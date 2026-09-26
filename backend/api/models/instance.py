from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base, str_enum, utcnow
from api.enums import LaunchType

if TYPE_CHECKING:
    from api.models.server import Server
    from api.models.snapshot import Snapshot


class Instance(Base):
    """A vLLM instance found by discovery; rows are refreshed on each scan."""

    __tablename__ = "instances"
    __table_args__ = (UniqueConstraint("server_id", "launch_type", "ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    launch_type: Mapped[LaunchType] = mapped_column(str_enum(LaunchType))
    # Container ID, unit name, or PID.
    ref: Mapped[str] = mapped_column(String(255))
    model: Mapped[str | None] = mapped_column(String(512))
    port: Mapped[int | None]
    managed: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)

    server: Mapped["Server"] = relationship(back_populates="instances")
    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="instance")
