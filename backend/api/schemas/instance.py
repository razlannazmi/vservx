from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.enums import LaunchType


class InstanceBase(BaseModel):
    """State refreshed on each discovery scan."""

    model: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    managed: bool = False
    status: str = "unknown"


class InstanceCreate(InstanceBase):
    # Identity of the instance on its server; fixed once created.
    server_id: int
    launch_type: LaunchType
    # Container ID, unit name, or PID.
    ref: str


class InstanceUpdate(InstanceBase):
    """Partial update from a rescan; apply with model_dump(exclude_unset=True)."""

    managed: bool | None = None
    status: str | None = None
    last_seen: datetime | None = None

    @model_validator(mode="after")
    def _reject_null_required(self) -> Self:
        for field in ("managed", "status", "last_seen"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class InstanceRead(InstanceBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    server_id: int
    launch_type: LaunchType
    ref: str
    last_seen: datetime
