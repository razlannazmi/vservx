from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.db.deps import SessionDep
from api.models import Server
from api.schemas import ServerCreate, ServerRead, ServerUpdate
from api.service.servers import apply_server_update, server_from_create

router = APIRouter(prefix="/servers", tags=["servers"])

# Stored credentials give shell access to the server, so only admins can add or change them.
_admin_only = [Depends(require_admin)]


async def _get_or_404(session: AsyncSession, server_id: int) -> Server:
    server = await session.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return server


@router.get("", response_model=list[ServerRead])
async def list_servers(session: SessionDep) -> Sequence[Server]:
    return (await session.scalars(select(Server).order_by(Server.name))).all()


@router.post("", response_model=ServerRead, status_code=status.HTTP_201_CREATED, dependencies=_admin_only)
async def create_server(data: ServerCreate, session: SessionDep) -> Server:
    server = server_from_create(data)
    session.add(server)
    await session.commit()
    return server


@router.get("/{server_id}", response_model=ServerRead)
async def get_server(server_id: int, session: SessionDep) -> Server:
    return await _get_or_404(session, server_id)


@router.patch("/{server_id}", response_model=ServerRead, dependencies=_admin_only)
async def update_server(server_id: int, data: ServerUpdate, session: SessionDep) -> Server:
    server = await _get_or_404(session, server_id)
    try:
        apply_server_update(server, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    await session.commit()
    return server


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin_only)
async def delete_server(server_id: int, session: SessionDep) -> None:
    server = await _get_or_404(session, server_id)
    await session.delete(server)
    await session.commit()
