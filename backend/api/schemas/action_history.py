from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ActionHistoryBase(BaseModel):
    """An audit log entry. Entries are never edited, so there is no update schema."""

    server_id: int | None
    instance_id: int | None
    action: str
    result: str
    detail: str | None = None


class ActionHistoryCreate(ActionHistoryBase):
    pass


class ActionHistoryRead(ActionHistoryBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    created_at: datetime
