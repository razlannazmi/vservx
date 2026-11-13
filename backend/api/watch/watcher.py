"""One ServerWatch per server, kept in step with the database, and answers from what they've seen."""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.config import Settings
from api.enums import AuthType, DockerStatus, ServerKind, UserRole, WatchState, WorkspaceRole
from api.models import SavedKey, Server, User, WorkspaceMember
from api.schemas.watch import InstanceHistoryRead, ServerWatchRead, WatchSummaryRead
from api.service.connections import build_hops
from api.service.servers import MAX_JUMP_HOSTS
from api.snapshots.recorder import SnapshotRecorder
from api.watch import local
from api.watch.server import ServerWatch, WatchConfig, usage_read
from api.watch.usage import UsageHistory

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    # NOT_TESTED or JUMP_ONLY when there's no watch; otherwise the watch says.
    state: WatchState
    signature: str | None = None
    watch: ServerWatch | None = None
    task: asyncio.Task[None] | None = None


def _chain(server: Server, servers: dict[int, Server]) -> list[Server] | None:
    """The server and the jump hosts in front of it, or None if the links are broken."""
    chain = [server]
    jump_id = server.jump_server_id
    while jump_id is not None:
        jump = servers.get(jump_id)
        if jump is None or jump in chain or len(chain) > MAX_JUMP_HOSTS:
            return None
        chain.append(jump)
        jump_id = jump.jump_server_id
    return chain


def _log_unexpected_end(server_id: int, task: asyncio.Task[None]) -> None:
    """A watch that dies on an error nobody expected would otherwise freeze its server's page silently."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.error("Watching server %s stopped on an unexpected error", server_id, exc_info=exc)


def _signature(server: Server, chain: list[Server], keys: dict[int, SavedKey]) -> str:
    """Changes when anything about reaching the server changes. Hashed, so no secret is kept around."""
    if server.kind is ServerKind.THIS_MACHINE:
        return hashlib.sha256(json.dumps(["this_machine", server.sudo_password]).encode()).hexdigest()
    parts: list[object] = [server.sudo_password]
    for hop in chain:
        key = keys.get(hop.ssh_key_id) if hop.ssh_key_id is not None else None
        parts.append([hop.id, hop.host, hop.port, hop.username, hop.auth_type, hop.password, hop.ssh_key_id,
                      hop.jump_server_id, hop.host_key, key.private_key if key else None, key.passphrase if key else None])
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


class Watcher:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        # One for every server's watch: each write is its own session.
        self._recorder = SnapshotRecorder(sessionmaker)
        self._limiter = asyncio.Semaphore(settings.watch_concurrency)
        self._entries: dict[int, _Entry] = {}
        # Server id -> container name -> history. Kept when a server's watch is replaced.
        self._histories: dict[int, dict[str, UsageHistory]] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._settings.watch_enabled or self._task is not None:
            return
        await self._sync()
        self._task = asyncio.create_task(self._keep_in_step(), name="watcher")

    async def stop(self) -> None:
        tasks = [task for task in [self._task, *(entry.task for entry in self._entries.values())] if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._entries.clear()

    def reload(self) -> None:
        """Bring the watches in step with the database as soon as possible."""
        self._wake.set()

    async def _keep_in_step(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self._settings.discovery_interval_seconds)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                await self._sync()
            except Exception:
                # Watching goes on with what it had; the next sync tries again.
                logger.exception("Couldn't bring server watching in step with the database")

    async def _sync(self) -> None:
        async with self._sessionmaker() as session:
            servers = {server.id: server for server in await session.scalars(select(Server))}
            keys = {key.id: key for key in await session.scalars(select(SavedKey))}
            # This machine is watched only while its workspace's owner is an admin who can sign in.
            admin_owned = set(await session.scalars(
                select(WorkspaceMember.workspace_id)
                .join(User, User.id == WorkspaceMember.user_id)
                .where(WorkspaceMember.role == WorkspaceRole.OWNER, User.role == UserRole.ADMIN,
                       User.is_active, User.approved_at.is_not(None))
            ))
            for server in servers.values():
                await self._sync_server(session, server, servers, keys, admin_owned)
        for server_id in [server_id for server_id in self._entries if server_id not in servers]:
            self._cancel(server_id)
            self._histories.pop(server_id, None)
            del self._entries[server_id]

    async def _sync_server(self, session: AsyncSession, server: Server, servers: dict[int, Server],
                           keys: dict[int, SavedKey], admin_owned: set[int]) -> None:
        this_machine = server.kind is ServerKind.THIS_MACHINE
        if this_machine and server.workspace_id not in admin_owned:
            self._set_idle(server.id, WatchState.NEEDS_ADMIN_OWNER)
            return
        if this_machine and local.unavailable_reason():
            self._set_idle(server.id, WatchState.NOT_TESTED)
            return
        if server.jump_only:
            self._set_idle(server.id, WatchState.JUMP_ONLY)
            return
        chain = _chain(server, servers)
        # Never trust a host key in the background: a server is watched once a test has recorded them.
        # This machine has none to record, and no jump hosts.
        if not this_machine and (chain is None or any(hop.host_key is None for hop in chain)):
            self._set_idle(server.id, WatchState.NOT_TESTED)
            return
        signature = _signature(server, chain or [server], keys)
        entry = self._entries.get(server.id)
        if entry is not None and entry.watch is not None and entry.signature == signature:
            # A watch that stopped on a rejected sign-in resumes once a connection test passes again.
            stopped = entry.watch.stopped_at
            retested = (stopped is not None and entry.watch.view().state is WatchState.SIGN_IN_FAILED
                        and server.last_test_ok and server.last_test_at is not None and server.last_test_at > stopped)
            if not retested:
                return
        if this_machine:
            config = WatchConfig(server.id, [], server.sudo_password, ServerKind.THIS_MACHINE)
        else:
            try:
                hops = [hop for _, hop in await build_hops(session, server)]
            except ValueError:
                self._set_idle(server.id, WatchState.NOT_TESTED)
                return
            sudo_password = server.sudo_password or (server.password if server.auth_type is AuthType.PASSWORD else None)
            config = WatchConfig(server.id, hops, sudo_password)
        # A replaced watch's history carries on into the new one.
        self._cancel(server.id)
        watch = ServerWatch(config, self._settings, self._limiter,
                            self._histories.setdefault(server.id, {}), self._recorder)
        task = asyncio.create_task(watch.run(), name=f"watch-server-{server.id}")
        server_id = server.id
        task.add_done_callback(lambda done: _log_unexpected_end(server_id, done))
        self._entries[server.id] = _Entry(WatchState.CHECKING, signature, watch, task)

    def _set_idle(self, server_id: int, state: WatchState) -> None:
        entry = self._entries.get(server_id)
        if entry is not None and entry.watch is None and entry.state is state:
            return
        self._cancel(server_id)
        # Not watched any more, so nothing it found is current.
        self._histories.pop(server_id, None)
        self._entries[server_id] = _Entry(state)

    def _cancel(self, server_id: int) -> None:
        entry = self._entries.get(server_id)
        if entry is not None and entry.task is not None:
            entry.task.cancel()

    # Reading back

    def summary(self, server_id: int) -> WatchSummaryRead:
        entry = self._entries.get(server_id)
        if entry is not None and entry.watch is not None:
            return entry.watch.summary()
        state = entry.state if entry is not None else WatchState.CHECKING
        return WatchSummaryRead(server_id=server_id, state=state, since=None, docker=DockerStatus.UNKNOWN, counts={})

    def view(self, server_id: int) -> ServerWatchRead:
        entry = self._entries.get(server_id)
        if entry is not None and entry.watch is not None:
            return entry.watch.view()
        return ServerWatchRead(
            server_id=server_id, state=entry.state if entry is not None else WatchState.CHECKING, since=None,
            message=None, docker=DockerStatus.UNKNOWN, docker_message=None, found_at=None, read_at=None,
            instances=[], gpus=None, gpu_message=None, usage_interval_seconds=self._settings.usage_interval_seconds,
        )

    def history(self, server_id: int, name: str) -> InstanceHistoryRead | None:
        """None for an instance the server doesn't have; an instance not yet read, or removed in
        the last 7 days, has no points."""
        view = self.view(server_id)
        if name in {row.name for row in view.removed}:
            return InstanceHistoryRead(name=name, interval_seconds=self._settings.usage_interval_seconds, points=[])
        if name not in {instance.name for instance in view.instances}:
            return None
        history = self._histories.get(server_id, {}).get(name)
        points = [usage_read(point) for point in history.points] if history else []
        return InstanceHistoryRead(name=name, interval_seconds=self._settings.usage_interval_seconds, points=points)

    async def refresh(self, server_id: int) -> ServerWatchRead:
        entry = self._entries.get(server_id)
        if entry is not None and entry.watch is not None:
            await entry.watch.refresh()
        return self.view(server_id)
