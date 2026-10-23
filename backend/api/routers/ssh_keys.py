from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.db.deps import SessionDep
from api.models import SavedKey
from api.schemas import SavedKeyCreate, SavedKeyRead, SavedKeyUpdate
from api.service.saved_keys import (
    apply_saved_key_update,
    count_servers_using,
    list_saved_keys,
    saved_key_from_create,
    saved_key_read,
)
from api.ssh.keys import InvalidKey

router = APIRouter(prefix="/ssh-keys", tags=["ssh-keys"])

# A saved key opens every server that uses it, so only admins can add or change one.
_admin_only = [Depends(require_admin)]


async def _get_or_404(session: AsyncSession, key_id: int) -> SavedKey:
    key = await session.get(SavedKey, key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved key not found")
    return key


def _unusable(exc: InvalidKey) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("", response_model=list[SavedKeyRead])
async def list_keys(session: SessionDep) -> list[SavedKeyRead]:
    return await list_saved_keys(session)


@router.post("", response_model=SavedKeyRead, status_code=status.HTTP_201_CREATED, dependencies=_admin_only)
async def create_key(data: SavedKeyCreate, session: SessionDep) -> SavedKeyRead:
    try:
        key = saved_key_from_create(data)
    except InvalidKey as exc:
        raise _unusable(exc) from None
    session.add(key)
    await session.commit()
    return await saved_key_read(session, key)


@router.get("/{key_id}", response_model=SavedKeyRead)
async def get_key(key_id: int, session: SessionDep) -> SavedKeyRead:
    return await saved_key_read(session, await _get_or_404(session, key_id))


@router.patch("/{key_id}", response_model=SavedKeyRead, dependencies=_admin_only)
async def update_key(key_id: int, data: SavedKeyUpdate, session: SessionDep) -> SavedKeyRead:
    key = await _get_or_404(session, key_id)
    try:
        apply_saved_key_update(key, data)
    except InvalidKey as exc:
        raise _unusable(exc) from None
    await session.commit()
    return await saved_key_read(session, key)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin_only)
async def delete_key(key_id: int, session: SessionDep) -> None:
    key = await _get_or_404(session, key_id)
    if in_use := await count_servers_using(session, key_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Saved key is used by {in_use} server(s)")
    await session.delete(key)
    await session.commit()
