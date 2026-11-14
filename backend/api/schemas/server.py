from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)

from api.enums import AuthType, ConnectionFailure, ServerKind

Text255 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Port = Annotated[int, Field(ge=1, le=65535)]


def check_auth_fields(auth_type: AuthType, password: SecretStr | str | None, ssh_key_id: int | None) -> None:
    """Ensure credentials match auth_type. Reuse on updates after merging with stored values."""
    if auth_type is AuthType.PASSWORD:
        if password is None:
            raise ValueError("password is required when auth_type is 'password'")
        if ssh_key_id is not None:
            raise ValueError("ssh_key_id is only allowed when auth_type is 'key'")
    else:
        if ssh_key_id is None:
            raise ValueError("ssh_key_id is required when auth_type is 'key'")
        if password is not None:
            raise ValueError("password is only allowed when auth_type is 'password'")


def check_kind_fields(
    kind: ServerKind,
    host: str | None,
    username: str | None,
    auth_type: AuthType | None,
    password: SecretStr | str | None,
    ssh_key_id: int | None,
    jump_server_id: int | None,
    jump_only: bool,
) -> None:
    """Ensure the connection fields match the server's kind. Reuse on updates after merging with stored values."""
    if kind is ServerKind.SSH:
        if host is None or username is None or auth_type is None:
            raise ValueError("host, username and auth_type are required for an SSH server")
        check_auth_fields(auth_type, password, ssh_key_id)
    elif any(value is not None for value in (host, username, auth_type, password, ssh_key_id, jump_server_id)) or jump_only:
        raise ValueError("This machine takes no host, login, key or jump settings")


class ServerBase(BaseModel):
    """Fields shared by every server schema. Secrets live only in Create/Update."""

    name: Text255
    kind: ServerKind = ServerKind.SSH
    host: Text255 | None = None
    port: Port = 22
    username: Text255 | None = None
    auth_type: AuthType | None = None
    ssh_key_id: int | None = None
    jump_server_id: int | None = None
    jump_only: bool = False


class ServerCreate(ServerBase):
    password: SecretStr | None = None
    # Only for running docker through sudo; a password server's sign-in password is used without it.
    sudo_password: SecretStr | None = None

    @model_validator(mode="after")
    def _check_auth(self) -> Self:
        check_kind_fields(self.kind, self.host, self.username, self.auth_type, self.password,
                          self.ssh_key_id, self.jump_server_id, self.jump_only)
        return self


class ServerUpdate(ServerBase):
    """Partial update: omitted fields are left unchanged, null clears an optional field.

    Apply with model_dump(exclude_unset=True), then run check_kind_fields on the merged result.
    """

    name: Text255 | None = None
    kind: ServerKind | None = None
    host: Text255 | None = None
    port: Port | None = None
    username: Text255 | None = None
    auth_type: AuthType | None = None
    jump_only: bool | None = None
    password: SecretStr | None = None
    sudo_password: SecretStr | None = None

    @model_validator(mode="after")
    def _reject_null_required(self) -> Self:
        # host, username and auth_type may be null in the request when the server is this machine.
        for field in ("name", "kind", "port", "jump_only"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class LastTestRead(BaseModel):
    """The latest connection test of a saved server."""

    at: datetime
    ok: bool
    elapsed_ms: int
    # What the server called itself; only on success.
    hostname: str | None
    # Only on failure: why, at which hop of the chain (by name), and that hop's message.
    failure: ConnectionFailure | None
    failed_hop: str | None
    message: str | None


class ServerRead(ServerBase):
    # Defaults inherited from Base would otherwise mark fields optional in the OpenAPI response schema.
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    # Secrets are never returned; these only say whether one is stored.
    has_password: bool
    has_sudo_password: bool
    # None until the first successful login records the server's host key.
    host_key_fingerprint: str | None
    host_key_type: str | None
    # Also None for a host key stored without a recorded date.
    host_key_recorded_at: datetime | None
    # None until the saved server is first tested.
    last_test: LastTestRead | None
    created_at: datetime
    updated_at: datetime


class ThisMachineRead(BaseModel):
    """Whether vservx can watch the machine it runs on, and what that machine calls itself."""

    available: bool
    reason: str | None
    hostname: str
