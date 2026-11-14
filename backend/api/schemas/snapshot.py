"""Launch snapshots as the API shows them. Nothing here holds a secret value: secrets are placeholders."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from api.enums import InstanceSource, SnapshotKind

# Defaults would otherwise mark fields optional in the OpenAPI response schema.
_READ = ConfigDict(json_schema_serialization_defaults_required=True)


class DifferenceRead(BaseModel):
    model_config = _READ

    label: str
    # None on one side means added or removed.
    before: str | None
    after: str | None
    note: str | None


class SnapshotEntryRead(BaseModel):
    model_config = _READ

    id: int
    # The container or unit name.
    instance: str
    source: InstanceSource
    # The model it served, from its launch arguments.
    model: str | None
    kind: SnapshotKind
    happened_at: datetime
    noticed_at: datetime
    # On removed entries: when the container was last seen.
    last_seen: datetime | None
    # 12 characters.
    container_id: str | None
    # Against the instance's previous snapshot; empty for first seen and removed entries.
    differences: list[DifferenceRead]


class SnapshotPageRead(BaseModel):
    model_config = _READ

    # Newest first.
    entries: list[SnapshotEntryRead]
    # Pass as `before` for the next page; None on the last one.
    next_before: str | None


class SnapshotDetailRead(SnapshotEntryRead):
    image: str | None
    image_id: str | None
    vllm_version: str | None
    created_at: datetime | None
    started_at: datetime | None
    restart_count: int | None
    # The rebuilt `docker run`, secrets as placeholders; None on removed entries.
    command: str | None
    # Which options the command covers.
    covers: str
    # Set when docker compose started the container.
    compose: str | None
    # Set when the server's Docker could only send env names.
    env_hidden: str | None
    env_values_hidden: bool
    key_fingerprint: str | None


class SnapshotCompareRead(BaseModel):
    model_config = _READ

    # The older of the two, by when each happened.
    from_snapshot: SnapshotDetailRead
    to_snapshot: SnapshotDetailRead
    differences: list[DifferenceRead]


class CheckKeyRequest(BaseModel):
    key: str = Field(max_length=4096)


class CheckKeyRead(BaseModel):
    model_config = _READ

    # None when it can't be checked; `reason` says why.
    matches: bool | None
    reason: str | None
