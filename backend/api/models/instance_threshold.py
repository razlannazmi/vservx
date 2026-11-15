from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base, str_enum
from api.enums import ThresholdMetric

if TYPE_CHECKING:
    from api.models.instance import Instance


class InstanceThreshold(Base):
    """Where one metric of an instance turns amber (warning) and red (critical), for everyone in
    the workspace. A reading above a value has crossed it.
    - No row: the metric's default.
    - A row with both values null: no lines, even where the default has some."""

    __tablename__ = "instance_thresholds"
    __table_args__ = (UniqueConstraint("instance_id", "metric"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int] = mapped_column(ForeignKey("instances.id", ondelete="CASCADE"), index=True)
    metric: Mapped[ThresholdMetric] = mapped_column(str_enum(ThresholdMetric))
    warning: Mapped[float | None]
    critical: Mapped[float | None]

    instance: Mapped["Instance"] = relationship(back_populates="thresholds")
