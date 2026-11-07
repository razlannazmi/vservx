"""Writing snapshots: at each successful discovery, what each vLLM container is now is compared with
its instance's latest snapshot, and a snapshot is written only for a real change. Comparing against
the database means a vservx restart never duplicates one."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.enums import SnapshotKind
from api.models import Instance, Snapshot
from api.schemas.watch import RemovedInstanceRead
from api.snapshots.config import LaunchConfig, config_from_json, config_to_json
from api.snapshots.diff import Point, same_launch

# A removed container stays in the Instances table this long.
REMOVED_ROW_DAYS = 7
_CHANGES = (SnapshotKind.RECREATED, SnapshotKind.RECREATED_SAME, SnapshotKind.CHANGED)


@dataclass(frozen=True)
class Seen:
    """One vLLM container as a discovery found it."""

    name: str
    container_id: str
    created_at: datetime | None
    started_at: datetime | None
    restart_count: int
    image_id: str
    model: str | None
    config: LaunchConfig
    key_fingerprint: str | None
    key_id: str | None


@dataclass(frozen=True)
class Recorded:
    # Name -> happened_at of its newest snapshot, when that's a recreation or a change.
    changed_at: dict[str, datetime]
    # Removed in the last REMOVED_ROW_DAYS days, newest first.
    removed: list[RemovedInstanceRead]


def point(snapshot: Snapshot) -> Point:
    config = config_from_json(snapshot.config) if snapshot.config is not None else None
    return Point(snapshot.container_id, snapshot.image_id, config, snapshot.key_fingerprint, snapshot.key_id)


async def _newest(session: AsyncSession, server_id: int, live_only: bool) -> dict[int, Snapshot]:
    """Each instance's newest snapshot by ID, or newest non-removed one."""
    newest = select(func.max(Snapshot.id)).where(Snapshot.server_id == server_id)
    if live_only:
        newest = newest.where(Snapshot.kind != SnapshotKind.REMOVED)
    rows = await session.scalars(select(Snapshot).where(Snapshot.id.in_(newest.group_by(Snapshot.instance_id))))
    return {snapshot.instance_id: snapshot for snapshot in rows}


class SnapshotRecorder:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(self, server_id: int, seen: list[Seen], now: datetime) -> Recorded:
        async with self._sessionmaker() as session:
            instances = {instance.name: instance for instance in
                         await session.scalars(select(Instance).where(Instance.server_id == server_id))}
            latest = await _newest(session, server_id, live_only=True)
            for found in seen:
                instance = instances.get(found.name)
                if instance is None:
                    instance = Instance(server_id=server_id, name=found.name, container_id=found.container_id,
                                        model=found.model, first_seen=now, last_seen=now)
                    session.add(instance)
                    await session.flush()
                    instances[found.name] = instance
                instance.last_seen, instance.container_id, instance.model = now, found.container_id, found.model
                instance.removed_at = None
                self._compare(session, server_id, instance, latest.get(instance.id), found, now)
            names = {found.name for found in seen}
            for instance in instances.values():
                if instance.removed_at is None and instance.name not in names:
                    instance.removed_at = now
                    session.add(Snapshot(server_id=server_id, instance_id=instance.id, kind=SnapshotKind.REMOVED,
                                         happened_at=now, noticed_at=now, container_id=instance.container_id,
                                         model=instance.model, last_seen=instance.last_seen))
            await session.flush()
            recorded = await self._recorded(session, server_id, instances, now)
            await session.commit()
            return recorded

    def _compare(self, session: AsyncSession, server_id: int, instance: Instance, last: Snapshot | None,
                 found: Seen, now: datetime) -> None:
        new = Point(found.container_id, found.image_id, found.config, found.key_fingerprint, found.key_id)
        if last is None:
            kind, happened = SnapshotKind.FIRST_SEEN, found.created_at or now
        else:
            old = point(last)
            same = same_launch(old, new)
            if last.container_id == found.container_id:
                if same:
                    if old.key_id and new.key_id and old.key_id != new.key_id:
                        # The key file was replaced; the key itself can't have changed in a living container.
                        last.key_fingerprint, last.key_id = found.key_fingerprint, found.key_id
                    return
                kind, happened = SnapshotKind.CHANGED, now
            else:
                kind = SnapshotKind.RECREATED_SAME if same else SnapshotKind.RECREATED
                happened = found.created_at or now
        session.add(Snapshot(
            server_id=server_id, instance_id=instance.id, kind=kind, happened_at=happened, noticed_at=now,
            container_id=found.container_id, created_at=found.created_at, started_at=found.started_at,
            restart_count=found.restart_count, image_id=found.image_id or None, model=found.model,
            config=config_to_json(found.config),
            key_fingerprint=found.key_fingerprint, key_id=found.key_id,
        ))

    async def _recorded(self, session: AsyncSession, server_id: int, instances: dict[str, Instance],
                        now: datetime) -> Recorded:
        by_id = {instance.id: instance for instance in instances.values()}
        newest = await _newest(session, server_id, live_only=False)
        changed_at = {by_id[instance_id].name: snapshot.happened_at for instance_id, snapshot in newest.items()
                      if snapshot.kind in _CHANGES}
        live = await _newest(session, server_id, live_only=True)
        since = now - timedelta(days=REMOVED_ROW_DAYS)
        removed = sorted((instance for instance in instances.values()
                          if instance.removed_at is not None and instance.removed_at >= since),
                         key=lambda instance: instance.removed_at, reverse=True)
        return Recorded(changed_at, [
            RemovedInstanceRead(name=instance.name,
                                image=(live[instance.id].config or {}).get("image") if instance.id in live else None,
                                model=instance.model, last_seen=instance.last_seen, removed_at=instance.removed_at)
            for instance in removed])

    async def fill_version(self, server_id: int, name: str, container_id: str, version: str) -> None:
        """The vLLM version, read once the instance is ready, into the snapshots of that container."""
        async with self._sessionmaker() as session:
            instance_id = select(Instance.id).where(Instance.server_id == server_id, Instance.name == name)
            await session.execute(update(Snapshot).where(
                Snapshot.instance_id.in_(instance_id), Snapshot.container_id == container_id,
                Snapshot.kind != SnapshotKind.REMOVED, Snapshot.vllm_version.is_(None),
            ).values(vllm_version=version))
            await session.commit()
