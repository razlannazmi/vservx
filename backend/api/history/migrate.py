"""History store migrations: which state the store's schema is in, and bringing it up to date.

- They run on the store's async engine through conn.run_sync, all in one transaction.
- An advisory lock lets only one vservx process migrate the store at a time.
- Alembic's version table lives in the store database, apart from SQLite's chain.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from sqlalchemy import Connection, make_url, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from api.enums import DatabaseState
from api.history.types import StoreSchema

SCRIPT_LOCATION = str(Path(__file__).parent / "migrations")
# Any fixed bigint works; this one spells "vservx" followed by 1.
STORE_LOCK_ID = 0x7673657276780001


def store_engine(url: str) -> AsyncEngine:
    """An engine for a postgresql:// or postgres:// URL, through asyncpg."""
    return create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"), pool_size=5, pool_pre_ping=True)


async def inspect_store(engine: AsyncEngine) -> StoreSchema:
    script = _script()
    head = script.get_current_head()
    assert head is not None
    async with engine.connect() as conn:
        current = await conn.run_sync(_current_revision)

    if current is None:
        return StoreSchema(DatabaseState.NEW, None, head, _descriptions(script, head, "base"))
    if current == head:
        return StoreSchema(DatabaseState.CURRENT, current, head, [])
    try:
        pending = _descriptions(script, head, current)
    except RevisionError:
        # A revision this code has never heard of: written by a newer vservx.
        return StoreSchema(DatabaseState.NEWER_THAN_APP, current, head, [])
    return StoreSchema(DatabaseState.UPGRADE_REQUIRED, current, head, pending)


async def create_store(engine: AsyncEngine) -> None:
    """Build the newest schema in a store that has none yet."""
    async with engine.begin() as conn:
        await _lock(conn)
        # Another process may have created it while this one waited for the lock.
        if await conn.run_sync(_current_revision) is None:
            await conn.run_sync(_upgrade)


async def upgrade_store(engine: AsyncEngine) -> bool:
    """Apply every pending store migration in one transaction. False when there was nothing to do."""
    head = _script().get_current_head()
    async with engine.begin() as conn:
        await _lock(conn)
        # Another process may have upgraded it while this one waited for the lock.
        if await conn.run_sync(_current_revision) == head:
            return False
        await conn.run_sync(_upgrade)
    return True


def _config() -> Config:
    config = Config()
    # Escaped because Config values go through configparser interpolation.
    config.set_main_option("script_location", SCRIPT_LOCATION.replace("%", "%%"))
    return config


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(_config())


def _descriptions(script: ScriptDirectory, head: str, current: str) -> list[str]:
    revisions = [rev for rev in script.iterate_revisions(head, current) if rev.revision != current]
    return [rev.doc for rev in reversed(revisions)]


def _current_revision(conn: Connection) -> str | None:
    return MigrationContext.configure(conn).get_current_revision()


async def _lock(conn: AsyncConnection) -> None:
    # Held until the transaction ends.
    await conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": STORE_LOCK_ID})


def _upgrade(conn: Connection) -> None:
    config = _config()
    config.attributes["connection"] = conn
    command.upgrade(config, "head")
