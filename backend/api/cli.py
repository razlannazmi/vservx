"""The vservx command line: `vservx db status` and `vservx db upgrade`."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from api.config import get_settings
from api.db import migrate
from api.enums import DatabaseState


def _when(moment: datetime) -> str:
    return f"{moment:%Y-%m-%d %H:%M:%S} UTC"


def _status(db_path: Path) -> int:
    status = migrate.inspect_database(db_path)
    print(f"Database: {status.state}")
    print(f"Revision: {status.current_revision or 'none'} (latest {status.head_revision})")
    for description in status.pending:
        print(f"  - {description}")
    last = status.last_upgrade
    print(f"Last upgrade: {_when(last.upgraded_at)} by {last.by}" if last else "Last upgrade: never")
    return 0


def _upgrade(db_path: Path) -> int:
    if migrate.inspect_database(db_path).state is DatabaseState.NEW:
        migrate.create_database(db_path)
        print(f"Created a new database at {db_path}.")
        return 0
    result = migrate.upgrade_database(db_path, by="command line", user_id=None, source="cli")
    if result is None:
        print("Database is already up to date.")
    else:
        print(f"Upgraded {result.from_revision} -> {result.to_revision} at {_when(result.upgraded_at)}.")
        print(f"Backup: {result.backup}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vservx")
    commands = parser.add_subparsers(dest="command", required=True)
    db = commands.add_parser("db", help="database status and upgrades")
    db_commands = db.add_subparsers(dest="action", required=True)
    db_commands.add_parser("status", help="show whether the database needs an upgrade")
    db_commands.add_parser("upgrade", help="back up the database, then apply pending migrations")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    action = _status if args.action == "status" else _upgrade
    try:
        return action(settings.db_path)
    except (migrate.PreMigrationDatabaseError, migrate.UpgradeError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
