from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import api.models  # noqa: F401  # registers all tables on Base.metadata
from api.db.base import Base


def create_engine(db_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn: Any, _: Any) -> None:
        cursor = dbapi_conn.cursor()
        # WAL lets the metrics poller write while API requests read.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Off by default in SQLite; required for ON DELETE CASCADE / SET NULL.
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    # Stand-in until Alembic migrations are added.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
