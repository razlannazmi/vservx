from datetime import datetime

from pydantic import BaseModel

from api.enums import DatabaseState


class LastUpgradeRead(BaseModel):
    upgraded_at: datetime
    # The admin's name, or "command line".
    by: str
    from_revision: str
    to_revision: str


class BackupRead(BaseModel):
    name: str
    created_at: datetime


class DatabaseRead(BaseModel):
    state: DatabaseState
    current_revision: str | None
    head_revision: str
    # What the pending upgrade changes, one line per migration, oldest first.
    pending: list[str]
    last_upgrade: LastUpgradeRead | None
    latest_backup: BackupRead | None
