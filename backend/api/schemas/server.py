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

from api.enums import AuthType

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


class ServerBase(BaseModel):
    """Fields shared by every server schema. Secrets live only in Create/Update."""

    name: Text255
    host: Text255
    port: Port = 22
    username: Text255
    auth_type: AuthType
    ssh_key_id: int | None = None
    jump_server_id: int | None = None
    jump_only: bool = False


class ServerCreate(ServerBase):
    password: SecretStr | None = None

    @model_validator(mode="after")
    def _check_auth(self) -> Self:
        check_auth_fields(self.auth_type, self.password, self.ssh_key_id)
        return self


class ServerUpdate(ServerBase):
    """Partial update: omitted fields are left unchanged, null clears an optional field.

    Apply with model_dump(exclude_unset=True), then run check_auth_fields on the merged result.
    """

    name: Text255 | None = None
    host: Text255 | None = None
    port: Port | None = None
    username: Text255 | None = None
    auth_type: AuthType | None = None
    jump_only: bool | None = None
    password: SecretStr | None = None

    @model_validator(mode="after")
    def _reject_null_required(self) -> Self:
        for field in ("name", "host", "port", "username", "auth_type", "jump_only"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ServerRead(ServerBase):
    # Defaults inherited from Base would otherwise mark fields optional in the OpenAPI response schema.
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    # Secrets are never returned; these only say whether one is stored.
    has_password: bool
    # None until the first successful login records the server's host key.
    host_key_fingerprint: str | None
    created_at: datetime
    updated_at: datetime
