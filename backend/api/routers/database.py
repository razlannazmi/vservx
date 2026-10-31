from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import require_admin
from api.db import migrate
from api.enums import DatabaseState
from api.models import User
from api.schemas import DatabaseRead
from api.service.database import DatabaseGate, DatabaseGateDep

# Reachable while an upgrade waits; every other router is blocked until it's done.
router = APIRouter(prefix="/database", tags=["database"])


def _database_read(gate: DatabaseGate) -> DatabaseRead:
    backup = migrate.newest_backup(gate.db_path)
    latest = None if backup is None else {
        "name": backup.name,
        "created_at": datetime.fromtimestamp(backup.stat().st_mtime, UTC),
    }
    return DatabaseRead.model_validate(asdict(gate.status) | {"latest_backup": latest})


@router.get("", response_model=DatabaseRead)
async def get_database(gate: DatabaseGateDep) -> DatabaseRead:
    await gate.refresh()
    return _database_read(gate)


@router.post("/upgrade", response_model=DatabaseRead)
async def upgrade_database(
    gate: DatabaseGateDep, user: Annotated[User, Depends(require_admin)]
) -> DatabaseRead:
    try:
        await gate.upgrade(user)
    except migrate.UpgradeError as exc:
        newer = gate.status is not None and gate.status.state is DatabaseState.NEWER_THAN_APP
        code = status.HTTP_409_CONFLICT if newer else status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(status_code=code, detail=str(exc)) from None
    return _database_read(gate)
