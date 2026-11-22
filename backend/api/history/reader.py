"""Reads from the PostgreSQL history store, and the guard every read goes through.

- Usage and GPU reads use the table pick_resolution chooses, re-aggregated into buckets one step
  wide: averages weighted by reading count. Raw readings at the reading interval come back as stored.
- ReadGuard puts a hard time limit on each read and stops trying for a while after repeated
  failures, so a slow store doesn't slow every chart.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, TypeVar

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncEngine

from api.db.base import utcnow
from api.enums import InstanceSource
from api.history.maintainer import ORIGIN
from api.history.resolution import Resolution, pick_resolution
from api.history.schema import GPU_METRICS, USAGE_METRICS
from api.history.types import (
    GpuHistory,
    GpuPoint,
    GpuSeries,
    HistoryUnavailable,
    LogCursor,
    ResumePoint,
    Retention,
    SeriesRef,
    Span,
    StateChange,
    UsageSeries,
)
from api.watch.frameworks import instance_key
from api.watch.usage import UsagePoint

T = TypeVar("T")

# SQLSTATE classes worth trying again for:
# - can't reach or get in: connection exceptions, authorization, missing database, shutdown
# - busy: insufficient resources
# - transaction rolled back: serialization failure, deadlock
RETRY_SQLSTATES = ("08", "28", "3D", "53", "57P", "40")

_SERIES_ID = "SELECT id FROM series WHERE server_uid = :uid AND source = :source AND name = :name"


def is_connection_problem(exc: BaseException) -> bool:
    """True when the same statement may succeed if sent again: the error isn't about what was sent."""
    if isinstance(exc, OSError | TimeoutError | InterfaceError):
        return True
    if isinstance(exc, DBAPIError):
        if exc.connection_invalidated:
            return True
        state = getattr(exc.orig, "sqlstate", None)
        return isinstance(state, str) and state.startswith(RETRY_SQLSTATES)
    return False


class ReadGuard:
    """Runs store reads with a time limit, and pauses reading after repeated failures.

    - `limit` covers getting a connection and running the query.
    - A timeout or connection problem counts as a failure; `failures` in a row pause reads for `pause`
      seconds, during which reads raise HistoryUnavailable without touching the store.
    - Other errors are bugs, not outages: they propagate unchanged.
    """

    def __init__(self, limit: float, failures: int, pause: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._max_failures = failures
        self._pause = pause
        self._clock = clock
        self._failures = 0
        self._paused_until: float | None = None

    async def run(self, read: Callable[[], Awaitable[T]]) -> T:
        if self._paused_until is not None and self._clock() < self._paused_until:
            raise HistoryUnavailable
        try:
            async with asyncio.timeout(self._limit):
                result = await read()
        except Exception as exc:
            if not is_connection_problem(exc):
                raise
            self._failures += 1
            if self._failures >= self._max_failures:
                self._paused_until = self._clock() + self._pause
            raise HistoryUnavailable from exc
        self._failures = 0
        self._paused_until = None
        return result


def _weighted(metric: str) -> str:
    has = f"FILTER (WHERE {metric}_avg IS NOT NULL)"
    return f"sum(n::float8 * {metric}_avg) {has} / nullif(sum(n) {has}, 0)"


def _bucketed(source: str, keys: str, where: str, metrics: tuple[str, ...], resolution: Resolution,
              interval_seconds: float) -> str:
    """SELECT [keys,] at, metrics... from the resolution's table, one row per bucket per key."""
    lead = f"{keys}, " if keys else ""
    order = f"{lead}at"
    if resolution.table == "raw":
        if resolution.step_seconds == interval_seconds:
            return (f"SELECT {lead}at, {', '.join(metrics)} FROM {source}_points "
                    f"WHERE {where} AND at >= :start AND at <= :end ORDER BY {order}")
        values = ", ".join(f"avg({metric}) AS {metric}" for metric in metrics)
        time_column, table = "at", f"{source}_points"
    else:
        values = ", ".join(f"{_weighted(metric)} AS {metric}" for metric in metrics)
        time_column, table = "bucket", f"{source}_{resolution.table}"
    groups = f"{keys}, 2" if keys else "1"
    return (f"SELECT {lead}date_bin(:step, {time_column}, {ORIGIN}) AS at, {values} FROM {table} "
            f"WHERE {where} AND {time_column} >= :start AND {time_column} <= :end "
            f"GROUP BY {groups} ORDER BY {order}")


class Reader:
    def __init__(self, engine: AsyncEngine, retention: Retention, interval_seconds: float, event_limit: int) -> None:
        self._engine = engine
        self._retention = retention
        self._interval_seconds = interval_seconds
        # The most state changes one events read returns: the newest in the span.
        self._event_limit = event_limit

    async def usage(self, series: SeriesRef, span: Span, max_points: int) -> UsageSeries:
        resolution = self._resolution(span, max_points)
        sql = _bucketed("usage", "", f"series_id = ({_SERIES_ID})", USAGE_METRICS, resolution,
                        self._interval_seconds)
        rows = await self._rows(sql, {**_series_params(series), **_span_params(span, resolution)})
        points = [UsagePoint(row.at, *(getattr(row, metric) for metric in USAGE_METRICS)) for row in rows]
        return UsageSeries(points=points, resolution_seconds=resolution.step_seconds, degraded=False)

    async def gpus(self, server_uid: str, span: Span, max_points: int) -> GpuHistory:
        resolution = self._resolution(span, max_points)
        sql = _bucketed("gpu", "gpu_index", "server_uid = :uid", GPU_METRICS, resolution, self._interval_seconds)
        rows = await self._rows(sql, {"uid": server_uid, **_span_params(span, resolution)})
        by_index: dict[int, list[GpuPoint]] = {}
        for row in rows:
            point = GpuPoint(row.at, *(getattr(row, metric) for metric in GPU_METRICS))
            by_index.setdefault(row.gpu_index, []).append(point)
        gpus = [GpuSeries(index, points) for index, points in sorted(by_index.items())]
        return GpuHistory(gpus=gpus, resolution_seconds=resolution.step_seconds, degraded=False)

    async def events(self, server_uid: str, span: Span, series: SeriesRef | None) -> list[StateChange]:
        only = "AND s.server_uid = :uid AND s.source = :source AND s.name = :name" if series else ""
        rows = await self._rows(
            "SELECT * FROM (SELECT c.at, c.id, s.source, s.name, c.from_state, c.to_state, c.message "
            "FROM state_changes c LEFT JOIN series s ON s.id = c.series_id "
            f"WHERE c.server_uid = :uid AND c.at >= :start AND c.at <= :end {only} "
            "ORDER BY c.at DESC, c.id DESC LIMIT :limit) newest ORDER BY at, id",
            {"uid": server_uid, "start": span.start, "end": span.end, "limit": self._event_limit,
             **(_series_params(series) if series else {})},
        )
        return [StateChange(server_uid, _series(server_uid, row.source, row.name), row.at, row.from_state,
                            row.to_state, row.message) for row in rows]

    async def resume(self, server_uid: str) -> ResumePoint:
        params = {"uid": server_uid}
        server = await self._rows(
            "SELECT to_state FROM state_changes WHERE server_uid = :uid AND series_id IS NULL "
            "ORDER BY at DESC, id DESC LIMIT 1", params)
        instances = await self._rows(
            "SELECT DISTINCT ON (c.series_id) s.source, s.name, c.to_state "
            "FROM state_changes c JOIN series s ON s.id = c.series_id WHERE c.server_uid = :uid "
            "ORDER BY c.series_id, c.at DESC, c.id DESC", params)
        cursors = await self._rows(
            "SELECT s.source, s.name, l.at, l.at_count, l.journal "
            "FROM log_cursors l JOIN series s ON s.id = l.series_id WHERE s.server_uid = :uid", params)
        return ResumePoint(
            server_state=server[0].to_state if server else None,
            # A removed instance's last change has no to_state: it has nothing to resume.
            instance_states={instance_key(InstanceSource(row.source), row.name): row.to_state
                             for row in instances if row.to_state is not None},
            log_cursors={instance_key(InstanceSource(row.source), row.name): LogCursor(row.at, row.at_count,
                                                                                          row.journal)
                         for row in cursors},
        )

    def _resolution(self, span: Span, max_points: int) -> Resolution:
        return pick_resolution(span, max_points, utcnow(), self._retention, self._interval_seconds)

    async def _rows(self, sql: str, params: dict[str, Any]) -> list[Any]:
        async with self._engine.connect() as conn:
            return list(await conn.execute(text(sql), params))


def _series_params(series: SeriesRef) -> dict[str, str]:
    return {"uid": series.server_uid, "source": str(series.source), "name": series.name}


def _span_params(span: Span, resolution: Resolution) -> dict[str, Any]:
    return {"start": span.start, "end": span.end, "step": timedelta(seconds=resolution.step_seconds)}


def _series(server_uid: str, source: str | None, name: str | None) -> SeriesRef | None:
    return SeriesRef(server_uid, InstanceSource(source), name) if source is not None and name is not None else None
