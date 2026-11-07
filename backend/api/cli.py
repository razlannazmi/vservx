"""The vservx command line: `vservx serve`, `vservx db status` and `vservx db upgrade`."""

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


def _serve(host: str, port: int, forwarded_allow_ips: str | None) -> int:
    # Imported here so `vservx db` doesn't load the web app.
    import uvicorn

    # One process, no reload: each process watches every server. None leaves uvicorn's own
    # default, the FORWARDED_ALLOW_IPS environment variable or else 127.0.0.1 and ::1.
    uvicorn.run("api.main:app", host=host, port=port, forwarded_allow_ips=forwarded_allow_ips)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vservx")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run vservx: the API and the built web app, without auto-reload")
    serve.add_argument("--host", help="address to listen on (default: VSERVX_HOST, or 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port to listen on (default: VSERVX_PORT, or 5325)")
    serve.add_argument(
        "--forwarded-allow-ips", metavar="IPS",
        help="comma-separated addresses of reverse proxies trusted to set X-Forwarded-For and "
             "X-Forwarded-Proto, or * for any (default: FORWARDED_ALLOW_IPS, or 127.0.0.1,::1)",
    )
    db = commands.add_parser("db", help="database status and upgrades")
    db_commands = db.add_subparsers(dest="action", required=True)
    db_commands.add_parser("status", help="show whether the database needs an upgrade")
    db_commands.add_parser("upgrade", help="back up the database, then apply pending migrations")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "serve":
        host = settings.host if args.host is None else args.host
        port = settings.port if args.port is None else args.port
        return _serve(host, port, args.forwarded_allow_ips)

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    action = _status if args.action == "status" else _upgrade
    try:
        return action(settings.db_path)
    except (migrate.PreMigrationDatabaseError, migrate.UpgradeError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
