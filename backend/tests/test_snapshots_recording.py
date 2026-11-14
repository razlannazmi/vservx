"""Recording launch snapshots on discovery: only on a real change, removals, and a database error
that mustn't stop watching."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db.crypto import init_crypto
from api.db.engine import create_engine, create_sessionmaker
from api.enums import InstanceSource
from api.models import Instance, Snapshot
from api.snapshots.config import LaunchConfig
from api.snapshots.recorder import Recorded, Seen, SnapshotRecorder
from tests.helpers import SERVER_BODY, Db, FakeVLLM, Sshd, docker_host
from tests.test_watch import _until, _watch

T0 = datetime(2026, 11, 7, 12, tzinfo=UTC)


class StubRecorder:
    def __init__(self, fail_first: bool) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail_first

    async def record(self, server_id: int, seen: list[Seen], now: datetime,
                     read: frozenset[InstanceSource]) -> Recorded:
        self.calls.append([s.name for s in seen])
        if self._fail:
            self._fail = False
            raise OSError("database is locked")
        return Recorded({}, [])

    async def fill_version(self, *args: object) -> None:
        pass


def _seen(container_id: str = "c1", length: str = "8192", created: datetime = T0, name: str = "vllm-qwen",
          source: InstanceSource = InstanceSource.DOCKER) -> Seen:
    config = LaunchConfig("vllm/vllm-openai:v0.7.1", args=("m", "--max-model-len", length))
    return Seen(name, container_id, created, created, 0, "sha256:a", "m", config, None, None, source)


def _record(data_dir: Path, server_id: int, seen: list[Seen], now: datetime,
            read: frozenset[InstanceSource] = frozenset({InstanceSource.DOCKER})) -> Recorded:
    """A fresh engine and recorder each call, as after a vservx restart."""
    async def main() -> Recorded:
        engine = create_engine(data_dir / "vservx.db")
        try:
            return await SnapshotRecorder(create_sessionmaker(engine)).record(server_id, seen, now, read)
        finally:
            await engine.dispose()
    return asyncio.run(main())


def _kinds(db: Db) -> list[tuple[str, datetime]]:
    async def read(session):
        rows = await session.scalars(select(Snapshot).order_by(Snapshot.id))
        return [(s.kind.value, s.happened_at.replace(tzinfo=UTC)) for s in rows]
    return db(read)


def test_snapshots_only_on_real_change(api: TestClient, w: str, db: Db, data_dir: Path) -> None:
    server_id = api.post(f"{w}/servers", json=SERVER_BODY).json()["id"]
    _record(data_dir, server_id, [_seen()], T0)
    _record(data_dir, server_id, [_seen()], T0 + timedelta(minutes=1))           # same: nothing
    _record(data_dir, server_id, [_seen("c2", created=T0 + timedelta(hours=1))], T0 + timedelta(hours=1))
    # Recreated while vservx was down: dated by Docker's Created time, not when it was noticed.
    late = T0 - timedelta(days=2)
    result = _record(data_dir, server_id, [_seen("c3", "16384", created=late)], T0 + timedelta(hours=3))
    assert [k for k, _ in _kinds(db)] == ["first_seen", "recreated_same", "recreated"]
    assert _kinds(db)[-1][1] == late and result.changed_at == {"vllm-qwen": late}


def test_removed_then_back(api: TestClient, w: str, db: Db, data_dir: Path) -> None:
    server_id = api.post(f"{w}/servers", json=SERVER_BODY).json()["id"]
    _record(data_dir, server_id, [_seen()], T0)
    gone = _record(data_dir, server_id, [], T0 + timedelta(hours=1))
    assert [r.name for r in gone.removed] == ["vllm-qwen"]
    back = _record(data_dir, server_id, [_seen("c2")], T0 + timedelta(hours=2))
    assert back.removed == [] and [k for k, _ in _kinds(db)] == ["first_seen", "removed", "recreated_same"]


def test_watch_records_once_per_change_and_retries(sshd: Sshd, fake_vllm: FakeVLLM, tmp_path: Path) -> None:
    init_crypto(tmp_path / "secret.key")  # the container has an API key to fingerprint
    answer = docker_host(fake_vllm, sudo_password="ssh-pw")
    host = sshd(password="ssh-pw", commands=answer)
    stub = StubRecorder(fail_first=True)
    watch = _watch(host, recorder=stub)

    async def scenario() -> None:
        task = asyncio.create_task(watch.run())
        await _until(lambda: len(stub.calls) >= 2)  # the failed write is tried again at the next discovery
        await asyncio.sleep(1.0)                    # about three more discoveries, nothing changed
        answer.ps = None                            # docker ps now fails: no removal may be recorded
        await asyncio.sleep(1.0)
        task.cancel()
    asyncio.run(scenario())
    assert stub.calls == [["vllm-llama"], ["vllm-llama"]] and watch.view().instances


def test_watch_waits_for_image_settings(sshd: Sshd, fake_vllm: FakeVLLM, tmp_path: Path) -> None:
    """A failed image inspect isn't taken as "the image has no settings of its own": that would put
    inherited env and entrypoint into the config, and a spurious change once the image reads fine."""
    init_crypto(tmp_path / "secret.key")
    answer = docker_host(fake_vllm, sudo_password="ssh-pw")
    answer.image_failures = 1
    host = sshd(password="ssh-pw", commands=answer)
    inspects_at_write: list[int] = []

    class Stub(StubRecorder):
        async def record(self, server_id: int, seen: list[Seen], now: datetime,
                         read: frozenset[InstanceSource]) -> Recorded:
            inspects_at_write.append(answer.image_inspects)
            return await super().record(server_id, seen, now, read)

    stub = Stub(fail_first=False)
    watch = _watch(host, recorder=stub)

    async def scenario() -> None:
        task = asyncio.create_task(watch.run())
        await _until(lambda: bool(stub.calls))
        task.cancel()
    asyncio.run(scenario())
    assert inspects_at_write[0] == 2


def test_same_name_different_sources_are_separate_instances(api: TestClient, w: str, db: Db, data_dir: Path) -> None:
    server_id = api.post(f"{w}/servers", json=SERVER_BODY).json()["id"]
    both = frozenset({InstanceSource.DOCKER, InstanceSource.SYSTEMD})
    result = _record(data_dir, server_id, [_seen(name="vllm.service"),
                                           _seen("", name="vllm.service", source=InstanceSource.SYSTEMD)], T0, both)

    async def read(session):
        return sorted((i.source.value, i.name) for i in await session.scalars(select(Instance)))
    assert db(read) == [("docker", "vllm.service"), ("systemd", "vllm.service")]
    assert result.changed_at == {}


def test_unread_source_is_not_marked_removed(api: TestClient, w: str, db: Db, data_dir: Path) -> None:
    server_id = api.post(f"{w}/servers", json=SERVER_BODY).json()["id"]
    both = frozenset({InstanceSource.DOCKER, InstanceSource.SYSTEMD})
    _record(data_dir, server_id, [_seen("", name="vllm.service", source=InstanceSource.SYSTEMD)], T0, both)
    result = _record(data_dir, server_id, [], T0 + timedelta(hours=1))  # only Docker was read

    async def removed(session):
        return [i.removed_at for i in await session.scalars(select(Instance))]
    assert db(removed) == [None] and result.removed == []
    assert [k for k, _ in _kinds(db)] == ["first_seen"]
