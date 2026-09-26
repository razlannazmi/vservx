from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, validates

from api.db.base import Base, str_enum, utcnow
from api.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), default=UserRole.VIEWER)
    # Deactivate instead of deleting so the account's audit history stays attributed.
    is_active: Mapped[bool] = mapped_column(default=True)
    # Embedded in issued JWTs; bump it to revoke every token issued before (password change, deactivation).
    token_version: Mapped[int] = mapped_column(default=0)
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    # Lowercased here, not just in the schema, so the unique constraint is case-insensitive.
    @validates("email")
    def _normalize_email(self, _: str, value: str) -> str:
        return value.strip().lower()
