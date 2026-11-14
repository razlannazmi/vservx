"""Reading snapshots back: change lists, one snapshot with its rebuilt command, comparing two, and
checking a pasted key against a fingerprint. Differences are worked out on read."""

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import InstanceSource, SnapshotKind
from api.models import Instance, Snapshot
from api.schemas.snapshot import (
    CheckKeyRead,
    DifferenceRead,
    SnapshotCompareRead,
    SnapshotDetailRead,
    SnapshotEntryRead,
    SnapshotPageRead,
)
from api.snapshots.command import COVERS, ENV_HIDDEN_LINE, compose_line, docker_run
from api.snapshots.config import config_from_json
from api.snapshots.diff import differences
from api.snapshots.fingerprint import check_key
from api.snapshots.recorder import point

PAGE_SIZE = 50
CANT_CHECK = "This fingerprint was made before vservx's key file was replaced, so it can't be checked."


class NotFound(Exception):
    pass


def _cursor(snapshot: Snapshot) -> str:
    return f"{snapshot.happened_at.isoformat()}|{snapshot.id}"


def parse_cursor(text: str) -> tuple[datetime, int]:
    """The `before` cursor; ValueError when it's malformed."""
    at, sep, snapshot_id = text.rpartition("|")
    if not sep:
        raise ValueError("not a snapshot cursor")
    happened = datetime.fromisoformat(at)
    return happened if happened.tzinfo else happened.replace(tzinfo=UTC), int(snapshot_id)


async def _previous(session: AsyncSession, snapshot: Snapshot) -> Snapshot | None:
    """The instance's previous snapshot with a config, as written."""
    return await session.scalar(
        select(Snapshot).where(Snapshot.instance_id == snapshot.instance_id, Snapshot.id < snapshot.id,
                               Snapshot.kind != SnapshotKind.REMOVED).order_by(Snapshot.id.desc()).limit(1))


async def _differences(session: AsyncSession, snapshot: Snapshot) -> list[DifferenceRead]:
    if snapshot.kind in (SnapshotKind.FIRST_SEEN, SnapshotKind.REMOVED):
        return []
    previous = await _previous(session, snapshot)
    if previous is None:
        return []
    return [DifferenceRead(label=d.label, before=d.before, after=d.after, note=d.note)
            for d in differences(point(previous), point(snapshot))]


async def _entry(session: AsyncSession, snapshot: Snapshot, name: str, source: InstanceSource) -> SnapshotEntryRead:
    return SnapshotEntryRead(
        id=snapshot.id, instance=name, source=source, model=snapshot.model, kind=snapshot.kind, happened_at=snapshot.happened_at,
        noticed_at=snapshot.noticed_at, last_seen=snapshot.last_seen,
        container_id=snapshot.container_id[:12] if snapshot.container_id else None,
        differences=await _differences(session, snapshot))


async def list_snapshots(session: AsyncSession, server_id: int, name: str | None, source: InstanceSource | None,
                         limit: int, before: str | None) -> SnapshotPageRead:
    """A server's or one instance's (`name` and `source`) change list, newest first by when things happened."""
    query = select(Snapshot, Instance.name, Instance.source).join(Instance).where(Snapshot.server_id == server_id)
    if name is not None:
        query = query.where(Instance.name == name)
    if source is not None:
        query = query.where(Instance.source == source)
    if before is not None:
        at, snapshot_id = parse_cursor(before)
        query = query.where(or_(Snapshot.happened_at < at, and_(Snapshot.happened_at == at, Snapshot.id < snapshot_id)))
    rows = (await session.execute(
        query.order_by(Snapshot.happened_at.desc(), Snapshot.id.desc()).limit(limit + 1))).all()
    page = rows[:limit]
    return SnapshotPageRead(
        entries=[await _entry(session, snapshot, instance, instance_source) for snapshot, instance, instance_source in page],
        next_before=_cursor(page[-1][0]) if len(rows) > limit else None)


async def _get(session: AsyncSession, server_id: int, snapshot_id: int) -> tuple[Snapshot, str, InstanceSource]:
    row = (await session.execute(select(Snapshot, Instance.name, Instance.source).join(Instance).where(
        Snapshot.id == snapshot_id, Snapshot.server_id == server_id))).first()
    if row is None:
        raise NotFound
    return row[0], row[1], row[2]


async def _detail(session: AsyncSession, snapshot: Snapshot, name: str, source: InstanceSource) -> SnapshotDetailRead:
    entry = await _entry(session, snapshot, name, source)
    config = config_from_json(snapshot.config) if snapshot.config is not None else None
    return SnapshotDetailRead(
        **entry.model_dump(),
        image=config.image if config else None, image_id=snapshot.image_id, vllm_version=snapshot.vllm_version,
        created_at=snapshot.created_at, started_at=snapshot.started_at, restart_count=snapshot.restart_count,
        command=docker_run(name, config) if config else None, covers=COVERS,
        compose=compose_line(config) if config else None,
        env_hidden=ENV_HIDDEN_LINE if config and config.env_values_hidden else None,
        env_values_hidden=bool(config and config.env_values_hidden),
        key_fingerprint=snapshot.key_fingerprint)


async def get_snapshot(session: AsyncSession, server_id: int, snapshot_id: int) -> SnapshotDetailRead:
    snapshot, name, source = await _get(session, server_id, snapshot_id)
    return await _detail(session, snapshot, name, source)


async def compare_snapshots(session: AsyncSession, server_id: int, first: int, second: int) -> SnapshotCompareRead:
    """Any two of a server's snapshots, the older as "from". Removed entries have no config to compare."""
    pair = [await _get(session, server_id, snapshot_id) for snapshot_id in (first, second)]
    if any(snapshot.kind is SnapshotKind.REMOVED for snapshot, _, _ in pair):
        raise NotFound
    older, newer = sorted(pair, key=lambda row: (row[0].happened_at, row[0].id))
    return SnapshotCompareRead(
        from_snapshot=await _detail(session, *older), to_snapshot=await _detail(session, *newer),
        differences=[DifferenceRead(label=d.label, before=d.before, after=d.after, note=d.note)
                     for d in differences(point(older[0]), point(newer[0]))])


async def check_snapshot_key(session: AsyncSession, server_id: int, snapshot_id: int, key: str) -> CheckKeyRead:
    """Never logs or keeps the candidate key."""
    snapshot, _, _ = await _get(session, server_id, snapshot_id)
    if snapshot.key_fingerprint is None or snapshot.key_id is None:
        raise NotFound
    matches = check_key(key, snapshot.key_fingerprint, snapshot.key_id)
    return CheckKeyRead(matches=matches, reason=CANT_CHECK if matches is None else None)
