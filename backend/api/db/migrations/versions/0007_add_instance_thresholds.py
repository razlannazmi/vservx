"""Add instance thresholds

Each instance can have a warning and a critical value per usage metric, shared by the workspace.
An instance with no row for a metric uses that metric's default.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('instance_thresholds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('instance_id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.Enum('waiting', 'kv_cache_percent', 'ttft_seconds', name='thresholdmetric', native_enum=False, length=32), nullable=False),
    sa.Column('warning', sa.Double(), nullable=True),
    sa.Column('critical', sa.Double(), nullable=True),
    sa.ForeignKeyConstraint(['instance_id'], ['instances.id'], name=op.f('fk_instance_thresholds_instance_id_instances'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_instance_thresholds')),
    sa.UniqueConstraint('instance_id', 'metric', name=op.f('uq_instance_thresholds_instance_id'))
    )
    with op.batch_alter_table('instance_thresholds', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_instance_thresholds_instance_id'), ['instance_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('instance_thresholds', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_instance_thresholds_instance_id'))
    op.drop_table('instance_thresholds')
