import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import migrate
from api.db.base import Base
from api.enums import DatabaseState
from api.main import create_app
from api.models import User
from tests.helpers import ADMIN, USER_PASSWORD, Db, login_headers

# The newest real migration, read before any test stacks a throwaway one on top.
HEAD = ScriptDirectory(migrate.SCRIPT_LOCATION).get_current_head()


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
    # A new database gets no workspace, and sign-up starts open.
    assert _sql(db_path, "SELECT count(*) FROM workspaces") == [(0,)]
    assert _sql(db_path, "SELECT id, signup_open FROM app_settings") == [(1, 1)]


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
    assert status.current_revision == HEAD
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


async def _admin_last_login(session: AsyncSession) -> datetime | None:
    return await session.scalar(select(User.last_login_at).where(User.email == ADMIN["email"]))


def test_upgrade_waits_then_keeps_data(
    api: TestClient, w: str, db: Db, data_dir: Path, extra_migration: Callable[[str], None]
) -> None:
    server = {"name": "gpu-7", "host": "10.0.0.1", "username": "ubuntu", "auth_type": "password", "password": "pw"}
    api.post(f"{w}/servers", json=server)
    # Rebuilding workspaces is the case that would cascade-delete their members, or be refused
    # because servers point at them.
    extra_migration(
        'with op.batch_alter_table("workspaces", recreate="always") as batch:\n'
        '    batch.add_column(sa.Column("note", sa.String(50)))'
    )

    signed_in_at = db(_admin_last_login)

    with TestClient(create_app()) as fresh:
        headers = login_headers(fresh, ADMIN["email"], ADMIN["password"])
        # Signing in while an upgrade waits only reads the database.
        assert db(_admin_last_login) == signed_in_at
        assert fresh.get("/api/health").json()["database"] == "upgrade_required"
        blocked = fresh.get(f"{w}/servers", headers=headers)
        assert blocked.status_code == 503
        assert blocked.json()["code"] == "database_upgrade_required"
        assert fresh.get("/api/database", headers=headers).json()["pending"] == ["Add a test column"]

        response = fresh.post("/api/database/upgrade", headers=headers)
        assert response.status_code == 200, response.text
        done = response.json()
        assert done["state"] == "current"
        assert done["last_upgrade"]["by"] == "Admin"
        assert done["last_upgrade"]["from_revision"] == HEAD
        assert done["last_upgrade"]["upgraded_at"]

        assert fresh.get(w, headers=headers).json()["member_count"] == 1
        assert [s["name"] for s in fresh.get(f"{w}/servers", headers=headers).json()] == ["gpu-7"]
        backup = migrate.newest_backup(data_dir / "vservx.db")
        assert done["latest_backup"]["name"] == backup.name
        assert _sql(backup, "SELECT count(*) FROM workspace_members") == [(1,)]


def test_waiting_upgrade_lets_only_admins_in(
    admin_headers: dict[str, str], add_user: Callable[..., None], data_dir: Path,
    extra_migration: Callable[[str], None],
) -> None:
    add_user("member@example.com")
    extra_migration('op.create_table("extra", sa.Column("id", sa.Integer, primary_key=True))')
    with TestClient(create_app()) as fresh:
        assert fresh.post("/api/auth/login", json=ADMIN).status_code == 200
        member = fresh.post("/api/auth/login", json={"email": "member@example.com", "password": USER_PASSWORD})
        assert (member.status_code, member.json()["code"]) == (503, "database_upgrade_required")
        assert fresh.get("/api/workspaces", headers=admin_headers).status_code == 503
        # Upgrading from the command line unblocks the running app.
        migrate.upgrade_database(data_dir / "vservx.db", by="command line", user_id=None, source="cli")
        assert fresh.get("/api/workspaces", headers=admin_headers).status_code == 200
