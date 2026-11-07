from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base, str_enum
from api.enums import SnapshotKind

if TYPE_CHECKING:
    from api.models.instance import Instance


class Snapshot(Base):
    """One entry in an instance's history: how it was launched when vservx saw it, or that it was
    removed. Holds no secret values. Written once; only vllm_version and the fingerprint's re-keying
    change it afterwards."""

    __tablename__ = "snapshots"
    __table_args__ = (Index("ix_snapshots_server_happened", "server_id", "happened_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    instance_id: Mapped[int] = mapped_column(ForeignKey("instances.id", ondelete="CASCADE"), index=True)
    kind: Mapped[SnapshotKind] = mapped_column(str_enum(SnapshotKind))
    # When it happened as best known (Docker's Created time for first seen and recreated), and
    # when vservx saw it.
    happened_at: Mapped[datetime]
    noticed_at: Mapped[datetime]
    container_id: Mapped[str | None] = mapped_column(String(64))
    # Docker's Created and StartedAt times, and restart count, at capture.
    created_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    restart_count: Mapped[int | None]
    image_id: Mapped[str | None] = mapped_column(String(128))
    vllm_version: Mapped[str | None] = mapped_column(String(64))
    # The model it served, from its launch arguments, so old entries say what they ran.
    model: Mapped[str | None] = mapped_column(String(512))
    # The LaunchConfig (api/snapshots/config.py); None on removed entries.
    config: Mapped[dict[str, Any] | None]
    key_fingerprint: Mapped[str | None] = mapped_column(String(16))
    # Which HMAC key made the fingerprint.
    key_id: Mapped[str | None] = mapped_column(String(16))
    # The instance's last sighting; on removed entries only.
    last_seen: Mapped[datetime | None]

    instance: Mapped["Instance"] = relationship(back_populates="snapshots")
