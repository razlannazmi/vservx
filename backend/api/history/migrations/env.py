"""Alembic environment for the history store.

vservx runs store migrations only through api.history.migrate, which passes in a connection that
is already inside the migration's transaction and holds the store's advisory lock.
"""

from alembic import context

from api.history.schema import metadata

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("History store migrations run through api.history.migrate, not the alembic command line")

context.configure(connection=connection, target_metadata=metadata)
with context.begin_transaction():
    context.run_migrations()
