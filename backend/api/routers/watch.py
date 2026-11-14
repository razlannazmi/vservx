"""What vservx sees on a workspace's servers. Answered from memory: only Refresh reaches a server."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from api.auth import WorkspaceAccessDep, workspace_access
from api.db.deps import SessionDep
from api.enums import InstanceSource
from api.models import Server
from api.routers.servers import get_server_or_404
from api.schemas.watch import InstanceHistoryRead, ServerWatchRead, WatchSummaryRead
from api.watch.watcher import Watcher

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["watch"], dependencies=[Depends(workspace_access)])


def _watcher(request: Request) -> Watcher:
    return request.app.state.watcher


WatcherDep = Annotated[Watcher, Depends(_watcher)]


@router.get("/watch", response_model=list[WatchSummaryRead])
async def list_watch_summaries(access: WorkspaceAccessDep, session: SessionDep, watcher: WatcherDep) -> Sequence[WatchSummaryRead]:
    """One line per server in the workspace, for its card."""
    server_ids = await session.scalars(
        select(Server.id).where(Server.workspace_id == access.workspace.id).order_by(Server.name))
    return [watcher.summary(server_id) for server_id in server_ids]


@router.get("/servers/{server_id}/watch", response_model=ServerWatchRead)
async def get_server_watch(server_id: int, access: WorkspaceAccessDep, session: SessionDep,
                           watcher: WatcherDep) -> ServerWatchRead:
    await get_server_or_404(session, access, server_id)
    return watcher.view(server_id)


@router.get("/servers/{server_id}/instances/{name}/history", response_model=InstanceHistoryRead)
async def get_instance_history(server_id: int, name: str, access: WorkspaceAccessDep, session: SessionDep,
                               watcher: WatcherDep,
                               source: InstanceSource = InstanceSource.DOCKER) -> InstanceHistoryRead:
    await get_server_or_404(session, access, server_id)
    history = watcher.history(server_id, source, name)
    if history is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return history


# Open to every member: it only reads, and it's limited to once every few seconds per server.
@router.post("/servers/{server_id}/refresh", response_model=ServerWatchRead)
async def refresh_server(server_id: int, access: WorkspaceAccessDep, session: SessionDep,
                         watcher: WatcherDep) -> ServerWatchRead:
    """Look for instances on the server now."""
    await get_server_or_404(session, access, server_id)
    return await watcher.refresh(server_id)
