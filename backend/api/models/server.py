from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base, str_enum, utcnow
from api.db.crypto import EncryptedString
from api.enums import AuthType
from api.ssh.keys import fingerprint_of

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
    # The saved key used for key auth; a key in use can't be deleted.
    ssh_key_id: Mapped[int | None] = mapped_column(ForeignKey("ssh_keys.id", ondelete="RESTRICT"), index=True)
    # The server directly in front of this one. Longer chains form from these links.
    jump_server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="RESTRICT"), index=True)
    # Only a doorway to other servers: tested and remembered, never searched for vLLM.
    jump_only: Mapped[bool] = mapped_column(default=False)
    # OpenSSH public key line recorded on the first successful login; only this key is accepted after.
    host_key: Mapped[str | None] = mapped_column(Text)
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
    def host_key_fingerprint(self) -> str | None:
        return fingerprint_of(self.host_key) if self.host_key else None
