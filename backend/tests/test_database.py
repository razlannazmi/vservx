import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import migrate
from api.db.base import Base
from api.enums import DatabaseState, LaunchType, SnapshotTrigger
from api.main import create_app
from api.models import Instance, Server, Snapshot, User
from tests.helpers import ADMIN, Db, login_headers


def _sql(db_path: Path, statement: str, *params: object) -> list[tuple]:
    with closing(sqlite3.connect(db_path)) as conn, conn:
        return conn.execute(statement, params).fetchall()


def _columns(db_path: Path, table: str) -> set[str]:
    return {row[1] for row in _sql(db_path, f"PRAGMA table_info({table})")}


def test_migrations_match_models(data_dir: Path) -> None:
    db_path = data_dir / "vservx.db"
    migrate.create_database(db_path)
    with migrate.migration_engine(db_path).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
    assert migrate.inspect_database(db_path).state is DatabaseState.CURRENT


def test_failed_upgrade_leaves_database_unchanged(
    data_dir: Path, extra_migration: Callable[[str], None]
) -> None:
    db_path = data_dir / "vservx.db"
    migrate.create_database(db_path)
    extra_migration(
        'with op.batch_alter_table("servers", recreate="always") as batch:\n'
        '    batch.add_column(sa.Column("note", sa.String(50)))\n'
        'raise RuntimeError("boom")'
    )
    with pytest.raises(migrate.UpgradeError, match="boom"):
        migrate.upgrade_database(db_path, by="Admin", user_id=None, source="cli")

    status = migrate.inspect_database(db_path)
    assert status.state is DatabaseState.UPGRADE_REQUIRED
    assert status.current_revision == "0001"
    assert status.last_upgrade is None
    # The table rebuild before the failure was rolled back too.
    assert "note" not in _columns(db_path, "servers")
    assert migrate.newest_backup(db_path) is not None


def test_unrecognised_databases_are_not_upgraded(data_dir: Path) -> None:
    db_path = data_dir / "vservx.db"
    migrate.create_database(db_path)
    _sql(db_path, "UPDATE alembic_version SET version_num = ?", "9999")
    assert migrate.inspect_database(db_path).state is DatabaseState.NEWER_THAN_APP
    with pytest.raises(migrate.UpgradeError, match="newer version"):
        migrate.upgrade_database(db_path, by="Admin", user_id=None, source="cli")

    # Made by create_all before migrations existed: no alembic_version table.
    old = data_dir / "old.db"
    engine = create_engine(f"sqlite:///{old.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with pytest.raises(migrate.PreMigrationDatabaseError):
        migrate.inspect_database(old)


def _server(name: str, **extra: object) -> dict:
    return {"name": name, "host": "10.0.0.1", "username": "ubuntu",
            "auth_type": "password", "password": "hunter2"} | extra


async def _add_instance_and_snapshot(session: AsyncSession) -> None:
    server_id = await session.scalar(select(Server.id).where(Server.name == "gpu-7"))
    instance = Instance(server_id=server_id, launch_type=LaunchType.DOCKER, ref="vllm-1")
    session.add(instance)
    await session.flush()
    session.add(Snapshot(instance_id=instance.id, server_id=server_id,
                         trigger=SnapshotTrigger.DISCOVERY, launch_type=LaunchType.DOCKER))


async def _admin_last_login(session: AsyncSession) -> datetime | None:
    return await session.scalar(select(User.last_login_at).where(User.email == ADMIN["email"]))


async def _count_instances_and_snapshots(session: AsyncSession) -> tuple[int, int]:
    instances = await session.scalar(select(func.count()).select_from(Instance))
    snapshots = await session.scalar(select(func.count()).select_from(Snapshot))
    return instances, snapshots


def test_upgrade_waits_then_keeps_data(
    api: TestClient, db: Db, data_dir: Path, extra_migration: Callable[[str], None]
) -> None:
    bastion = api.post("/api/servers", json=_server("bastion")).json()["id"]
    api.post("/api/servers", json=_server("gpu-7", jump_server_id=bastion))
    db(_add_instance_and_snapshot)
    # Rebuilding servers is the case that would cascade-delete instances and snapshots.
    extra_migration(
        'with op.batch_alter_table("servers", recreate="always") as batch:\n'
        '    batch.add_column(sa.Column("note", sa.String(50)))'
    )

    signed_in_at = db(_admin_last_login)

    with TestClient(create_app()) as fresh:
        headers = login_headers(fresh, ADMIN["email"], ADMIN["password"])
        # Signing in while an upgrade waits only reads the database.
        assert db(_admin_last_login) == signed_in_at
        assert fresh.get("/api/health").json()["database"] == "upgrade_required"
        blocked = fresh.get("/api/servers", headers=headers)
        assert blocked.status_code == 503
        assert blocked.json()["code"] == "database_upgrade_required"
        assert fresh.get("/api/database", headers=headers).json()["pending"] == ["Add a test column"]

        response = fresh.post("/api/database/upgrade", headers=headers)
        assert response.status_code == 200, response.text
        done = response.json()
        assert done["state"] == "current"
        assert done["last_upgrade"]["by"] == "Admin"
        assert done["last_upgrade"]["from_revision"] == "0001"
        assert done["last_upgrade"]["upgraded_at"]

        servers = fresh.get("/api/servers", headers=headers).json()
        assert {s["name"]: s["jump_server_id"] for s in servers} == {"bastion": None, "gpu-7": bastion}
        assert db(_count_instances_and_snapshots) == (1, 1)
        backup = migrate.newest_backup(data_dir / "vservx.db")
        assert done["latest_backup"]["name"] == backup.name
        assert _sql(backup, "SELECT count(*) FROM servers") == [(2,)]


def test_command_line_upgrade_unblocks_running_server(
    admin_headers: dict[str, str], data_dir: Path, extra_migration: Callable[[str], None]
) -> None:
    extra_migration('op.create_table("extra", sa.Column("id", sa.Integer, primary_key=True))')
    with TestClient(create_app()) as fresh:
        assert fresh.get("/api/servers", headers=admin_headers).status_code == 503
        migrate.upgrade_database(data_dir / "vservx.db", by="command line", user_id=None, source="cli")
        assert fresh.get("/api/servers", headers=admin_headers).status_code == 200
