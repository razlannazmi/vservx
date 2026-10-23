from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.config import get_settings
from api.db.deps import SessionDep
from api.models import Server
from api.schemas import ServerCreate, ServerRead, ServerUpdate
from api.schemas.connection import ConnectionTestResult, HostKeyAccept
from api.schemas.ssh_config import ImportedHostRead, SSHConfigImport, SSHConfigPreview
from api.service.connections import (
    ChainUnreachable,
    HostKeyMismatch,
    accept_host_key,
    check_server_connection,
)
from api.service.servers import (
    apply_server_update,
    check_links,
    count_servers_behind,
    server_from_create,
)
from api.ssh.config_import import parse_ssh_config

router = APIRouter(prefix="/servers", tags=["servers"])

# Stored credentials give shell access to the server, so only admins can add or change them.
_admin_only = [Depends(require_admin)]


async def _get_or_404(session: AsyncSession, server_id: int) -> Server:
    server = await session.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return server


def _unprocessable(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("", response_model=list[ServerRead])
async def list_servers(session: SessionDep) -> Sequence[Server]:
    return (await session.scalars(select(Server).order_by(Server.name))).all()


@router.post("", response_model=ServerRead, status_code=status.HTTP_201_CREATED, dependencies=_admin_only)
async def create_server(data: ServerCreate, session: SessionDep) -> Server:
    server = server_from_create(data)
    try:
        await check_links(session, server)
    except ValueError as exc:
        raise _unprocessable(exc) from None
    session.add(server)
    await session.commit()
    return server


@router.post("/test", response_model=ConnectionTestResult, dependencies=_admin_only)
async def test_unsaved_server(data: ServerCreate, session: SessionDep) -> ConnectionTestResult:
    """Test settings before saving them. Nothing is stored for this server; saved jump hosts
    in its chain have their host keys recorded as usual."""
    server = server_from_create(data)
    try:
        await check_links(session, server)
        return await check_server_connection(session, server, get_settings().ssh_connect_timeout)
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.post("/import-ssh-config", response_model=SSHConfigPreview, dependencies=_admin_only)
def preview_ssh_config_import(data: SSHConfigImport) -> SSHConfigPreview:
    """Read an uploaded SSH config into proposed servers. Saves nothing."""
    hosts, warnings = parse_ssh_config(data.config)
    return SSHConfigPreview(hosts=[ImportedHostRead.model_validate(host) for host in hosts], warnings=warnings)


@router.post("/{server_id}/test", response_model=ConnectionTestResult)
async def test_saved_server(server_id: int, session: SessionDep) -> ConnectionTestResult:
    server = await _get_or_404(session, server_id)
    try:
        return await check_server_connection(session, server, get_settings().ssh_connect_timeout)
    except ValueError as exc:
        raise _unprocessable(exc) from None


@router.post("/{server_id}/host-key/accept", response_model=ServerRead, dependencies=_admin_only)
async def accept_server_host_key(server_id: int, data: HostKeyAccept, session: SessionDep) -> Server:
    server = await _get_or_404(session, server_id)
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
async def get_server(server_id: int, session: SessionDep) -> Server:
    return await _get_or_404(session, server_id)


@router.patch("/{server_id}", response_model=ServerRead, dependencies=_admin_only)
async def update_server(server_id: int, data: ServerUpdate, session: SessionDep) -> Server:
    server = await _get_or_404(session, server_id)
    try:
        apply_server_update(server, data)
        await check_links(session, server)
    except ValueError as exc:
        raise _unprocessable(exc) from None
    await session.commit()
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin_only)
async def delete_server(server_id: int, session: SessionDep) -> None:
    server = await _get_or_404(session, server_id)
    if behind := await count_servers_behind(session, server_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Server is the jump host for {behind} server(s)")
    await session.delete(server)
    await session.commit()
