"""An instance's usage over the last few minutes, from its metric readings."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from api.watch.frameworks import MetricSample


@dataclass(frozen=True)
class UsagePoint:
    at: datetime
    running: float | None
    waiting: float | None
    kv_cache_percent: float | None
    tokens_in_per_s: float | None
    tokens_out_per_s: float | None
    ttft_seconds: float | None


def _went_down(before: MetricSample, now: MetricSample) -> bool:
    """A counter lower than last time: the instance restarted and its counters began again."""
    pairs = [(before.prompt_tokens, now.prompt_tokens), (before.generation_tokens, now.generation_tokens),
             (before.ttft_count, now.ttft_count)]
    return any(old is not None and new is not None and new < old for old, new in pairs)


def _rate(old: float | None, new: float | None, seconds: float) -> float | None:
    if old is None or new is None or seconds <= 0:
        return None
    return (new - old) / seconds


def _ttft(oldest: MetricSample, now: MetricSample) -> float | None:
    """Average time to first token of the requests that got one since the oldest reading."""
    if oldest.ttft_sum is None or oldest.ttft_count is None or now.ttft_sum is None or now.ttft_count is None:
        return None
    if now.ttft_count <= oldest.ttft_count:
        return None
    return (now.ttft_sum - oldest.ttft_sum) / (now.ttft_count - oldest.ttft_count)


class UsageHistory:
    """One instance's points to chart, oldest first. Time to first token is averaged over the
    last minute, so one slow request doesn't make the line jump about every reading."""

    def __init__(self, length: int, ttft_window_seconds: float = 60.0) -> None:
        self._points: deque[UsagePoint] = deque(maxlen=length)
        self._window = timedelta(seconds=ttft_window_seconds)
        # Readings since the counters last began, back to the start of the window.
        self._readings: deque[tuple[datetime, MetricSample]] = deque()

    def add(self, sample: MetricSample, at: datetime) -> UsagePoint:
        previous = self._readings[-1] if self._readings else None
        if previous is not None and _went_down(previous[1], sample):
            # Rates across a restart would be negative or huge: skip this interval.
            self._readings.clear()
            previous = None
        self._readings.append((at, sample))
        while self._readings[0][0] < at - self._window:
            self._readings.popleft()

        seconds = (at - previous[0]).total_seconds() if previous else 0.0
        before = previous[1] if previous else None
        point = UsagePoint(
            at=at,
            running=sample.running,
            waiting=sample.waiting,
            kv_cache_percent=sample.kv_cache * 100 if sample.kv_cache is not None else None,
            tokens_in_per_s=_rate(before.prompt_tokens, sample.prompt_tokens, seconds) if before else None,
            tokens_out_per_s=_rate(before.generation_tokens, sample.generation_tokens, seconds) if before else None,
            ttft_seconds=_ttft(self._readings[0][1], sample),
        )
        self._points.append(point)
        return point

    @property
    def points(self) -> list[UsagePoint]:
        return list(self._points)

    @property
    def latest(self) -> UsagePoint | None:
        return self._points[-1] if self._points else None
