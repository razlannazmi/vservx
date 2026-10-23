from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import SavedKey, Server
from api.schemas import SavedKeyCreate, SavedKeyRead, SavedKeyUpdate
from api.ssh.keys import InvalidKey, inspect_private_key


def _reveal(value: SecretStr | None) -> str | None:
    return None if value is None else value.get_secret_value()


def _set_key(key: SavedKey, private_key: str, passphrase: str | None) -> None:
    """Check the key, then store it with what's derived from it. Raises InvalidKey before
    changing anything."""
    info = inspect_private_key(private_key, passphrase)
    key.private_key = private_key
    # A passphrase sent with a key that isn't encrypted is ignored, not stored.
    key.passphrase = passphrase if info.encrypted else None
    key.key_type = info.key_type
    key.fingerprint = info.fingerprint
    key.public_key = info.public_key


def saved_key_from_create(data: SavedKeyCreate) -> SavedKey:
    key = SavedKey(name=data.name)
    _set_key(key, data.private_key.get_secret_value(), _reveal(data.passphrase))
    return key


def apply_saved_key_update(key: SavedKey, update: SavedKeyUpdate) -> None:
    """Apply a partial update. Raises InvalidKey, leaving the key unchanged, if the new key
    or passphrase doesn't check out."""
    fields = update.model_fields_set
    if "private_key" in fields or "passphrase" in fields:
        private_key = _reveal(update.private_key) if "private_key" in fields else key.private_key
        if private_key is None:
            raise InvalidKey("The stored key can't be read; upload it again")
        _set_key(key, private_key, _reveal(update.passphrase))
    if "name" in fields and update.name is not None:
        key.name = update.name


async def count_servers_using(session: AsyncSession, key_id: int) -> int:
    return await session.scalar(
        select(func.count()).select_from(Server).where(Server.ssh_key_id == key_id)
    ) or 0


def _read(key: SavedKey, server_count: int) -> SavedKeyRead:
    fields = {name: getattr(key, name) for name in SavedKeyRead.model_fields if name != "server_count"}
    return SavedKeyRead(**fields, server_count=server_count)


async def saved_key_read(session: AsyncSession, key: SavedKey) -> SavedKeyRead:
    return _read(key, await count_servers_using(session, key.id))


async def list_saved_keys(session: AsyncSession) -> list[SavedKeyRead]:
    keys = (await session.scalars(select(SavedKey).order_by(SavedKey.name))).all()
    rows = await session.execute(
        select(Server.ssh_key_id, func.count()).where(Server.ssh_key_id.is_not(None)).group_by(Server.ssh_key_id)
    )
    counts = {key_id: count for key_id, count in rows}
    return [_read(key, counts.get(key.id, 0)) for key in keys]
