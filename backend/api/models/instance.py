from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base

if TYPE_CHECKING:
    from api.models.server import Server
    from api.models.snapshot import Snapshot


class Instance(Base):
    """A container name vservx has seen on a server: the identity snapshots belong to. Kept after
    the container is removed, so its snapshots stay."""

    __tablename__ = "instances"
    __table_args__ = (UniqueConstraint("server_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    # The current, or last seen, container's full ID.
    container_id: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(512))
    first_seen: Mapped[datetime]
    last_seen: Mapped[datetime]
    # When vservx noticed the container gone; None while it exists.
    removed_at: Mapped[datetime | None]

    server: Mapped["Server"] = relationship(back_populates="instances")
    snapshots: Mapped[list["Snapshot"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", passive_deletes=True
    )
