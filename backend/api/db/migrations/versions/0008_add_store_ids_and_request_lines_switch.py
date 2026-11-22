"""Add store ids and the request lines switch

Accounts, workspaces and servers get a uid: a random id that names them in the history store.
The store keeps their history after the row here is deleted, and SQLite can give a deleted row's
id to a new one, so the id alone could tie old history to a new account, workspace or server.
Every existing row gets its own uid.

Servers get keep_request_logs, off for every server: whether vLLM's per-request log lines, which
can include the prompts users send, are kept.

Revision ID: 0008
Revises: 0007
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008'
down_revision: str | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ('users', 'workspaces', 'servers')


def upgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('uid', sa.String(length=36), nullable=True))

        rows = sa.table(table, sa.column('id'), sa.column('uid'))
        for row_id in conn.scalars(sa.select(rows.c.id)).all():
            conn.execute(rows.update().where(rows.c.id == row_id).values(uid=str(uuid.uuid4())))

        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('uid', existing_type=sa.String(length=36), nullable=False)
            batch_op.create_unique_constraint(batch_op.f(f'uq_{table}_uid'), ['uid'])
            if table == 'servers':
                batch_op.add_column(sa.Column('keep_request_logs', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    for table in reversed(_TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            if table == 'servers':
                batch_op.drop_column('keep_request_logs')
            batch_op.drop_constraint(batch_op.f(f'uq_{table}_uid'), type_='unique')
            batch_op.drop_column('uid')
