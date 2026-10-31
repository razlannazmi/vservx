"""Alembic environment.

vservx runs migrations through api.db.migrate, which passes in its own connection (foreign keys off,
already inside the upgrade's transaction). Run from the alembic command line instead (e.g.
`alembic revision --autogenerate` from backend/), it opens the database in VSERVX_DATA_DIR.
"""

from typing import Any

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.types import TypeDecorator

import api.models  # noqa: F401  # registers all tables on Base.metadata
from api.config import get_settings
from api.db.base import Base
from api.db.migrate import migration_engine

config = context.config


def _render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    # Write app column types (UTCDateTime, EncryptedString) as their plain SQL type,
    # so migration files never import app code that may change later.
    if type_ == "type" and isinstance(obj, TypeDecorator):
        return f"sa.{obj.impl!r}"
    return False


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    engine = migration_engine(config.attributes.get("db_path") or get_settings().db_path)
    try:
        with engine.connect() as conn:
            _run(conn)
    finally:
        engine.dispose()
