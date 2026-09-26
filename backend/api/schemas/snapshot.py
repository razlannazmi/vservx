from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.enums import LaunchType, SnapshotTrigger


class SnapshotBase(BaseModel):
    """The captured launch config. Snapshots are immutable, so there is no update schema."""

    trigger: SnapshotTrigger
    launch_type: LaunchType
    command: str | None = None
    cwd: str | None = None
    run_user: str | None = None
    # Secrets (e.g. HF_TOKEN) must be masked before a snapshot is created.
    env: dict[str, Any] | None = None
    image: str | None = None
    gpus: list[Any] | None = None
    ports: list[Any] | None = None
    volumes: list[Any] | None = None
    vllm_version: str | None = None


class SnapshotCreate(SnapshotBase):
    server_id: int
    instance_id: int | None = None
    # Full raw source: inspect JSON, unit file, or /proc data.
    raw: str | None = None


class SnapshotRead(SnapshotBase):
    """Snapshot for lists and diffs; leaves out the potentially large raw source."""

    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    server_id: int
    instance_id: int | None
    created_at: datetime


class SnapshotDetail(SnapshotRead):
    raw: str | None
