import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from api.config import Settings
from api.enums import InstanceSource
from api.history.types import AppLogEntry, SeriesRef, StoreTuning, UsageReading
from api.history.writer import ConnectionLost, ForgetServer, Queued, Writer
from api.watch.usage import UsagePoint

TUNING = StoreTuning.from_settings(Settings(_env_file=None))


def _usage(server_uid: str, running: float) -> UsageReading:
    point = UsagePoint(datetime.now(UTC), running, None, None, None, None, None)
    return UsageReading(SeriesRef(server_uid, InstanceSource.DOCKER, "vllm-a"), point)


def _app_log(text: str) -> AppLogEntry:
    return AppLogEntry(datetime.now(UTC), "WARNING", "api.test", text, None)


async def _until(done: Callable[[], bool], timeout: float = 10.0) -> None:
    async with asyncio.timeout(timeout):
        while not done():
            await asyncio.sleep(0.01)


def test_writer_keeps_records_through_an_outage() -> None:
    flushed: list[Queued] = []
    failures = 2

    async def flush(batch: Sequence[Queued]) -> None:
        nonlocal failures
        if failures:
            failures -= 1
            raise ConnectionLost("store unreachable")
        flushed.extend(batch)

    records = [_usage("u1", n) for n in range(5)]

    async def run() -> Writer:
        writer = Writer(flush, replace(TUNING, flush_seconds=0.01, backoff_min_seconds=0.01))
        for record in records:
            writer.put(record)
        task = asyncio.create_task(writer.run())
        try:
            await _until(lambda: len(flushed) == len(records))
        finally:
            task.cancel()
        return writer

    writer = asyncio.run(run())
    assert flushed == records
    assert writer.dropped == {}


def test_writer_drops_oldest_when_full() -> None:
    flushed: list[Queued] = []

    async def flush(batch: Sequence[Queued]) -> None:
        flushed.extend(batch)

    entries = [_app_log(str(n).ljust(300)) for n in range(10)]
    writer = Writer(flush, replace(TUNING, queue_bytes=1000))
    for entry in entries:
        writer.put(entry)

    assert writer.dropped == {"app_logs": 7}
    assert writer.queued == 3
    assert asyncio.run(writer.drain(1.0)) == 0
    assert flushed == entries[-3:]


def test_writer_drops_records_of_forgotten_servers() -> None:
    flushed: list[Queued] = []

    async def flush(batch: Sequence[Queued]) -> None:
        flushed.extend(batch)

    writer = Writer(flush, TUNING)
    kept = _usage("u2", 1.0)
    writer.put(ForgetServer("u1"))
    writer.put(_usage("u1", 1.0))
    writer.put(kept)

    asyncio.run(writer.drain(1.0))
    assert flushed == [ForgetServer("u1"), kept]


def test_writer_errors_leave_out_the_statement() -> None:
    async def flush(batch: Sequence[Queued]) -> None:
        raise ValueError("value too long\n[SQL: INSERT INTO model_logs ...]\n[parameters: ('a user prompt',)]")

    writer = Writer(flush, TUNING)
    writer.put(_app_log("x"))
    asyncio.run(writer.drain(1.0))

    assert writer.dropped == {"app_logs": 1}
    assert writer.last_error == "ValueError: value too long"
