from datetime import datetime

from pydantic import BaseModel

from api.enums import DatabaseState, StoreState


class HistoryStatusRead(BaseModel):
    # False: no store is set, and history stays in memory only.
    persistent: bool
    state: StoreState
    # Days kept per kind: raw, minute, hour, model_logs, app_logs, events, audit.
    retention_days: dict[str, int]
    # Admins only; None for everyone else.
    queued: int | None = None
    # Records dropped, by kind.
    dropped: dict[str, int] | None = None
    last_error: str | None = None
    last_write_at: datetime | None = None


class HistoryDatabaseRead(BaseModel):
    """The history store's schema, beside SQLite's in the database page."""

    state: DatabaseState
    current_revision: str | None
    head_revision: str
    # What the pending store upgrade changes, one line per migration, oldest first.
    pending: list[str]
