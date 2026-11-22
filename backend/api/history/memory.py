"""The history store used without a database: usage and GPU readings for a short window, in memory."""

import threading
from collections import deque
from datetime import timedelta
from typing import TypeVar

from api.db.base import utcnow
from api.enums import StoreState
from api.history.types import (
    AppLogPage,
    AppLogQuery,
    AuditPage,
    AuditQuery,
    GpuHistory,
    GpuPoint,
    GpuReading,
    GpuSeries,
    HistoryRequired,
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
from api.watch.usage import UsagePoint

K = TypeVar("K")
V = TypeVar("V")


class MemoryStore:
    """Keeps the last `window` of usage and GPU readings.

    - One ring per series and one per (server uid, GPU index), each sized to hold `window`.
    - Reads trim to `window` before now, so a series that stopped reporting ages out.
    - Every other record is dropped; reads of them raise HistoryRequired.
    """

    persistent = False

    def __init__(self, window: timedelta, interval_seconds: float, retention: Retention) -> None:
        self._window = window
        self._interval_seconds = interval_seconds
        self._retention = retention
        self._length = max(1, round(window.total_seconds() / interval_seconds))
        self._lock = threading.Lock()
        self._usage: dict[SeriesRef, deque[UsagePoint]] = {}
        self._gpus: dict[tuple[str, int], deque[GpuPoint]] = {}

    def status(self) -> StoreStatus:
        return StoreStatus(persistent=False, state=StoreState.OFF, retention=self._retention, queued=0,
                           dropped={}, last_error=None, last_write_at=None)

    def schema(self) -> StoreSchema | None:
        return None

    async def upgrade(self) -> bool:
        return False

    def write(self, record: Record) -> None:
        with self._lock:
            if isinstance(record, UsageReading):
                self._ring(self._usage, record.series).append(record.point)
            elif isinstance(record, GpuReading):
                point = GpuPoint(record.at, record.utilization, record.memory_used, record.memory_total,
                                 record.temperature)
                self._ring(self._gpus, (record.server_uid, record.index)).append(point)

    def forget_server(self, server_uid: str) -> None:
        with self._lock:
            for series in [series for series in self._usage if series.server_uid == server_uid]:
                del self._usage[series]
            for key in [key for key in self._gpus if key[0] == server_uid]:
                del self._gpus[key]

    def forget_request_lines(self, server_uid: str) -> None:
        return None

    async def usage(self, series: SeriesRef, span: Span, max_points: int) -> UsageSeries:
        start = max(span.start, utcnow() - self._window)
        with self._lock:
            points = [point for point in self._usage.get(series, ()) if start <= point.at <= span.end]
        return UsageSeries(points=points, resolution_seconds=self._interval_seconds, degraded=False)

    async def gpus(self, server_uid: str, span: Span, max_points: int) -> GpuHistory:
        start = max(span.start, utcnow() - self._window)
        with self._lock:
            rings = sorted((index, list(ring)) for (uid, index), ring in self._gpus.items() if uid == server_uid)
        gpus = [GpuSeries(index, [point for point in ring if start <= point.at <= span.end]) for index, ring in rings]
        return GpuHistory(gpus=[gpu for gpu in gpus if gpu.points], resolution_seconds=self._interval_seconds,
                          degraded=False)

    async def events(self, server_uid: str, span: Span, series: SeriesRef | None) -> list[StateChange]:
        raise HistoryRequired

    async def logs(self, series: SeriesRef, query: LogQuery) -> LogPage:
        raise HistoryRequired

    async def audit(self, query: AuditQuery) -> AuditPage:
        raise HistoryRequired

    async def app_logs(self, query: AppLogQuery) -> AppLogPage:
        raise HistoryRequired

    async def resume(self, server_uid: str) -> ResumePoint:
        return ResumePoint(None, {}, {})

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def _ring(self, rings: dict[K, deque[V]], key: K) -> deque[V]:
        ring = rings.get(key)
        if ring is None:
            ring = rings[key] = deque(maxlen=self._length)
        return ring
