from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class SSHConfigImport(BaseModel):
    # The text of the user's SSH config; the browser reads the file they pick.
    config: Annotated[str, Field(max_length=1_000_000)]


class ImportedHostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    name: str
    host: str
    port: int
    # None when the config sets no User; the user must enter one before saving.
    user: str | None
    identity_files: list[str]
    proxy_jump: list[str]
    warnings: list[str]


class SSHConfigPreview(BaseModel):
    """Proposed servers to review. Nothing is saved until they're created normally."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    hosts: list[ImportedHostRead]
    warnings: list[str]
