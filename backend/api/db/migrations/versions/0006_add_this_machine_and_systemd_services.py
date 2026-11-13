"""Add this machine and systemd services

Servers get a kind: ssh (every existing server) or this_machine, which has no host or sign-in.
Instances get a source: docker (every existing instance) or a systemd service. The unique
constraint on instances now includes the source, so a container and a service may share a name.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kind', sa.Enum('ssh', 'this_machine', name='serverkind', native_enum=False, length=32), server_default='ssh', nullable=False))
        batch_op.alter_column('host', existing_type=sa.String(length=255), nullable=True)
        batch_op.alter_column('username', existing_type=sa.String(length=255), nullable=True)
        batch_op.alter_column('auth_type', existing_type=sa.Enum('password', 'key', name='authtype', native_enum=False, length=32), nullable=True)

    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.Enum('docker', 'systemd', 'systemd-user', name='instancesource', native_enum=False, length=32), server_default='docker', nullable=False))
        batch_op.drop_constraint(batch_op.f('uq_instances_server_id'), type_='unique')
        batch_op.create_unique_constraint(batch_op.f('uq_instances_server_id'), ['server_id', 'source', 'name'])


def downgrade() -> None:
    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_instances_server_id'), type_='unique')
        batch_op.create_unique_constraint(batch_op.f('uq_instances_server_id'), ['server_id', 'name'])
        batch_op.drop_column('source')

    with op.batch_alter_table('servers', schema=None) as batch_op:
        batch_op.alter_column('auth_type', existing_type=sa.Enum('password', 'key', name='authtype', native_enum=False, length=32), nullable=False)
        batch_op.alter_column('username', existing_type=sa.String(length=255), nullable=False)
        batch_op.alter_column('host', existing_type=sa.String(length=255), nullable=False)
        batch_op.drop_column('kind')
