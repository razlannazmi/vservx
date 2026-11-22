"""Which table a usage or GPU read uses, and how wide its buckets are."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from api.history.schema import HOUR, MINUTE
from api.history.types import Retention, Span

Table = Literal["raw", "1m", "1h"]


@dataclass(frozen=True)
class Resolution:
    table: Table
    step_seconds: float


def pick_resolution(span: Span, max_points: int, now: datetime, retention: Retention,
                    interval_seconds: float) -> Resolution:
    """The coarsest table that still shows about max_points points across the span.

    - step: the span divided by max_points, never less than the reading interval.
    - Only tables whose retention reaches back to the span's start count.
    - Of those, the coarsest whose bucket is no wider than the step wins.
    - When every one is wider, the finest is used, and the step widens to its bucket.
    - When none reaches back, hour rollups are used: they're kept longest.
    """
    step = max(interval_seconds, (span.end - span.start).total_seconds() / max_points)
    tables: list[tuple[Table, float, int]] = [
        ("raw", interval_seconds, retention.raw_days),
        ("1m", MINUTE.total_seconds(), retention.minute_days),
        ("1h", HOUR.total_seconds(), retention.hour_days),
    ]
    reaching = [(name, bucket) for name, bucket, days in tables if now - timedelta(days=days) <= span.start]
    if not reaching:
        return Resolution("1h", max(step, HOUR.total_seconds()))
    fitting = [(name, bucket) for name, bucket in reaching if bucket <= step]
    if fitting:
        return Resolution(fitting[-1][0], step)
    name, bucket = reaching[0]
    return Resolution(name, max(step, bucket))
