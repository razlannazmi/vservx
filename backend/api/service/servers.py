from typing import Any

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import SavedKey, Server
from api.schemas import ServerCreate, ServerUpdate
from api.schemas.server import check_auth_fields

_AUTH_FIELDS = ("auth_type", "password", "ssh_key_id")

# Most jump hosts allowed in front of any one server.
MAX_JUMP_HOSTS = 8


def _reveal(fields: dict[str, Any]) -> dict[str, Any]:
    """Unwrap SecretStr values so the model stores the secret, not its masked form."""
    return {name: value.get_secret_value() if isinstance(value, SecretStr) else value
            for name, value in fields.items()}


def server_from_create(data: ServerCreate) -> Server:
    return Server(**_reveal(data.model_dump()))


def apply_server_update(server: Server, update: ServerUpdate) -> None:
    """Apply a partial update. Raises ValueError, leaving the server unchanged, if the
    merged credentials don't match auth_type."""
    fields = _reveal(update.model_dump(exclude_unset=True))
    merged = {name: fields.get(name, getattr(server, name)) for name in _AUTH_FIELDS}
    check_auth_fields(**merged)
    address = (server.host, server.port)
    for name, value in fields.items():
        setattr(server, name, value)
    # A new address is a new identity to learn.
    if (server.host, server.port) != address:
        server.host_key = None


async def _jump_hosts_in_front(session: AsyncSession, server: Server) -> int:
    """Walk the jump links in front of the server and count them."""
    count = 0
    jump_id = server.jump_server_id
    while jump_id is not None:
        if jump_id == server.id:
            raise ValueError("A server can't be its own jump host, directly or through others")
        count += 1
        if count > MAX_JUMP_HOSTS:
            raise ValueError(f"A server can have at most {MAX_JUMP_HOSTS} jump hosts in front of it")
        jump = await session.get(Server, jump_id)
        if jump is None:
            raise ValueError(f"Jump server {jump_id} does not exist")
        jump_id = jump.jump_server_id
    return count


async def _levels_behind(session: AsyncSession, server_id: int) -> int:
    """How many levels of servers jump through this one, directly or through others."""
    levels, frontier = 0, [server_id]
    while levels <= MAX_JUMP_HOSTS:
        frontier = list(await session.scalars(select(Server.id).where(Server.jump_server_id.in_(frontier))))
        if not frontier:
            break
        levels += 1
    return levels


async def check_links(session: AsyncSession, server: Server) -> None:
    """Raise ValueError if the server's saved key or jump chain is invalid. Works for an
    unsaved server too.

    Runs without autoflush so a pending bad id is reported here instead of failing the
    flush as a foreign-key error.
    """
    with session.no_autoflush:
        if server.ssh_key_id is not None and await session.get(SavedKey, server.ssh_key_id) is None:
            raise ValueError(f"Saved key {server.ssh_key_id} does not exist")
        in_front = await _jump_hosts_in_front(session, server)
        # Servers behind this one inherit its chain, so they must stay within the limit too.
        if server.id is not None and in_front + await _levels_behind(session, server.id) > MAX_JUMP_HOSTS:
            raise ValueError(
                f"This would put more than {MAX_JUMP_HOSTS} jump hosts in front of a server behind this one"
            )


async def count_servers_behind(session: AsyncSession, server_id: int) -> int:
    """How many servers use this one as their jump host."""
    return await session.scalar(
        select(func.count()).select_from(Server).where(Server.jump_server_id == server_id)
    ) or 0
