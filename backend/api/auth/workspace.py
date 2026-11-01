"""Who may do what inside a workspace, checked from the workspace id in the path."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from api.auth.deps import CurrentUserDep
from api.db.deps import SessionDep
from api.enums import WorkspaceRole
from api.models import Workspace, WorkspaceMember


@dataclass(frozen=True)
class WorkspaceAccess:
    workspace: Workspace
    role: WorkspaceRole


async def workspace_access(workspace_id: int, user: CurrentUserDep, session: SessionDep) -> WorkspaceAccess:
    # Not a member looks exactly like no such workspace, so ids don't reveal what exists.
    row = (await session.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(Workspace.id == workspace_id, WorkspaceMember.user_id == user.id)
    )).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return WorkspaceAccess(workspace=row[0], role=row[1])


WorkspaceAccessDep = Annotated[WorkspaceAccess, Depends(workspace_access)]


def _require(role: WorkspaceRole, access: WorkspaceAccess) -> WorkspaceAccess:
    if not access.role.at_least(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{role.value.title()} role required")
    return access


async def require_operator(access: WorkspaceAccessDep) -> WorkspaceAccess:
    return _require(WorkspaceRole.OPERATOR, access)


async def require_owner(access: WorkspaceAccessDep) -> WorkspaceAccess:
    return _require(WorkspaceRole.OWNER, access)
