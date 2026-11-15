"""An instance's warning and critical thresholds. Every member sees them; only operators and the owner
change them, since everyone in the workspace sees the same lines."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from api.auth import CurrentUserDep, WorkspaceAccessDep, require_operator, workspace_access
from api.db.deps import SessionDep
from api.enums import InstanceSource, ThresholdMetric
from api.models import Instance
from api.routers.servers import get_server_or_404
from api.schemas.threshold import InstanceThresholdsRead, ThresholdRead, ThresholdWrite
from api.service import thresholds as service
from api.service.servers import can_see_this_machine

router = APIRouter(prefix="/workspaces/{workspace_id}/servers/{server_id}/instances/{name}/thresholds",
                   tags=["thresholds"], dependencies=[Depends(workspace_access)])

_operator_only = [Depends(require_operator)]


async def _instance_or_404(session: SessionDep, access: WorkspaceAccessDep, user: CurrentUserDep, server_id: int,
                           source: InstanceSource, name: str) -> Instance:
    """The instance vservx has seen on the server, removed or not. This machine's instances are as
    good as missing to someone who may not see them."""
    server = await get_server_or_404(session, access, server_id)
    instance = await session.scalar(select(Instance).where(
        Instance.server_id == server.id, Instance.source == source, Instance.name == name))
    if instance is None or not await can_see_this_machine(session, server, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return instance


@router.get("", response_model=InstanceThresholdsRead)
async def get_thresholds(server_id: int, name: str, access: WorkspaceAccessDep, user: CurrentUserDep,
                         session: SessionDep, source: InstanceSource = InstanceSource.DOCKER) -> InstanceThresholdsRead:
    instance = await _instance_or_404(session, access, user, server_id, source, name)
    return InstanceThresholdsRead(thresholds=await service.read_all(session, instance.id))


@router.put("/{metric}", response_model=ThresholdRead, dependencies=_operator_only)
async def set_threshold(server_id: int, name: str, metric: ThresholdMetric, body: ThresholdWrite,
                        access: WorkspaceAccessDep, user: CurrentUserDep, session: SessionDep,
                        source: InstanceSource = InstanceSource.DOCKER) -> ThresholdRead:
    instance = await _instance_or_404(session, access, user, server_id, source, name)
    try:
        return await service.save(session, instance.id, metric, body.warning, body.critical)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.delete("/{metric}", response_model=ThresholdRead, dependencies=_operator_only)
async def reset_threshold(server_id: int, name: str, metric: ThresholdMetric, access: WorkspaceAccessDep,
                          user: CurrentUserDep, session: SessionDep,
                          source: InstanceSource = InstanceSource.DOCKER) -> ThresholdRead:
    """Back to the metric's default. Resetting one already at its default changes nothing."""
    instance = await _instance_or_404(session, access, user, server_id, source, name)
    return await service.reset(session, instance.id, metric)
