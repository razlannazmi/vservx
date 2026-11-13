from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import CurrentUserDep, WorkspaceAccess, WorkspaceAccessDep, require_operator, workspace_access
from api.config import get_settings
from api.db.deps import SessionDep
from api.enums import ServerKind, UserRole
from api.models import Server, User
from api.schemas import ServerCreate, ServerRead, ServerUpdate
from api.schemas.connection import ConnectionTestResult, HostKeyAccept
from api.schemas.ssh_config import ImportedHostRead, SSHConfigImport, SSHConfigPreview
from api.service.connections import (
    ChainUnreachable,
    HostKeyMismatch,
    accept_host_key,
    check_server_connection,
    check_this_machine,
)
from api.service.servers import (
    apply_server_update,
    can_see_this_machine,
    check_links,
    count_servers_behind,
    has_this_machine,
    owner_is_admin,
    server_from_create,
)
from api.ssh.config_import import parse_ssh_config
from api.watch import local

router = APIRouter(prefix="/workspaces/{workspace_id}/servers", tags=["servers"],
                   dependencies=[Depends(workspace_access)])

# Stored credentials give shell access to the server, so only operators and the owner add or change them.
_operator_only = [Depends(require_operator)]


async def get_server_or_404(session: AsyncSession, access: WorkspaceAccess, server_id: int) -> Server:
    server = await session.get(Server, server_id)
    # Another workspace's server is as good as missing.
    if server is None or server.workspace_id != access.workspace.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return server


def _unprocessable(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _require_app_admin(user: User) -> None:
    # The host's own hostname and what runs on it are for app admins only, even to test.
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only app admins can add or change this machine")


async def _check_can_hold_this_machine(session: AsyncSession, user: User, workspace_id: int) -> None:
    """The checks for adding this machine to a workspace, in order. Raises HTTPException."""
    _require_app_admin(user)
    if reason := local.unavailable_reason():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=reason)
    if not await owner_is_admin(session, workspace_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="This machine can only be in a workspace whose owner is an app admin")
    if await has_this_machine(session, workspace_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This workspace already has this machine")


@router.get("", response_model=list[ServerRead])
async def list_servers(access: WorkspaceAccessDep, session: SessionDep) -> Sequence[Server]:
    return (await session.scalars(
        select(Server).where(Server.workspace_id == access.workspace.id).order_by(Server.name)
    )).all()


@router.post("", response_model=ServerRead, status_code=status.HTTP_201_CREATED, dependencies=_operator_only)
async def create_server(
    data: ServerCreate, user: CurrentUserDep, access: WorkspaceAccessDep, session: SessionDep
) -> Server:
    if data.kind is ServerKind.THIS_MACHINE:
        await _check_can_hold_this_machine(session, user, access.workspace.id)
    server = server_from_create(data, access.workspace.id)
    try:
        await check_links(session, server)
    except ValueError as exc:
        raise _unprocessable(exc) from None
    session.add(server)
    await session.commit()
    return server


@router.post("/test", response_model=ConnectionTestResult, dependencies=_operator_only)
async def test_unsaved_server(
    data: ServerCreate, user: CurrentUserDep, access: WorkspaceAccessDep, session: SessionDep
) -> ConnectionTestResult:
    """Test settings before saving them. Nothing is stored for this server; saved jump hosts
    in its chain have their host keys recorded as usual."""
    if data.kind is ServerKind.THIS_MACHINE:
        await _check_can_hold_this_machine(session, user, access.workspace.id)
        return await check_this_machine(session, server_from_create(data, access.workspace.id))
    server = server_from_create(data, access.workspace.id)
    try:
        await check_links(session, server)
        return await check_server_connection(session, server, get_settings().ssh_connect_timeout)
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.post("/import-ssh-config", response_model=SSHConfigPreview, dependencies=_operator_only)
def preview_ssh_config_import(data: SSHConfigImport) -> SSHConfigPreview:
    """Read an uploaded SSH config into proposed servers. Saves nothing."""
    hosts, warnings = parse_ssh_config(data.config)
    return SSHConfigPreview(hosts=[ImportedHostRead.model_validate(host) for host in hosts], warnings=warnings)


@router.post("/{server_id}/test", response_model=ConnectionTestResult)
async def test_saved_server(
    server_id: int, user: CurrentUserDep, access: WorkspaceAccessDep, session: SessionDep
) -> ConnectionTestResult:
    server = await get_server_or_404(session, access, server_id)
    if server.kind is ServerKind.THIS_MACHINE:
        # Its hostname and status are hidden from everyone but app admins while no admin owns the workspace.
        if not await can_see_this_machine(session, server, user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This machine needs an admin owner")
        return await check_this_machine(session, server)
    try:
        return await check_server_connection(session, server, get_settings().ssh_connect_timeout)
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.post("/{server_id}/host-key/accept", response_model=ServerRead, dependencies=_operator_only)
async def accept_server_host_key(
    server_id: int, data: HostKeyAccept, access: WorkspaceAccessDep, session: SessionDep
) -> Server:
    server = await get_server_or_404(session, access, server_id)
    if server.kind is ServerKind.THIS_MACHINE:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="This machine has no host key to accept")
    try:
        await accept_host_key(session, server, data.fingerprint, get_settings().ssh_connect_timeout)
    except HostKeyMismatch:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="The server is presenting a different key than the one you approved") from None
    except ChainUnreachable as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    except ValueError as exc:
        raise _unprocessable(exc) from None
    return server


@router.get("/{server_id}", response_model=ServerRead)
async def get_server(server_id: int, access: WorkspaceAccessDep, session: SessionDep) -> Server:
    return await get_server_or_404(session, access, server_id)


@router.patch("/{server_id}", response_model=ServerRead, dependencies=_operator_only)
async def update_server(
    server_id: int, data: ServerUpdate, user: CurrentUserDep, access: WorkspaceAccessDep, session: SessionDep
) -> Server:
    server = await get_server_or_404(session, access, server_id)
    kind = data.kind or server.kind
    if ServerKind.THIS_MACHINE in (kind, server.kind):
        # Operators may rename this machine; anything else about it is for app admins.
        if data.model_fields_set - {"name"}:
            _require_app_admin(user)
        if kind is ServerKind.THIS_MACHINE and server.kind is not ServerKind.THIS_MACHINE:
            await _check_can_hold_this_machine(session, user, access.workspace.id)
    try:
        apply_server_update(server, data)
        await check_links(session, server)
    except ValueError as exc:
        raise _unprocessable(exc) from None
    await session.commit()
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_operator_only)
async def delete_server(server_id: int, access: WorkspaceAccessDep, session: SessionDep) -> None:
    server = await get_server_or_404(session, access, server_id)
    if behind := await count_servers_behind(session, server_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Server is the jump host for {behind} server(s)")
    await session.delete(server)
    await session.commit()
