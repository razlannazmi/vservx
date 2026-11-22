import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from api.history.reader import ReadGuard
from api.history.resolution import Resolution, pick_resolution
from api.history.types import HistoryUnavailable, Retention, Span

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
RETENTION = Retention(7, 90, 365, 7, 30, 365, 365)


@pytest.mark.parametrize(("minutes", "expected"), [
    (30, Resolution("raw", 5)),
    (24 * 60, Resolution("1m", 120)),
    (7 * 24 * 60, Resolution("1m", 840)),
    (90 * 24 * 60, Resolution("1h", 10800)),
])
def test_pick_resolution(minutes: int, expected: Resolution) -> None:
    span = Span(NOW - timedelta(minutes=minutes), NOW)
    assert pick_resolution(span, 720, NOW, RETENTION, 5.0) == expected


def test_read_guard_times_out_then_pauses() -> None:
    clock = [1000.0]
    calls = 0

    async def slow_read() -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(10)

    async def attempt(guard: ReadGuard) -> None:
        with pytest.raises(HistoryUnavailable):
            await guard.run(slow_read)

    async def run() -> list[int]:
        guard = ReadGuard(limit=0.05, failures=3, pause=30.0, clock=lambda: clock[0])
        seen = []
        for _ in range(4):
            await attempt(guard)
            seen.append(calls)
        clock[0] += 31
        await attempt(guard)
        seen.append(calls)
        return seen

    # Three reads time out; the fourth is refused without reading; after the pause, reads resume.
    assert asyncio.run(run()) == [1, 2, 3, 3, 4]
