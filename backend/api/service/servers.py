from typing import Any

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import ServerKind, UserRole, WorkspaceRole
from api.models import SavedKey, Server, User, WorkspaceMember
from api.schemas import ServerCreate, ServerUpdate
from api.schemas.server import check_kind_fields

_KIND_FIELDS = ("host", "username", "auth_type", "password", "ssh_key_id", "jump_server_id", "jump_only")

# Most jump hosts allowed in front of any one server.
MAX_JUMP_HOSTS = 8


def _reveal(fields: dict[str, Any]) -> dict[str, Any]:
    """Unwrap SecretStr values so the model stores the secret, not its masked form."""
    return {name: value.get_secret_value() if isinstance(value, SecretStr) else value
            for name, value in fields.items()}


def server_from_create(data: ServerCreate, workspace_id: int) -> Server:
    return Server(**_reveal(data.model_dump()), workspace_id=workspace_id)


async def owner_is_admin(session: AsyncSession, workspace_id: int) -> bool:
    """True when the workspace's owner is an admin who is active and approved."""
    owner = await session.scalar(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == WorkspaceRole.OWNER)
    )
    return owner is not None and owner.role is UserRole.ADMIN and owner.is_active and not owner.is_pending


async def has_this_machine(session: AsyncSession, workspace_id: int) -> bool:
    return await session.scalar(
        select(Server.id).where(Server.workspace_id == workspace_id, Server.kind == ServerKind.THIS_MACHINE).limit(1)
    ) is not None


async def can_see_this_machine(session: AsyncSession, server: Server, user: User) -> bool:
    """Whether the user may see the server's instances, GPUs and snapshots. Always true for an SSH server.
    This machine is for app admins, and for everyone else only while its workspace's owner is an admin."""
    if server.kind is not ServerKind.THIS_MACHINE or user.role is UserRole.ADMIN:
        return True
    return await owner_is_admin(session, server.workspace_id)


def apply_server_update(server: Server, update: ServerUpdate) -> None:
    """Apply a partial update. Raises ValueError, leaving the server unchanged, if the
    merged settings don't fit the server's kind."""
    fields = _reveal(update.model_dump(exclude_unset=True))
    kind = fields.get("kind", server.kind)
    # Switching kind starts the connection settings from scratch.
    if kind is not server.kind:
        base = {name: False if name == "jump_only" else None for name in _KIND_FIELDS}
    else:
        base = {name: getattr(server, name) for name in _KIND_FIELDS}
    merged = {name: fields.get(name, base[name]) for name in _KIND_FIELDS}
    check_kind_fields(kind, **merged)
    if kind is not server.kind:
        for name, value in base.items():
            setattr(server, name, value)
        # This machine has no host key to trust.
        server.host_key = None
        server.host_key_recorded_at = None
    address = (server.host, server.port)
    for name, value in fields.items():
        setattr(server, name, value)
    # A new address is a new identity to learn.
    if (server.host, server.port) != address:
        server.host_key = None
        server.host_key_recorded_at = None


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
        # Another workspace's server is as good as missing.
        if jump is None or jump.workspace_id != server.workspace_id:
            raise ValueError(f"Jump server {jump_id} does not exist")
        if jump.kind is ServerKind.THIS_MACHINE:
            raise ValueError("This machine can't be a jump host")
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
        # Servers that jump through this one would build a hop with no host.
        if server.kind is ServerKind.THIS_MACHINE and server.id is not None and await count_servers_behind(session, server.id):
            raise ValueError("This machine can't be a jump host")
        if server.ssh_key_id is not None:
            key = await session.get(SavedKey, server.ssh_key_id)
            # Another workspace's key is as good as missing.
            if key is None or key.workspace_id != server.workspace_id:
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
