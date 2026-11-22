import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from api.enums import InstanceSource
from api.history import MemoryStore
from api.history.types import (
    AppLogQuery,
    AuditQuery,
    GpuReading,
    HistoryRequired,
    LogQuery,
    Retention,
    SeriesRef,
    Span,
    UsageReading,
)
from api.watch.usage import UsagePoint

RETENTION = Retention(7, 90, 365, 7, 30, 365, 365)
SERVER = "4b6f0c1e-0000-4000-8000-000000000001"
SERIES = SeriesRef(SERVER, InstanceSource.DOCKER, "vllm-a")


def _store() -> MemoryStore:
    return MemoryStore(timedelta(minutes=30), 5.0, RETENTION)


def _usage(at: datetime) -> UsageReading:
    return UsageReading(SERIES, UsagePoint(at, 1.0, 0.0, 10.0, None, None, None))


def _gpu(index: int, at: datetime) -> GpuReading:
    return GpuReading(SERVER, at, index, 50.0, 1000.0, 8000.0, 60.0)


def test_memory_store_serves_usage_within_window() -> None:
    store = _store()
    now = datetime.now(UTC)
    for minutes in (40, 10, 0):
        store.write(_usage(now - timedelta(minutes=minutes)))

    usage = asyncio.run(store.usage(SERIES, Span(now - timedelta(minutes=60), now), 720))

    assert [point.at for point in usage.points] == [now - timedelta(minutes=10), now]
    assert usage.resolution_seconds == 5
    assert usage.degraded is False


def test_memory_store_gpus_by_index() -> None:
    store = _store()
    now = datetime.now(UTC)
    for index in (1, 0):
        store.write(_gpu(index, now))

    history = asyncio.run(store.gpus(SERVER, Span(now - timedelta(minutes=5), now), 720))

    assert [gpu.index for gpu in history.gpus] == [0, 1]
    assert all(len(gpu.points) == 1 for gpu in history.gpus)


def test_memory_store_needs_a_store_for_stored_reads() -> None:
    store = _store()
    now = datetime.now(UTC)
    span = Span(now - timedelta(hours=1), now)
    reads = [
        store.events(SERVER, span, None),
        store.logs(SERIES, LogQuery(span, None, None, None, 100)),
        store.audit(AuditQuery(span, None, None, None, None, 100)),
        store.app_logs(AppLogQuery(span, None, None, None, None, 100)),
    ]
    for read in reads:
        with pytest.raises(HistoryRequired):
            asyncio.run(read)


def test_memory_store_forgets_a_server() -> None:
    store = _store()
    now = datetime.now(UTC)
    store.write(_usage(now))
    store.write(_gpu(0, now))

    store.forget_server(SERVER)

    span = Span(now - timedelta(minutes=5), now)
    assert asyncio.run(store.usage(SERIES, span, 720)).points == []
    assert asyncio.run(store.gpus(SERVER, span, 720)).gpus == []
