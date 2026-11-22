"""The history store on PostgreSQL.

- `write` never waits on the database: records go to the Writer's queue, and usage and GPU
  readings also go to an in-memory window that reads fall back on.
- `start` returns at once. A background task finds the store's schema, creates it when the
  database is empty, then lets the Writer and Maintainer run. While the database can't be
  reached it tries again every 30 s, and records stay queued.
- A store that needs an upgrade, or was written by a newer vservx, is left alone: the Writer stays
  paused until an admin upgrades.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import timedelta

from sqlalchemy import Table, bindparam, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.functions import func

from api.enums import DatabaseState, InstanceSource, StoreState
from api.history import schema
from api.history.maintainer import Maintainer
from api.history.memory import MemoryStore
from api.history.migrate import create_store, inspect_store, store_engine, upgrade_store
from api.history.types import (
    AppLogEntry,
    AppLogPage,
    AppLogQuery,
    AuditEntry,
    AuditPage,
    AuditQuery,
    GpuHistory,
    GpuReading,
    HistoryUnavailable,
    LogLines,
    LogPage,
    LogQuery,
    Record,
    Retention,
    ResumePoint,
    SeriesRef,
    Span,
    StateChange,
    StoreSchema,
    StoreStatus,
    UsageReading,
    UsageSeries,
)
from api.history.writer import ConnectionLost, ForgetRequestLines, ForgetServer, Queued, Writer

logger = logging.getLogger(__name__)

RETRY_SECONDS = 30.0
CONNECT_TIMEOUT_SECONDS = 10.0
STOP_FLUSH_SECONDS = 5.0
# SQLSTATE classes worth retrying the same batch for:
# - can't reach or get in: connection exceptions, authorization, missing database, shutdown
# - busy: insufficient resources
# - transaction rolled back: serialization failure, deadlock
RETRY_SQLSTATES = ("08", "28", "3D", "53", "57P", "40")

_STATES = {
    DatabaseState.CURRENT: StoreState.OK,
    DatabaseState.UPGRADE_REQUIRED: StoreState.UPGRADE_REQUIRED,
    DatabaseState.NEWER_THAN_APP: StoreState.NEWER_THAN_APP,
}


def is_connection_problem(exc: BaseException) -> bool:
    """True when the batch may succeed if sent again: the error isn't about what was sent."""
    if isinstance(exc, OSError | TimeoutError | InterfaceError):
        return True
    if isinstance(exc, DBAPIError):
        if exc.connection_invalidated:
            return True
        state = getattr(exc.orig, "sqlstate", None)
        return isinstance(state, str) and state.startswith(RETRY_SQLSTATES)
    return False


class PostgresStore:
    persistent = True

    def __init__(self, url: str, retention: Retention, window: timedelta, interval_seconds: float) -> None:
        self._engine = store_engine(url)
        self._retention = retention
        self._memory = MemoryStore(window, interval_seconds, retention)
        self._writer = Writer(self._flush)
        self._writer.paused = True
        self._maintainer = Maintainer(self._engine, retention)
        self._state = StoreState.UNREACHABLE
        self._schema: StoreSchema | None = None
        self._error: str | None = None
        # Series ids already in the store, so most batches don't look them up.
        self._series: dict[SeriesRef, int] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._maintaining: asyncio.Task[None] | None = None

    def status(self) -> StoreStatus:
        state = self._state
        if state is StoreState.OK and self._writer.retrying:
            state = StoreState.UNREACHABLE
        return StoreStatus(persistent=True, state=state, retention=self._retention, queued=self._writer.queued,
                           dropped=dict(self._writer.dropped), last_error=self._writer.last_error or self._error,
                           last_write_at=self._writer.last_write_at)

    def schema(self) -> StoreSchema | None:
        return self._schema

    async def upgrade(self) -> bool:
        if self._state is not StoreState.UPGRADE_REQUIRED:
            return False
        changed = await upgrade_store(self._engine)
        self._apply(await inspect_store(self._engine))
        return changed

    def write(self, record: Record) -> None:
        if isinstance(record, UsageReading | GpuReading):
            self._memory.write(record)
        self._writer.put(record)

    def forget_server(self, server_uid: str) -> None:
        self._memory.forget_server(server_uid)
        self._writer.put(ForgetServer(server_uid))

    def forget_request_lines(self, server_uid: str) -> None:
        self._writer.put(ForgetRequestLines(server_uid))

    async def usage(self, series: SeriesRef, span: Span, max_points: int) -> UsageSeries:
        return replace(await self._memory.usage(series, span, max_points), degraded=True)

    async def gpus(self, server_uid: str, span: Span, max_points: int) -> GpuHistory:
        return replace(await self._memory.gpus(server_uid, span, max_points), degraded=True)

    async def events(self, server_uid: str, span: Span, series: SeriesRef | None) -> list[StateChange]:
        raise HistoryUnavailable

    async def logs(self, series: SeriesRef, query: LogQuery) -> LogPage:
        raise HistoryUnavailable

    async def audit(self, query: AuditQuery) -> AuditPage:
        raise HistoryUnavailable

    async def app_logs(self, query: AppLogQuery) -> AppLogPage:
        raise HistoryUnavailable

    async def resume(self, server_uid: str) -> ResumePoint:
        return ResumePoint(None, {}, {})

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._writer.run()), asyncio.create_task(self._connect())]

    async def stop(self) -> None:
        tasks = [*self._tasks, *([self._maintaining] if self._maintaining else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        lost = await self._writer.drain(STOP_FLUSH_SECONDS)
        if lost:
            logger.warning("%d history records were not written to the history store before shutdown", lost)
        await self._engine.dispose()

    async def _connect(self) -> None:
        """Find the store's schema, creating it in an empty database, retrying while unreachable."""
        while True:
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
                    found = await inspect_store(self._engine)
                    if found.state is DatabaseState.NEW:
                        await create_store(self._engine)
                        found = await inspect_store(self._engine)
            except Exception as exc:
                if self._error is None:
                    logger.warning("The history store can't be reached; trying again every %ds: %s",
                                   int(RETRY_SECONDS), exc)
                self._state = StoreState.UNREACHABLE
                self._error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(RETRY_SECONDS)
                continue
            self._apply(found)
            return

    def _apply(self, found: StoreSchema) -> None:
        self._schema = found
        self._state = _STATES[found.state]
        self._error = None
        if self._state is StoreState.OK:
            self._writer.paused = False
            if self._maintaining is None:
                self._maintaining = asyncio.create_task(self._maintainer.run())
            return
        self._writer.paused = True
        if self._state is StoreState.UPGRADE_REQUIRED:
            logger.warning("The history store needs an upgrade; history isn't kept until an admin runs "
                           "`vservx db upgrade` or uses the upgrade button")
        else:
            logger.warning("The history store was written by a newer vservx; history isn't kept")

    async def _flush(self, batch: Sequence[Queued]) -> None:
        """Write one batch in one transaction, in the order it was queued."""
        staged: dict[SeriesRef, int] = {}
        forgotten: list[str] = []
        try:
            async with self._engine.begin() as conn:
                records: list[Record] = []
                for item in batch:
                    if isinstance(item, ForgetServer | ForgetRequestLines):
                        await self._insert(conn, records, staged)
                        records = []
                        await _forget(conn, item)
                        if isinstance(item, ForgetServer):
                            forgotten.append(item.server_uid)
                    else:
                        records.append(item)
                await self._insert(conn, records, staged)
        except Exception as exc:
            if is_connection_problem(exc):
                raise ConnectionLost(str(exc)) from exc
            raise
        self._series.update(staged)
        for uid in forgotten:
            self._series = {ref: id_ for ref, id_ in self._series.items() if ref.server_uid != uid}

    async def _insert(self, conn: AsyncConnection, records: list[Record], staged: dict[SeriesRef, int]) -> None:
        if not records:
            return
        refs = {r.series for r in records if isinstance(r, UsageReading | LogLines)}
        refs |= {r.series for r in records if isinstance(r, StateChange) and r.series is not None}
        ids = await self._series_ids(conn, refs, staged)

        usage = [{"series_id": ids[r.series], **asdict(r.point)} for r in records if isinstance(r, UsageReading)]
        gpus = [{"server_uid": r.server_uid, "gpu_index": r.index, "at": r.at, "utilization": r.utilization,
                 "memory_used": r.memory_used, "memory_total": r.memory_total, "temperature": r.temperature}
                for r in records if isinstance(r, GpuReading)]
        changes = [{"server_uid": r.server_uid, "series_id": ids[r.series] if r.series else None, "at": r.at,
                    "from_state": r.from_state, "to_state": r.to_state, "message": r.message}
                   for r in records if isinstance(r, StateChange)]
        logs = [r for r in records if isinstance(r, LogLines)]
        lines = [{"series_id": ids[r.series], **asdict(line)} for r in logs for line in r.lines]
        # The newest cursor per series: one statement can't upsert a row twice.
        cursors = {ids[r.series]: r.cursor for r in logs}
        audit = [asdict(r) for r in records if isinstance(r, AuditEntry)]
        app_logs = [asdict(r) for r in records if isinstance(r, AppLogEntry)]

        for table, rows in ((schema.usage_points, usage), (schema.gpu_points, gpus),
                            (schema.state_changes, changes), (schema.model_logs, lines),
                            (schema.audit_entries, audit), (schema.app_logs, app_logs)):
            if rows:
                await conn.execute(insert(table), rows)
        if cursors:
            statement = pg_insert(schema.log_cursors).values(
                [{"series_id": id_, **asdict(cursor)} for id_, cursor in cursors.items()]
            )
            await conn.execute(statement.on_conflict_do_update(
                index_elements=["series_id"],
                set_={"at": statement.excluded.at, "at_count": statement.excluded.at_count,
                      "journal": statement.excluded.journal},
            ))
        # Readings older than a rollup's mark move it back, so the Maintainer rolls those buckets up again.
        for rows, names in ((usage, ("usage_1m", "usage_1h")), (gpus, ("gpu_1m", "gpu_1h"))):
            if rows:
                oldest = min(row["at"] for row in rows)
                await conn.execute(
                    update(schema.rollup_marks)
                    .where(schema.rollup_marks.c.name.in_(names))
                    .values(done_until=func.least(schema.rollup_marks.c.done_until, bindparam("oldest"))),
                    {"oldest": oldest},
                )

    async def _series_ids(self, conn: AsyncConnection, refs: set[SeriesRef],
                          staged: dict[SeriesRef, int]) -> dict[SeriesRef, int]:
        missing = [ref for ref in refs if ref not in self._series and ref not in staged]
        if missing:
            table = schema.series
            statement = pg_insert(table).values(
                [{"server_uid": ref.server_uid, "source": str(ref.source), "name": ref.name} for ref in missing]
            )
            # DO UPDATE rather than DO NOTHING, so RETURNING gives ids of rows that already existed.
            statement = statement.on_conflict_do_update(
                index_elements=["server_uid", "source", "name"], set_={"name": statement.excluded.name}
            ).returning(table.c.id, table.c.server_uid, table.c.source, table.c.name)
            for row in await conn.execute(statement):
                staged[SeriesRef(row.server_uid, InstanceSource(row.source), row.name)] = row.id
        return {**self._series, **staged}


async def _forget(conn: AsyncConnection, item: ForgetServer | ForgetRequestLines) -> None:
    uid = item.server_uid
    series_ids = select(schema.series.c.id).where(schema.series.c.server_uid == uid).scalar_subquery()
    if isinstance(item, ForgetRequestLines):
        await conn.execute(delete(schema.model_logs).where(
            schema.model_logs.c.request, schema.model_logs.c.series_id.in_(series_ids)
        ))
        return
    by_series: list[Table] = [schema.usage_points, schema.usage_1m, schema.usage_1h, schema.model_logs,
                              schema.log_cursors]
    for table in by_series:
        await conn.execute(delete(table).where(table.c.series_id.in_(series_ids)))
    by_server: list[Table] = [schema.state_changes, schema.gpu_points, schema.gpu_1m, schema.gpu_1h]
    for table in by_server:
        await conn.execute(delete(table).where(table.c.server_uid == uid))
    await conn.execute(delete(schema.series).where(schema.series.c.server_uid == uid))
