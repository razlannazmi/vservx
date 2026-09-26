from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base, str_enum, utcnow
from api.db.crypto import EncryptedString
from api.enums import AuthType

if TYPE_CHECKING:
    from api.models.instance import Instance


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(default=22)
    username: Mapped[str] = mapped_column(String(255))
    auth_type: Mapped[AuthType] = mapped_column(str_enum(AuthType))
    password: Mapped[str | None] = mapped_column(EncryptedString)
    # Stored as entered (may start with "~"); expand with Path.expanduser() when connecting.
    key_path: Mapped[str | None] = mapped_column(String(1024))
    key_passphrase: Mapped[str | None] = mapped_column(EncryptedString)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    instances: Mapped[list["Instance"]] = relationship(
        back_populates="server", cascade="all, delete-orphan", passive_deletes=True
    )

    # Lets API responses report that a secret is set without exposing it.
    @property
    def has_password(self) -> bool:
        return self.password is not None

    @property
    def has_key_passphrase(self) -> bool:
        return self.key_passphrase is not None
