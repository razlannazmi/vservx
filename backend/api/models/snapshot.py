from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base, str_enum, utcnow
from api.enums import LaunchType, SnapshotTrigger

if TYPE_CHECKING:
    from api.models.instance import Instance


class Snapshot(Base):
    """A saved launch config. Outlives its instance so bare processes can be restarted."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("instances.id", ondelete="SET NULL"), index=True
    )
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    trigger: Mapped[SnapshotTrigger] = mapped_column(str_enum(SnapshotTrigger))
    launch_type: Mapped[LaunchType] = mapped_column(str_enum(LaunchType))
    command: Mapped[str | None] = mapped_column(Text)
    cwd: Mapped[str | None] = mapped_column(String(1024))
    run_user: Mapped[str | None] = mapped_column(String(255))
    # Secrets (e.g. HF_TOKEN) must be masked before they are stored here.
    env: Mapped[dict[str, Any] | None]
    image: Mapped[str | None] = mapped_column(String(512))
    gpus: Mapped[list[Any] | None]
    ports: Mapped[list[Any] | None]
    volumes: Mapped[list[Any] | None]
    vllm_version: Mapped[str | None] = mapped_column(String(64))
    # Full raw source: inspect JSON, unit file, or /proc data.
    raw: Mapped[str | None] = mapped_column(Text)

    instance: Mapped["Instance | None"] = relationship(back_populates="snapshots")
