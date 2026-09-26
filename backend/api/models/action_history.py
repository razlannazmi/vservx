from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, utcnow


class ActionHistory(Base):
    __tablename__ = "action_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    # SET NULL so the audit log survives user/server/instance deletion.
    # user_id is also null for actions the app takes on its own (e.g. discovery scans).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"))
    instance_id: Mapped[int | None] = mapped_column(ForeignKey("instances.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text)
