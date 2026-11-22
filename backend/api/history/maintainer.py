"""Keeps the history store in shape: day partitions ahead of time, rollups, and retention.

- Partitions are one UTC day each, named `<table>_pYYYYMMDD`, made for today and two days ahead.
- Rollups recompute whole buckets from `rollup_marks.done_until` up to the last whole bucket. The
  Writer moves a mark back when it stores older readings, so a late backlog is rolled up again.
- Retention drops whole partitions, and deletes in bounded batches from default partitions and
  unpartitioned tables.
- Every step takes a transaction-level advisory lock, so two vservx processes sharing a store
  don't maintain it at once.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from api.db.base import utcnow
from api.history.migrate import STORE_LOCK_ID
from api.history.schema import GPU_METRICS, USAGE_METRICS
from api.history.types import Retention

logger = logging.getLogger(__name__)

MAINTAIN_LOCK_ID = STORE_LOCK_ID + 1
DAY = timedelta(days=1)
DAYS_AHEAD = 2
# Rows removed per table per expire run from default partitions and unpartitioned tables.
DELETE_BATCH = 10_000
PERIOD_SECONDS = 60.0
EXPIRE_EVERY = timedelta(hours=1)
# date_bin's origin, so buckets line up with _floor.
ORIGIN = "TIMESTAMPTZ '1970-01-01 00:00:00+00'"

# Partitioned table -> its time column.
PARTITION_COLUMNS = {
    "usage_points": "at",
    "usage_1m": "bucket",
    "gpu_points": "at",
    "gpu_1m": "bucket",
    "model_logs": "at",
    "app_logs": "at",
}


@dataclass(frozen=True)
class _Rollup:
    name: str
    source: str
    source_time: str
    keys: tuple[str, ...]
    metrics: tuple[str, ...]
    step: timedelta
    # The finer rollup this one is built from; None when built from raw readings.
    finer: str | None
    # The most one run computes, so a long backlog is caught up in short transactions.
    max_span: timedelta


ROLLUPS = (
    _Rollup("usage_1m", "usage_points", "at", ("series_id",), USAGE_METRICS, timedelta(minutes=1), None, DAY),
    _Rollup("usage_1h", "usage_1m", "bucket", ("series_id",), USAGE_METRICS, timedelta(hours=1), "usage_1m", 7 * DAY),
    _Rollup("gpu_1m", "gpu_points", "at", ("server_uid", "gpu_index"), GPU_METRICS, timedelta(minutes=1), None, DAY),
    _Rollup("gpu_1h", "gpu_1m", "bucket", ("server_uid", "gpu_index"), GPU_METRICS, timedelta(hours=1), "gpu_1m",
            7 * DAY),
)


def _floor(at: datetime, step: timedelta) -> datetime:
    seconds = step.total_seconds()
    return datetime.fromtimestamp(at.timestamp() // seconds * seconds, UTC)


def _day(at: datetime) -> datetime:
    return _floor(at, DAY)


def _rollup_statement(rollup: _Rollup) -> str:
    keys = ", ".join(rollup.keys)
    columns = ["n"]
    values = []
    if rollup.finer is None:
        values.append("count(*)")
        for metric in rollup.metrics:
            columns += [f"{metric}_min", f"{metric}_avg", f"{metric}_max"]
            values += [f"min({metric})", f"avg({metric})", f"max({metric})"]
    else:
        values.append("sum(n)")
        for metric in rollup.metrics:
            columns += [f"{metric}_min", f"{metric}_avg", f"{metric}_max"]
            # Count-weighted: each finer bucket's average counts once per reading in it.
            has = f"FILTER (WHERE {metric}_avg IS NOT NULL)"
            values += [f"min({metric}_min)",
                       f"sum(n::float8 * {metric}_avg) {has} / nullif(sum(n) {has}, 0)",
                       f"max({metric}_max)"]
    step = f"{int(rollup.step.total_seconds())} seconds"
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns)
    return (
        f"INSERT INTO {rollup.name} ({keys}, bucket, {', '.join(columns)}) "
        f"SELECT {keys}, date_bin('{step}', {rollup.source_time}, {ORIGIN}), {', '.join(values)} "
        f"FROM {rollup.source} WHERE {rollup.source_time} >= :start AND {rollup.source_time} < :end "
        f"GROUP BY {keys}, {len(rollup.keys) + 1} "
        f"ON CONFLICT ({keys}, bucket) DO UPDATE SET {updates}"
    )


class Maintainer:
    def __init__(self, engine: AsyncEngine, retention: Retention) -> None:
        self._engine = engine
        self._retention = retention
        self._logged: set[str] = set()

    async def run(self) -> None:
        """Make partitions and roll up every minute, and expire old history every hour, until cancelled."""
        last_expire: datetime | None = None
        while True:
            now = utcnow()
            await self._attempt("make partitions", self.ensure_partitions(now))
            await self._attempt("roll up", self.roll_up(now))
            if last_expire is None or now - last_expire >= EXPIRE_EVERY:
                await self._attempt("expire", self.expire(now))
                last_expire = now
            await asyncio.sleep(PERIOD_SECONDS)

    async def ensure_partitions(self, now: datetime) -> None:
        first = _day(now)
        for table, column in PARTITION_COLUMNS.items():
            for offset in range(DAYS_AHEAD + 1):
                await self._ensure_partition(table, column, first + offset * DAY)

    async def roll_up(self, now: datetime) -> None:
        for rollup in ROLLUPS:
            async with self._engine.begin() as conn:
                await _lock(conn)
                await self._roll_up(conn, rollup, now)

    async def expire(self, now: datetime) -> None:
        days = {
            "usage_points": self._retention.raw_days,
            "usage_1m": self._retention.minute_days,
            "gpu_points": self._retention.raw_days,
            "gpu_1m": self._retention.minute_days,
            "model_logs": self._retention.model_log_days,
            "app_logs": self._retention.app_log_days,
        }
        unpartitioned = {
            "usage_1h": ("bucket", self._retention.hour_days),
            "gpu_1h": ("bucket", self._retention.hour_days),
            "state_changes": ("at", self._retention.event_days),
            "audit_entries": ("at", self._retention.audit_days),
        }
        # One transaction per table, so no table stays locked while another is cleaned.
        for table, column in PARTITION_COLUMNS.items():
            cutoff = now - timedelta(days=days[table])
            async with self._engine.begin() as conn:
                await _lock(conn)
                expired = [name for name in await _partitions(conn, table) if _expired(table, name, cutoff)]
                if expired:
                    # Parent first, as in _ensure_partition: DROP alone locks the partition before the parent.
                    await conn.execute(text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
                for name in expired:
                    await conn.execute(text(f"DROP TABLE {name}"))
                await _delete_before(conn, f"{table}_default", column, cutoff)
        for table, (column, table_days) in unpartitioned.items():
            async with self._engine.begin() as conn:
                await _lock(conn)
                await _delete_before(conn, table, column, now - timedelta(days=table_days))

    async def _ensure_partition(self, table: str, column: str, day: datetime) -> None:
        """Make one day's partition. Rows already in the default partition for that day move into it."""
        name = f"{table}_p{day:%Y%m%d}"
        default = f"{table}_default"
        bounds = {"start": day, "end": day + DAY}
        in_range = f"{column} >= :start AND {column} < :end"
        async with self._engine.begin() as conn:
            await _lock(conn)
            if (await conn.execute(text("SELECT to_regclass(:name)"), {"name": name})).scalar() is not None:
                return
            # - Parent first, the order every insert and delete takes: locking the default partition
            #   first would deadlock with them.
            # - Keeps the Writer from adding rows for this day to the default partition meanwhile.
            await conn.execute(text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
            stray = (await conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {default} WHERE {in_range})"),
                                        bounds)).scalar()
            if stray:
                await conn.execute(text(f"CREATE TEMP TABLE moved_rows (LIKE {table}) ON COMMIT DROP"))
                await conn.execute(text(
                    f"WITH moved AS (DELETE FROM {default} WHERE {in_range} RETURNING *) "
                    "INSERT INTO moved_rows SELECT * FROM moved"
                ), bounds)
            await conn.execute(text(
                f"CREATE TABLE {name} PARTITION OF {table} "
                f"FOR VALUES FROM ('{day.isoformat()}') TO ('{(day + DAY).isoformat()}')"
            ))
            if stray:
                await conn.execute(text(f"INSERT INTO {table} SELECT * FROM moved_rows"))

    async def _roll_up(self, conn: AsyncConnection, rollup: _Rollup, now: datetime) -> None:
        # FOR UPDATE makes a Writer that moves this mark back wait, so its move isn't overwritten below.
        mark = (await conn.execute(text("SELECT done_until FROM rollup_marks WHERE name = :name FOR UPDATE"),
                                   {"name": rollup.name})).scalar()
        if mark is None:
            first = (await conn.execute(text(f"SELECT min({rollup.source_time}) FROM {rollup.source}"))).scalar()
            mark = first or now
            await conn.execute(text("INSERT INTO rollup_marks (name, done_until) VALUES (:name, :at)"),
                               {"name": rollup.name, "at": mark})

        start = _floor(mark, rollup.step)
        end = _floor(now, rollup.step)
        if rollup.finer is not None:
            # Only hours whose minutes are all rolled up.
            finer = (await conn.execute(text("SELECT done_until FROM rollup_marks WHERE name = :name"),
                                        {"name": rollup.finer})).scalar()
            end = min(end, _floor(finer, rollup.step)) if finer is not None else start
        end = min(end, start + rollup.max_span)
        if end <= start:
            return
        await conn.execute(text(_rollup_statement(rollup)), {"start": start, "end": end})
        await conn.execute(text("UPDATE rollup_marks SET done_until = :end WHERE name = :name"),
                           {"name": rollup.name, "end": end})

    async def _attempt(self, step: str, work: Awaitable[None]) -> None:
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Once per step and error type, so a long outage doesn't flood the log.
            key = f"{step}:{type(exc).__name__}"
            if key not in self._logged:
                self._logged.add(key)
                logger.warning("History store maintenance could not %s: %s", step, exc)
        else:
            self._logged = {key for key in self._logged if not key.startswith(f"{step}:")}


def _expired(table: str, partition: str, cutoff: datetime) -> bool:
    """True for a day partition whose whole day is before cutoff. Other partitions are never dropped."""
    match = re.fullmatch(rf"{table}_p(\d{{8}})", partition)
    return match is not None and datetime.strptime(match[1], "%Y%m%d").replace(tzinfo=UTC) + DAY <= cutoff


async def _lock(conn: AsyncConnection) -> None:
    await conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MAINTAIN_LOCK_ID})


async def _partitions(conn: AsyncConnection, table: str) -> list[str]:
    rows = await conn.execute(text(
        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
        "WHERE i.inhparent = CAST(:table AS regclass)"
    ), {"table": table})
    return [row[0] for row in rows]


async def _delete_before(conn: AsyncConnection, table: str, column: str, cutoff: datetime) -> None:
    await conn.execute(text(
        f"DELETE FROM {table} WHERE ctid IN "
        f"(SELECT ctid FROM {table} WHERE {column} < :cutoff LIMIT {DELETE_BATCH})"
    ), {"cutoff": cutoff})
