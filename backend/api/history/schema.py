"""The history store's PostgreSQL tables.

- Raw readings, logs and minute rollups are partitioned by day on their time column; the
  Maintainer adds day partitions, and rows outside them land in `<table>_default`.
- Hour rollups, state changes and the audit stay unpartitioned: they're small.
- Store migrations (api/history/migrations) build these tables; this module describes them for
  reads, writes and the migrations' drift check.
"""

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, REAL

metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
})

USAGE_METRICS = ("running", "waiting", "kv_cache_percent", "tokens_in_per_s", "tokens_out_per_s", "ttft_seconds")
GPU_METRICS = ("utilization", "memory_used", "memory_total", "temperature")

PARTITIONED = ("usage_points", "usage_1m", "gpu_points", "gpu_1m", "model_logs", "app_logs")


def _time(name: str) -> Column:
    return Column(name, TIMESTAMP(timezone=True), nullable=False)


def _values(metrics: tuple[str, ...]) -> list[Column]:
    return [Column(metric, REAL) for metric in metrics]


def _rollups(metrics: tuple[str, ...]) -> list[Column]:
    """Readings in a bucket: how many, and each metric's min, average and max."""
    columns = [Column("n", Integer, nullable=False)]
    for metric in metrics:
        columns += [Column(f"{metric}_{kind}", REAL) for kind in ("min", "avg", "max")]
    return columns


series = Table(
    "series", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("server_uid", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("name", Text, nullable=False),
    UniqueConstraint("server_uid", "source", "name"),
)

usage_points = Table(
    "usage_points", metadata,
    Column("series_id", BigInteger, nullable=False),
    _time("at"),
    *_values(USAGE_METRICS),
    Index("ix_usage_points_series_id_at", "series_id", "at"),
    postgresql_partition_by="RANGE (at)",
)

usage_1m = Table(
    "usage_1m", metadata,
    Column("series_id", BigInteger, nullable=False),
    _time("bucket"),
    *_rollups(USAGE_METRICS),
    PrimaryKeyConstraint("series_id", "bucket"),
    postgresql_partition_by="RANGE (bucket)",
)

usage_1h = Table(
    "usage_1h", metadata,
    Column("series_id", BigInteger, nullable=False),
    _time("bucket"),
    *_rollups(USAGE_METRICS),
    PrimaryKeyConstraint("series_id", "bucket"),
)

gpu_points = Table(
    "gpu_points", metadata,
    Column("server_uid", Text, nullable=False),
    Column("gpu_index", Integer, nullable=False),
    _time("at"),
    *_values(GPU_METRICS),
    Index("ix_gpu_points_server_uid_at", "server_uid", "at"),
    postgresql_partition_by="RANGE (at)",
)

gpu_1m = Table(
    "gpu_1m", metadata,
    Column("server_uid", Text, nullable=False),
    Column("gpu_index", Integer, nullable=False),
    _time("bucket"),
    *_rollups(GPU_METRICS),
    PrimaryKeyConstraint("server_uid", "gpu_index", "bucket"),
    postgresql_partition_by="RANGE (bucket)",
)

gpu_1h = Table(
    "gpu_1h", metadata,
    Column("server_uid", Text, nullable=False),
    Column("gpu_index", Integer, nullable=False),
    _time("bucket"),
    *_rollups(GPU_METRICS),
    PrimaryKeyConstraint("server_uid", "gpu_index", "bucket"),
)

# A server's change has no series_id. from_state None: first seen; to_state None: removed.
state_changes = Table(
    "state_changes", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("server_uid", Text, nullable=False),
    Column("series_id", BigInteger),
    _time("at"),
    Column("from_state", Text),
    Column("to_state", Text),
    Column("message", Text),
    Index("ix_state_changes_server_uid_at", "server_uid", "at"),
)

# request: one of vLLM's per-request lines, which can include prompts. seq orders lines that share a time.
model_logs = Table(
    "model_logs", metadata,
    Column("series_id", BigInteger, nullable=False),
    _time("at"),
    Column("seq", Integer, nullable=False),
    Column("stream", Text, nullable=False),
    Column("level", Text),
    Column("request", Boolean, nullable=False),
    Column("text", Text, nullable=False),
    Index("ix_model_logs_series_id_at_seq", "series_id", "at", "seq"),
    postgresql_partition_by="RANGE (at)",
)

# Where reading each series' log resumes (api.history.types.LogCursor).
log_cursors = Table(
    "log_cursors", metadata,
    Column("series_id", BigInteger, primary_key=True, autoincrement=False),
    Column("at", TIMESTAMP(timezone=True)),
    Column("at_count", Integer, nullable=False),
    Column("journal", Text),
)

audit_entries = Table(
    "audit_entries", metadata,
    Column("id", BigInteger, primary_key=True),
    _time("at"),
    Column("action", Text, nullable=False),
    Column("result", Text, nullable=False),
    Column("user_uid", Text),
    Column("user_name", Text),
    Column("user_email", Text),
    Column("workspace_uid", Text),
    Column("server_uid", Text),
    Column("client_ip", Text),
    Column("target", Text),
    Column("detail", JSONB, nullable=False),
    Index("ix_audit_entries_at", "at"),
    Index("ix_audit_entries_workspace_uid_at", "workspace_uid", "at"),
)

app_logs = Table(
    "app_logs", metadata,
    _time("at"),
    Column("level", Text, nullable=False),
    Column("logger", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("exception", Text),
    Index("ix_app_logs_at", "at"),
    postgresql_partition_by="RANGE (at)",
)

# How far each rollup has been computed: name is usage_1m, usage_1h, gpu_1m or gpu_1h.
rollup_marks = Table(
    "rollup_marks", metadata,
    Column("name", Text, primary_key=True),
    _time("done_until"),
)
