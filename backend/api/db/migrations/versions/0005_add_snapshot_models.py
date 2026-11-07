"""Add the served model to snapshots

Each snapshot keeps the model its container served, so old entries say what they ran. Snapshots
taken before this have none.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model', sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.drop_column('model')
