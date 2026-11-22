import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, validates

from api.db.base import Base, str_enum, utcnow
from api.enums import WorkspaceRole


class Workspace(Base):
    """A fence around a set of servers and saved keys, with its own members."""

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Names this workspace in the history store, which outlives the row; SQLite can reuse a deleted row's id.
    uid: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    # The name case-folded: unique, so "Homelab" and "homelab" can't both exist. The web app's
    # addresses are made from names.
    name_key: Mapped[str] = mapped_column(String(255), unique=True)
    # A movingicons icon name, chosen by the owner. None: the UI's default icon.
    icon: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @validates("name")
    def _fold_name(self, _: str, value: str) -> str:
        self.name_key = value.casefold()
        return value


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        # Exactly one owner per workspace: at most one here, and ownership only ever moves.
        Index("ix_workspace_members_one_owner", "workspace_id", unique=True, sqlite_where=text("role = 'owner'")),
    )

    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[WorkspaceRole] = mapped_column(str_enum(WorkspaceRole))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
