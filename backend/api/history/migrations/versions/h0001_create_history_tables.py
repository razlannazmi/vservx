"""Create the history tables

Usage and GPU readings with minute and hour rollups, state changes, model logs and where reading
them resumes, the audit, and vservx's own log. Readings, logs and minute rollups are partitioned
by day; each starts with a default partition for rows no day partition holds.

Revision ID: h0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'h0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USAGE = ('running', 'waiting', 'kv_cache_percent', 'tokens_in_per_s', 'tokens_out_per_s', 'ttft_seconds')
_GPU = ('utilization', 'memory_used', 'memory_total', 'temperature')
_PARTITIONED = ('usage_points', 'usage_1m', 'gpu_points', 'gpu_1m', 'model_logs', 'app_logs')


def _time(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.TIMESTAMP(timezone=True), nullable=nullable)


def _values(metrics: tuple[str, ...]) -> list[sa.Column]:
    return [sa.Column(metric, postgresql.REAL(), nullable=True) for metric in metrics]


def _rollups(metrics: tuple[str, ...]) -> list[sa.Column]:
    columns = [sa.Column('n', sa.Integer(), nullable=False)]
    for metric in metrics:
        columns += [sa.Column(f'{metric}_{kind}', postgresql.REAL(), nullable=True) for kind in ('min', 'avg', 'max')]
    return columns


def upgrade() -> None:
    op.create_table('series',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('server_uid', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_series')),
    sa.UniqueConstraint('server_uid', 'source', 'name', name=op.f('uq_series_server_uid'))
    )

    op.create_table('usage_points',
    sa.Column('series_id', sa.BigInteger(), nullable=False),
    _time('at'),
    *_values(_USAGE),
    postgresql_partition_by='RANGE (at)'
    )
    op.create_index('ix_usage_points_series_id_at', 'usage_points', ['series_id', 'at'])

    for name, partitioned in (('usage_1m', True), ('usage_1h', False)):
        op.create_table(name,
        sa.Column('series_id', sa.BigInteger(), nullable=False),
        _time('bucket'),
        *_rollups(_USAGE),
        sa.PrimaryKeyConstraint('series_id', 'bucket', name=op.f(f'pk_{name}')),
        **({'postgresql_partition_by': 'RANGE (bucket)'} if partitioned else {})
        )

    op.create_table('gpu_points',
    sa.Column('server_uid', sa.Text(), nullable=False),
    sa.Column('gpu_index', sa.Integer(), nullable=False),
    _time('at'),
    *_values(_GPU),
    postgresql_partition_by='RANGE (at)'
    )
    op.create_index('ix_gpu_points_server_uid_at', 'gpu_points', ['server_uid', 'at'])

    for name, partitioned in (('gpu_1m', True), ('gpu_1h', False)):
        op.create_table(name,
        sa.Column('server_uid', sa.Text(), nullable=False),
        sa.Column('gpu_index', sa.Integer(), nullable=False),
        _time('bucket'),
        *_rollups(_GPU),
        sa.PrimaryKeyConstraint('server_uid', 'gpu_index', 'bucket', name=op.f(f'pk_{name}')),
        **({'postgresql_partition_by': 'RANGE (bucket)'} if partitioned else {})
        )

    op.create_table('state_changes',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('server_uid', sa.Text(), nullable=False),
    sa.Column('series_id', sa.BigInteger(), nullable=True),
    _time('at'),
    sa.Column('from_state', sa.Text(), nullable=True),
    sa.Column('to_state', sa.Text(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_state_changes'))
    )
    op.create_index('ix_state_changes_server_uid_at', 'state_changes', ['server_uid', 'at'])

    op.create_table('model_logs',
    sa.Column('series_id', sa.BigInteger(), nullable=False),
    _time('at'),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('stream', sa.Text(), nullable=False),
    sa.Column('level', sa.Text(), nullable=True),
    sa.Column('request', sa.Boolean(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    postgresql_partition_by='RANGE (at)'
    )
    op.create_index('ix_model_logs_series_id_at_seq', 'model_logs', ['series_id', 'at', 'seq'])

    op.create_table('log_cursors',
    sa.Column('series_id', sa.BigInteger(), autoincrement=False, nullable=False),
    _time('at', nullable=True),
    sa.Column('at_count', sa.Integer(), nullable=False),
    sa.Column('journal', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('series_id', name=op.f('pk_log_cursors'))
    )

    op.create_table('audit_entries',
    sa.Column('id', sa.BigInteger(), nullable=False),
    _time('at'),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('result', sa.Text(), nullable=False),
    sa.Column('user_uid', sa.Text(), nullable=True),
    sa.Column('user_name', sa.Text(), nullable=True),
    sa.Column('user_email', sa.Text(), nullable=True),
    sa.Column('workspace_uid', sa.Text(), nullable=True),
    sa.Column('server_uid', sa.Text(), nullable=True),
    sa.Column('client_ip', sa.Text(), nullable=True),
    sa.Column('target', sa.Text(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_entries'))
    )
    op.create_index('ix_audit_entries_at', 'audit_entries', ['at'])
    op.create_index('ix_audit_entries_workspace_uid_at', 'audit_entries', ['workspace_uid', 'at'])

    op.create_table('app_logs',
    _time('at'),
    sa.Column('level', sa.Text(), nullable=False),
    sa.Column('logger', sa.Text(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('exception', sa.Text(), nullable=True),
    postgresql_partition_by='RANGE (at)'
    )
    op.create_index('ix_app_logs_at', 'app_logs', ['at'])

    op.create_table('rollup_marks',
    sa.Column('name', sa.Text(), nullable=False),
    _time('done_until'),
    sa.PrimaryKeyConstraint('name', name=op.f('pk_rollup_marks'))
    )

    for name in _PARTITIONED:
        op.execute(f'CREATE TABLE {name}_default PARTITION OF {name} DEFAULT')


def downgrade() -> None:
    # Dropping a partitioned table drops its partitions and indexes too.
    for name in ('rollup_marks', 'app_logs', 'audit_entries', 'log_cursors', 'model_logs', 'state_changes',
                 'gpu_1h', 'gpu_1m', 'gpu_points', 'usage_1h', 'usage_1m', 'usage_points', 'series'):
        op.drop_table(name)
