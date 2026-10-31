"""Keeps the app off the database until its schema matches this version of vservx."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from api.db import migrate
from api.enums import DatabaseState
from api.models import User


class DatabaseNotReady(Exception):
    def __init__(self, state: DatabaseState) -> None:
        super().__init__(state)
        self.state = state


class DatabaseGate:
    """The database's state, and the one place that moves it to current.

    Work that uses the database at startup (seeding the admin, later the SSH pool and pollers)
    goes in on_ready. It runs once the schema is current: at startup, or after the upgrade.
    """

    def __init__(self, db_path: Path, on_ready: Callable[[], Awaitable[None]]) -> None:
        self.db_path = db_path
        self.status: migrate.DatabaseStatus | None = None
        self._on_ready = on_ready
        # Held while the state can change, so on_ready runs once and upgrades never overlap.
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self.status is not None and self.status.state is DatabaseState.CURRENT

    async def start(self) -> None:
        async with self._lock:
            status = await self._inspect()
            if status.state is DatabaseState.NEW:
                await asyncio.to_thread(migrate.create_database, self.db_path)
                status = await self._inspect()
            await self._set(status)

    async def refresh(self) -> migrate.DatabaseStatus:
        """Re-read the state while not current, so an upgrade run from the command line
        takes effect without a restart."""
        if not self.ready:
            async with self._lock:
                if not self.ready:
                    await self._set(await self._inspect())
        assert self.status is not None
        return self.status

    async def upgrade(self, user: User) -> None:
        async with self._lock:
            await asyncio.to_thread(
                migrate.upgrade_database, self.db_path, by=user.name, user_id=user.id, source="ui"
            )
            await self._set(await self._inspect())

    async def _inspect(self) -> migrate.DatabaseStatus:
        return await asyncio.to_thread(migrate.inspect_database, self.db_path)

    async def _set(self, status: migrate.DatabaseStatus) -> None:
        was_ready = self.ready
        self.status = status
        if self.ready and not was_ready:
            await self._on_ready()


def get_database_gate(request: Request) -> DatabaseGate:
    return request.app.state.database


DatabaseGateDep = Annotated[DatabaseGate, Depends(get_database_gate)]


async def require_current_database(gate: DatabaseGateDep) -> None:
    status = await gate.refresh()
    if status.state is not DatabaseState.CURRENT:
        raise DatabaseNotReady(status.state)
