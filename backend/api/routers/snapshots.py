"""Launch snapshots of a server's containers: change lists, one snapshot's rebuilt command, comparing
two, and checking a key against a fingerprint. Every member may use them: nothing secret is stored."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import CurrentUserDep, WorkspaceAccessDep, workspace_access
from api.auth.limits import KeyCheckLimitsDep
from api.db.deps import SessionDep
from api.routers.servers import get_server_or_404
from api.schemas.snapshot import (
    CheckKeyRead,
    CheckKeyRequest,
    SnapshotCompareRead,
    SnapshotDetailRead,
    SnapshotPageRead,
)
from api.service import snapshots as service

router = APIRouter(prefix="/workspaces/{workspace_id}/servers/{server_id}", tags=["snapshots"],
                   dependencies=[Depends(workspace_access)])

Limit = Annotated[int, Query(ge=1, le=service.PAGE_SIZE)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")


async def _page(session: SessionDep, server_id: int, name: str | None, limit: int, before: str | None) -> SnapshotPageRead:
    try:
        return await service.list_snapshots(session, server_id, name, limit, before)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Bad `before` cursor") from None


@router.get("/snapshots", response_model=SnapshotPageRead)
async def list_server_snapshots(server_id: int, access: WorkspaceAccessDep, session: SessionDep,
                                limit: Limit = service.PAGE_SIZE, before: str | None = None) -> SnapshotPageRead:
    """Every instance's changes and removals on the server, newest first."""
    await get_server_or_404(session, access, server_id)
    return await _page(session, server_id, None, limit, before)


@router.get("/instances/{name}/snapshots", response_model=SnapshotPageRead)
async def list_instance_snapshots(server_id: int, name: str, access: WorkspaceAccessDep, session: SessionDep,
                                  limit: Limit = service.PAGE_SIZE, before: str | None = None) -> SnapshotPageRead:
    await get_server_or_404(session, access, server_id)
    return await _page(session, server_id, name, limit, before)


# Declared before /snapshots/{snapshot_id}, which would otherwise take "compare" as an ID.
@router.get("/snapshots/compare", response_model=SnapshotCompareRead)
async def compare_snapshots(server_id: int, access: WorkspaceAccessDep, session: SessionDep,
                            first: Annotated[int, Query(alias="from")],
                            second: Annotated[int, Query(alias="to")]) -> SnapshotCompareRead:
    """Any two snapshots of this server; the older is always "from"."""
    await get_server_or_404(session, access, server_id)
    try:
        return await service.compare_snapshots(session, server_id, first, second)
    except service.NotFound:
        raise _not_found() from None


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetailRead)
async def get_snapshot(server_id: int, snapshot_id: int, access: WorkspaceAccessDep,
                       session: SessionDep) -> SnapshotDetailRead:
    await get_server_or_404(session, access, server_id)
    try:
        return await service.get_snapshot(session, server_id, snapshot_id)
    except service.NotFound:
        raise _not_found() from None


@router.post("/snapshots/{snapshot_id}/check-key", response_model=CheckKeyRead)
async def check_key(server_id: int, snapshot_id: int, body: CheckKeyRequest, user: CurrentUserDep,
                    access: WorkspaceAccessDep, session: SessionDep, limits: KeyCheckLimitsDep) -> CheckKeyRead:
    """Whether a key matches the snapshot's API key fingerprint. The key is never stored or logged."""
    await get_server_or_404(session, access, server_id)
    limits.attempt(user.id)
    try:
        return await service.check_snapshot_key(session, server_id, snapshot_id, body.key)
    except service.NotFound:
        raise _not_found() from None
