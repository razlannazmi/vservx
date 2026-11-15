"""Instance thresholds: the defaults, the rules a pair of values must follow, and reading and writing them."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import ThresholdMetric
from api.models import InstanceThreshold
from api.schemas.threshold import ThresholdRead

# (warning, critical) for an instance that hasn't set its own.
# - KV cache near full means requests start to queue or be preempted, on any model.
# - A good time to first token or queue length depends on the model and its users, so none is guessed.
DEFAULTS: dict[ThresholdMetric, tuple[float | None, float | None]] = {
    ThresholdMetric.WAITING: (None, None),
    ThresholdMetric.KV_CACHE_PERCENT: (90.0, 98.0),
    ThresholdMetric.TTFT_SECONDS: (None, None),
}


def check(metric: ThresholdMetric, warning: float | None, critical: float | None) -> None:
    """Raises ValueError, with a message for the user, when the values don't make sense together."""
    if warning is not None and critical is not None and warning >= critical:
        raise ValueError("Warning must be below critical")
    if metric is ThresholdMetric.KV_CACHE_PERCENT and any(each is not None and each > 100 for each in (warning, critical)):
        raise ValueError("KV cache thresholds can't be above 100%")


def _read(metric: ThresholdMetric, row: InstanceThreshold | None) -> ThresholdRead:
    if row is None:
        warning, critical = DEFAULTS[metric]
        return ThresholdRead(metric=metric, warning=warning, critical=critical, is_default=True)
    return ThresholdRead(metric=metric, warning=row.warning, critical=row.critical, is_default=False)


async def _row(session: AsyncSession, instance_id: int, metric: ThresholdMetric) -> InstanceThreshold | None:
    return await session.scalar(select(InstanceThreshold).where(
        InstanceThreshold.instance_id == instance_id, InstanceThreshold.metric == metric))


async def read_all(session: AsyncSession, instance_id: int) -> list[ThresholdRead]:
    """Every metric's thresholds, in the enum's order."""
    rows = {row.metric: row for row in await session.scalars(
        select(InstanceThreshold).where(InstanceThreshold.instance_id == instance_id))}
    return [_read(metric, rows.get(metric)) for metric in ThresholdMetric]


async def save(session: AsyncSession, instance_id: int, metric: ThresholdMetric,
               warning: float | None, critical: float | None) -> ThresholdRead:
    """Set both values, replacing the default. Raises ValueError as check() does."""
    check(metric, warning, critical)
    row = await _row(session, instance_id, metric)
    if row is None:
        row = InstanceThreshold(instance_id=instance_id, metric=metric)
        session.add(row)
    row.warning, row.critical = warning, critical
    await session.commit()
    return _read(metric, row)


async def reset(session: AsyncSession, instance_id: int, metric: ThresholdMetric) -> ThresholdRead:
    """Back to the metric's default."""
    await session.execute(delete(InstanceThreshold).where(
        InstanceThreshold.instance_id == instance_id, InstanceThreshold.metric == metric))
    await session.commit()
    return _read(metric, None)
