from fastapi import APIRouter

from api.auth import CurrentUserDep
from api.enums import UserRole
from api.history.deps import HistoryDep
from api.schemas.history import HistoryStatusRead

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/status", response_model=HistoryStatusRead)
async def history_status(history: HistoryDep, user: CurrentUserDep) -> HistoryStatusRead:
    """Whether history is kept, and for how long. The queue and errors are for admins only."""
    status = history.status()
    read = HistoryStatusRead(persistent=status.persistent, state=status.state,
                             retention_days=status.retention.as_dict())
    if user.role is UserRole.ADMIN:
        read.queued = status.queued
        read.dropped = status.dropped
        read.last_error = status.last_error
        read.last_write_at = status.last_write_at
    return read
