from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUserDep, WorkspaceAccess, WorkspaceAccessDep, require_owner
from api.db.deps import SessionDep
from api.enums import WorkspaceRole
from api.models import WorkspaceMember
from api.schemas import (
    MemberAdd,
    MemberRead,
    MemberUpdate,
    OwnerChange,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from api.service.workspaces import (
    account_that_can_join,
    change_owner,
    create_workspace,
    delete_workspace,
    list_members,
    list_workspaces_for,
    member_read,
    name_taken,
    workspace_read,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_owner_only = [Depends(require_owner)]


def _unprocessable(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


async def _member_or_404(session: AsyncSession, access: WorkspaceAccess, user_id: int) -> WorkspaceMember:
    member = await session.get(WorkspaceMember, (access.workspace.id, user_id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return member


async def _name_free(session: AsyncSession, name: str, besides: int | None = None) -> None:
    # Names are unique across vservx, so the other workspace may be one the caller can't see.
    if await name_taken(session, name, besides=besides):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another workspace already has that name")


def _not_the_owner(member: WorkspaceMember) -> None:
    # A workspace always has exactly one owner; ownership moves only through a hand-over.
    if member.role is WorkspaceRole.OWNER:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="The owner can't leave or change role; hand the workspace to someone else first")


@router.get("", response_model=list[WorkspaceRead])
async def list_my_workspaces(user: CurrentUserDep, session: SessionDep) -> list[WorkspaceRead]:
    return await list_workspaces_for(session, user)


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_my_workspace(data: WorkspaceCreate, user: CurrentUserDep, session: SessionDep) -> WorkspaceRead:
    """Anyone signed in can create a workspace, and becomes its owner."""
    await _name_free(session, data.name)
    workspace = await create_workspace(session, user, data.name)
    return await workspace_read(session, workspace, WorkspaceRole.OWNER)


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(access: WorkspaceAccessDep, session: SessionDep) -> WorkspaceRead:
    return await workspace_read(session, access.workspace, access.role)


@router.patch("/{workspace_id}", response_model=WorkspaceRead, dependencies=_owner_only)
async def rename_workspace(data: WorkspaceUpdate, access: WorkspaceAccessDep, session: SessionDep) -> WorkspaceRead:
    # Changing only the case of its own name is fine.
    await _name_free(session, data.name, besides=access.workspace.id)
    access.workspace.name = data.name
    await session.commit()
    return await workspace_read(session, access.workspace, access.role)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_owner_only)
async def delete_my_workspace(access: WorkspaceAccessDep, session: SessionDep) -> None:
    """Delete the workspace with its servers, saved keys and everything attached to them."""
    await delete_workspace(session, access.workspace)


@router.post("/{workspace_id}/owner", response_model=WorkspaceRead, dependencies=_owner_only)
async def hand_over_workspace(
    data: OwnerChange, user: CurrentUserDep, access: WorkspaceAccessDep, session: SessionDep
) -> WorkspaceRead:
    """Hand the workspace to another member. The caller stays on as an operator."""
    try:
        await change_owner(session, access.workspace, data.user_id, must_be_member=True)
    except ValueError as exc:
        raise _unprocessable(exc) from None
    role = WorkspaceRole.OWNER if data.user_id == user.id else WorkspaceRole.OPERATOR
    return await workspace_read(session, access.workspace, role)


@router.get("/{workspace_id}/members", response_model=list[MemberRead])
async def get_members(access: WorkspaceAccessDep, session: SessionDep) -> list[MemberRead]:
    return await list_members(session, access.workspace.id)


@router.post("/{workspace_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED,
             dependencies=_owner_only)
async def add_member(data: MemberAdd, access: WorkspaceAccessDep, session: SessionDep) -> MemberRead:
    try:
        await account_that_can_join(session, data.user_id)
    except ValueError as exc:
        raise _unprocessable(exc) from None
    if await session.get(WorkspaceMember, (access.workspace.id, data.user_id)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already a member of this workspace")
    member = WorkspaceMember(workspace_id=access.workspace.id, user_id=data.user_id, role=data.role)
    session.add(member)
    await session.commit()
    return await member_read(session, member)


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberRead, dependencies=_owner_only)
async def change_member_role(
    user_id: int, data: MemberUpdate, access: WorkspaceAccessDep, session: SessionDep
) -> MemberRead:
    member = await _member_or_404(session, access, user_id)
    _not_the_owner(member)
    member.role = data.role
    await session.commit()
    return await member_read(session, member)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(user_id: int, user: CurrentUserDep, access: WorkspaceAccessDep, session: SessionDep) -> None:
    """The owner removes someone, or a member leaves."""
    if access.role is not WorkspaceRole.OWNER and user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    member = await _member_or_404(session, access, user_id)
    _not_the_owner(member)
    await session.delete(member)
    await session.commit()
