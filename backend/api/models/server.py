from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base, str_enum, utcnow
from api.db.crypto import EncryptedString
from api.enums import AuthType, ConnectionFailure, ServerKind
from api.ssh.keys import fingerprint_of

if TYPE_CHECKING:
    from api.models.instance import Instance


class Server(Base):
    __tablename__ = "servers"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Deleting a workspace deletes its servers first (api.service.workspaces.delete_workspace).
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[ServerKind] = mapped_column(
        str_enum(ServerKind), default=ServerKind.SSH, server_default=ServerKind.SSH.value
    )
    # host, username and auth_type are empty for the this-machine kind.
    host: Mapped[str | None] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(default=22)
    username: Mapped[str | None] = mapped_column(String(255))
    auth_type: Mapped[AuthType | None] = mapped_column(str_enum(AuthType))
    password: Mapped[str | None] = mapped_column(EncryptedString)
    # Used only to run `docker ps` / `docker inspect` through sudo. Without it, a password
    # server's sign-in password is used.
    sudo_password: Mapped[str | None] = mapped_column(EncryptedString)
    # The saved key used for key auth; a key in use can't be deleted.
    ssh_key_id: Mapped[int | None] = mapped_column(ForeignKey("ssh_keys.id", ondelete="RESTRICT"), index=True)
    # The server directly in front of this one. Longer chains form from these links.
    jump_server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="RESTRICT"), index=True)
    # Only a doorway to other servers: tested and remembered, never searched for vLLM.
    jump_only: Mapped[bool] = mapped_column(default=False)
    # OpenSSH public key line recorded on the first successful login; only this key is accepted after.
    host_key: Mapped[str | None] = mapped_column(Text)
    # When host_key was recorded; None for a key stored without a recorded date.
    host_key_recorded_at: Mapped[datetime | None]
    # The latest connection test of this saved server (tests of unsaved settings aren't kept).
    last_test_at: Mapped[datetime | None]
    last_test_ok: Mapped[bool | None]
    last_test_elapsed_ms: Mapped[int | None]
    # What the server called itself; only on success.
    last_test_hostname: Mapped[str | None] = mapped_column(String(255))
    # Only on failure: why, at which hop of the chain, and the hop's message.
    last_test_failure: Mapped[ConnectionFailure | None] = mapped_column(str_enum(ConnectionFailure))
    last_test_failed_hop: Mapped[str | None] = mapped_column(String(255))
    last_test_message: Mapped[str | None] = mapped_column(Text)
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
    def has_sudo_password(self) -> bool:
        return self.sudo_password is not None

    @property
    def host_key_fingerprint(self) -> str | None:
        return fingerprint_of(self.host_key) if self.host_key else None

    @property
    def host_key_type(self) -> str | None:
        # The first word of an OpenSSH public key line, e.g. "ssh-ed25519".
        return self.host_key.split(maxsplit=1)[0] if self.host_key else None

    @property
    def last_test(self) -> dict[str, Any] | None:
        if self.last_test_at is None:
            return None
        return {"at": self.last_test_at, "ok": self.last_test_ok, "elapsed_ms": self.last_test_elapsed_ms,
                "hostname": self.last_test_hostname, "failure": self.last_test_failure,
                "failed_hop": self.last_test_failed_hop, "message": self.last_test_message}
