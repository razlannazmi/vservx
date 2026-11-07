"""Reshape instances and snapshots for launch snapshots

No code ever wrote the instances or snapshots tables made by 0001, so there is nothing to carry
over: both are dropped and created in their new shape. action_history keeps its foreign key to
instances.id.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = ('first_seen', 'recreated', 'recreated_same', 'changed', 'removed')


def _drop_old() -> None:
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_snapshots_server_id'))
        batch_op.drop_index(batch_op.f('ix_snapshots_instance_id'))
    op.drop_table('snapshots')
    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_instances_server_id'))
    op.drop_table('instances')


def upgrade() -> None:
    _drop_old()
    op.create_table('instances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('container_id', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=512), nullable=True),
    sa.Column('first_seen', sa.DateTime(), nullable=False),
    sa.Column('last_seen', sa.DateTime(), nullable=False),
    sa.Column('removed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_instances_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_instances')),
    sa.UniqueConstraint('server_id', 'name', name=op.f('uq_instances_server_id'))
    )
    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_instances_server_id'), ['server_id'], unique=False)

    op.create_table('snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('instance_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum(*_KINDS, name='snapshotkind', native_enum=False, length=32), nullable=False),
    sa.Column('happened_at', sa.DateTime(), nullable=False),
    sa.Column('noticed_at', sa.DateTime(), nullable=False),
    sa.Column('container_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('restart_count', sa.Integer(), nullable=True),
    sa.Column('image_id', sa.String(length=128), nullable=True),
    sa.Column('vllm_version', sa.String(length=64), nullable=True),
    sa.Column('config', sa.JSON(), nullable=True),
    sa.Column('key_fingerprint', sa.String(length=16), nullable=True),
    sa.Column('key_id', sa.String(length=16), nullable=True),
    sa.Column('last_seen', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['instance_id'], ['instances.id'], name=op.f('fk_snapshots_instance_id_instances'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_snapshots_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_snapshots'))
    )
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_snapshots_instance_id'), ['instance_id'], unique=False)
        batch_op.create_index('ix_snapshots_server_happened', ['server_id', 'happened_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.drop_index('ix_snapshots_server_happened')
        batch_op.drop_index(batch_op.f('ix_snapshots_instance_id'))
    op.drop_table('snapshots')
    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_instances_server_id'))
    op.drop_table('instances')

    # The shapes 0001 made.
    op.create_table('instances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('launch_type', sa.Enum('docker', 'systemd', 'bare', name='launchtype', native_enum=False, length=32), nullable=False),
    sa.Column('ref', sa.String(length=255), nullable=False),
    sa.Column('model', sa.String(length=512), nullable=True),
    sa.Column('port', sa.Integer(), nullable=True),
    sa.Column('managed', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('last_seen', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_instances_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_instances')),
    sa.UniqueConstraint('server_id', 'launch_type', 'ref', name=op.f('uq_instances_server_id'))
    )
    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_instances_server_id'), ['server_id'], unique=False)

    op.create_table('snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('instance_id', sa.Integer(), nullable=True),
    sa.Column('server_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('trigger', sa.Enum('discovery', 'pre-stop', 'manual', name='snapshottrigger', native_enum=False, length=32), nullable=False),
    sa.Column('launch_type', sa.Enum('docker', 'systemd', 'bare', name='launchtype', native_enum=False, length=32), nullable=False),
    sa.Column('command', sa.Text(), nullable=True),
    sa.Column('cwd', sa.String(length=1024), nullable=True),
    sa.Column('run_user', sa.String(length=255), nullable=True),
    sa.Column('env', sa.JSON(), nullable=True),
    sa.Column('image', sa.String(length=512), nullable=True),
    sa.Column('gpus', sa.JSON(), nullable=True),
    sa.Column('ports', sa.JSON(), nullable=True),
    sa.Column('volumes', sa.JSON(), nullable=True),
    sa.Column('vllm_version', sa.String(length=64), nullable=True),
    sa.Column('raw', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['instance_id'], ['instances.id'], name=op.f('fk_snapshots_instance_id_instances'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_snapshots_server_id_servers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_snapshots'))
    )
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_snapshots_instance_id'), ['instance_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_snapshots_server_id'), ['server_id'], unique=False)
