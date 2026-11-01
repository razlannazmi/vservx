from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, str_enum, utcnow
from api.enums import WorkspaceRole


class Workspace(Base):
    """A fence around a set of servers and saved keys, with its own members."""

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Not unique: each person sees only their own list.
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


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
