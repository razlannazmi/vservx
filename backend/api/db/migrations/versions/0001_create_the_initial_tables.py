"""Create the initial tables

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ssh_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('private_key', sa.String(), nullable=False),
    sa.Column('passphrase', sa.String(), nullable=True),
    sa.Column('key_type', sa.String(length=64), nullable=False),
    sa.Column('fingerprint', sa.String(length=128), nullable=False),
    sa.Column('public_key', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ssh_keys')),
    sa.UniqueConstraint('name', name=op.f('uq_ssh_keys_name'))
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('admin', 'operator', 'viewer', name='userrole', native_enum=False, length=32), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('servers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=255), nullable=False),
    sa.Column('auth_type', sa.Enum('password', 'key', name='authtype', native_enum=False, length=32), nullable=False),
    sa.Column('password', sa.String(), nullable=True),
    sa.Column('ssh_key_id', sa.Integer(), nullable=True),
    sa.Column('jump_server_id', sa.Integer(), nullable=True),
    sa.Column('jump_only', sa.Boolean(), nullable=False),
    sa.Column('host_key', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['jump_server_id'], ['servers.id'], name=op.f('fk_servers_jump_server_id_servers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['ssh_key_id'], ['ssh_keys.id'], name=op.f('fk_servers_ssh_key_id_ssh_keys'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_servers')),
    sa.UniqueConstraint('name', name=op.f('uq_servers_name'))
    )
    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_servers_jump_server_id'), ['jump_server_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_servers_ssh_key_id'), ['ssh_key_id'], unique=False)

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

    op.create_table('action_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('server_id', sa.Integer(), nullable=True),
    sa.Column('instance_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('result', sa.String(length=32), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['instance_id'], ['instances.id'], name=op.f('fk_action_history_instance_id_instances'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['server_id'], ['servers.id'], name=op.f('fk_action_history_server_id_servers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_action_history_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_action_history'))
    )
    with op.batch_alter_table('action_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_action_history_created_at'), ['created_at'], unique=False)

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


def downgrade() -> None:
    with op.batch_alter_table('snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_snapshots_server_id'))
        batch_op.drop_index(batch_op.f('ix_snapshots_instance_id'))

    op.drop_table('snapshots')
    with op.batch_alter_table('action_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_action_history_created_at'))

    op.drop_table('action_history')
    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_instances_server_id'))

    op.drop_table('instances')
    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_servers_ssh_key_id'))
        batch_op.drop_index(batch_op.f('ix_servers_jump_server_id'))

    op.drop_table('servers')
    op.drop_table('users')
    op.drop_table('ssh_keys')
