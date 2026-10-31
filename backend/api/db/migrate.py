"""Schema migrations: which state the database is in, and bringing it up to date.

Migrations run on their own synchronous engine, not the app's async one, because they need two
things the app's connections don't give them: foreign keys off (rebuilding a table with them on
would cascade-delete its child rows), and DDL that really runs inside one transaction.
"""

import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from sqlalchemy import Connection, Engine, create_engine, event, insert, inspect, select
from sqlalchemy.pool import NullPool

from api.db.base import utcnow
from api.enums import DatabaseState
from api.models import ActionHistory

logger = logging.getLogger(__name__)

SCRIPT_LOCATION = str(Path(__file__).parent / "migrations")
UPGRADE_ACTION = "database_upgrade"


class PreMigrationDatabaseError(RuntimeError):
    def __init__(self, db_path: Path) -> None:
        super().__init__(
            f"{db_path} was created before vservx had database migrations and can't be upgraded. "
            "Move it aside or delete it, then start vservx again to create a new one."
        )


class UpgradeError(RuntimeError):
    """The upgrade didn't happen. The message says why, in words fit to show the user."""


@dataclass(frozen=True)
class LastUpgrade:
    upgraded_at: datetime
    # The admin's name, or "command line".
    by: str
    from_revision: str
    to_revision: str


@dataclass(frozen=True)
class DatabaseStatus:
    state: DatabaseState
    current_revision: str | None
    head_revision: str
    # Descriptions of the migrations still to apply, oldest first.
    pending: list[str]
    last_upgrade: LastUpgrade | None = None


@dataclass(frozen=True)
class UpgradeResult:
    from_revision: str
    to_revision: str
    upgraded_at: datetime
    backup: Path


def migration_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", poolclass=NullPool)

    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn: Any, _: Any) -> None:
        # Let SQLAlchemy open transactions itself: the sqlite3 driver would run DDL outside one.
        dbapi_conn.isolation_level = None
        dbapi_conn.execute("PRAGMA foreign_keys=OFF")
        dbapi_conn.execute("PRAGMA busy_timeout=5000")

    @event.listens_for(engine, "begin")
    def _begin(conn: Connection) -> None:
        # IMMEDIATE takes the write lock up front, so two upgrades can't interleave.
        immediate = conn.get_execution_options().get("immediate", False)
        conn.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


def alembic_config(db_path: Path) -> Config:
    config = Config()
    # Escaped because Config values go through configparser interpolation.
    config.set_main_option("script_location", SCRIPT_LOCATION.replace("%", "%%"))
    config.attributes["db_path"] = db_path
    return config


def backups_dir(db_path: Path) -> Path:
    return db_path.parent / "backups"


def newest_backup(db_path: Path) -> Path | None:
    # Names start with a UTC timestamp, so the last one in name order is the newest.
    backups = sorted(backups_dir(db_path).glob("vservx-*.db"))
    return backups[-1] if backups else None


def inspect_database(db_path: Path) -> DatabaseStatus:
    script = ScriptDirectory.from_config(alembic_config(db_path))
    head = script.get_current_head()
    engine = migration_engine(db_path)
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names()) - {"alembic_version"}
            current = MigrationContext.configure(conn).get_current_revision()
            last = _last_upgrade(conn) if current is not None else None
    finally:
        engine.dispose()

    if current is None:
        if tables:
            raise PreMigrationDatabaseError(db_path)
        return DatabaseStatus(DatabaseState.NEW, None, head, _descriptions(script, head, "base"))
    if current == head:
        return DatabaseStatus(DatabaseState.CURRENT, current, head, [], last)
    try:
        pending = _descriptions(script, head, current)
    except RevisionError:
        # A revision this code has never heard of: written by a newer vservx.
        return DatabaseStatus(DatabaseState.NEWER_THAN_APP, current, head, [], last)
    return DatabaseStatus(DatabaseState.UPGRADE_REQUIRED, current, head, pending, last)


def create_database(db_path: Path) -> None:
    """Build the newest schema in a database that has no tables yet."""
    engine = migration_engine(db_path)
    try:
        with engine.connect().execution_options(immediate=True) as conn, conn.begin():
            # Another process may have created it while this one waited for the lock.
            if MigrationContext.configure(conn).get_current_revision() is None:
                _run_migrations(conn, db_path)
    finally:
        engine.dispose()


def upgrade_database(db_path: Path, *, by: str, user_id: int | None, source: str) -> UpgradeResult | None:
    """Back up the database, then apply every pending migration in one transaction.

    Returns None when there was nothing to do, including when another process upgraded it first.
    """
    status = inspect_database(db_path)
    if status.state is DatabaseState.CURRENT:
        return None
    if status.state is DatabaseState.NEWER_THAN_APP:
        raise UpgradeError(
            "The database is from a newer version of vservx. Run that version, or restore a backup."
        )
    if status.state is DatabaseState.NEW:
        raise UpgradeError("There is no database to upgrade yet.")

    from_revision = status.current_revision
    backup = _back_up(db_path, from_revision)
    engine = migration_engine(db_path)
    try:
        with engine.connect().execution_options(immediate=True) as conn, conn.begin():
            if MigrationContext.configure(conn).get_current_revision() != from_revision:
                backup.unlink()
                return None
            _run_migrations(conn, db_path)
            upgraded_at = utcnow()
            detail = {"from": from_revision, "to": status.head_revision, "backup": backup.name,
                      "by": by, "source": source}
            conn.execute(insert(ActionHistory.__table__).values(
                created_at=upgraded_at, user_id=user_id, action=UPGRADE_ACTION, result="ok",
                detail=json.dumps(detail),
            ))
    except Exception as exc:
        logger.exception("Database upgrade from revision %s failed", from_revision)
        raise UpgradeError(
            f"Upgrade failed: {exc}. The database is unchanged; a backup is at {backup.name}."
        ) from exc
    finally:
        engine.dispose()
    logger.info("Upgraded the database from %s to %s (%s)", from_revision, status.head_revision, by)
    return UpgradeResult(from_revision, status.head_revision, upgraded_at, backup)


def _descriptions(script: ScriptDirectory, head: str, current: str) -> list[str]:
    revisions = [rev for rev in script.iterate_revisions(head, current) if rev.revision != current]
    return [rev.doc for rev in reversed(revisions)]


def _run_migrations(conn: Connection, db_path: Path) -> None:
    config = alembic_config(db_path)
    config.attributes["connection"] = conn
    command.upgrade(config, "head")
    broken = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise RuntimeError(f"Migration left {len(broken)} broken foreign key reference(s)")


def _back_up(db_path: Path, revision: str) -> Path:
    folder = backups_dir(db_path)
    path = folder / f"vservx-{utcnow():%Y%m%dT%H%M%SZ}-{revision}.db"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        # VACUUM INTO writes a consistent copy, including anything still in the WAL file.
        with closing(sqlite3.connect(db_path, isolation_level=None)) as conn:
            conn.execute("VACUUM INTO ?", (str(path),))
    except (OSError, sqlite3.Error) as exc:
        raise UpgradeError(f"Couldn't back up the database, so it wasn't upgraded: {exc}") from exc
    return path


def _last_upgrade(conn: Connection) -> LastUpgrade | None:
    # Only columns every revision of action_history has, so this also works while an upgrade waits.
    history = ActionHistory.__table__
    row = conn.execute(
        select(history.c.created_at, history.c.detail)
        .where(history.c.action == UPGRADE_ACTION)
        .order_by(history.c.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    detail = json.loads(row.detail)
    return LastUpgrade(row.created_at, detail["by"], detail["from"], detail["to"])
