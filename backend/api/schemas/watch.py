"""What vservx has seen on the servers it watches. Read from memory; nothing here is stored."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import DockerStatus, InstanceSource, InstanceState, WatchState

# Defaults would otherwise mark fields optional in the OpenAPI response schema.
_READ = ConfigDict(json_schema_serialization_defaults_required=True)


class UsagePointRead(BaseModel):
    model_config = _READ

    at: datetime
    running: float | None
    waiting: float | None
    kv_cache_percent: float | None
    tokens_in_per_s: float | None
    tokens_out_per_s: float | None
    # Averaged over the last minute.
    ttft_seconds: float | None


class WatchedInstanceRead(BaseModel):
    model_config = _READ

    # The container's or unit's name; with its source, an instance's identity on its server.
    name: str
    source: InstanceSource
    framework: str
    state: InstanceState
    message: str | None
    image: str
    model: str | None
    port: int
    max_model_len: int | None
    version: str | None
    gpus: list[str] | None
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    oom_killed: bool
    restart_count: int
    # The latest reading; only while the instance is ready, so old numbers never pass for current.
    usage: UsagePointRead | None
    # Running requests over the kept history, oldest first.
    running_trend: list[float | None]
    # When its latest snapshot was a recreation or change; None when it's first seen (or unknown).
    changed_at: datetime | None = None


class RemovedInstanceRead(BaseModel):
    """A container noticed removed in the last 7 days. Its snapshots are kept."""

    model_config = _READ

    name: str
    source: InstanceSource
    image: str | None
    model: str | None
    last_seen: datetime
    removed_at: datetime


class GpuRead(BaseModel):
    model_config = _READ

    index: int
    name: str
    utilization_percent: float | None
    memory_used_mib: float | None
    memory_total_mib: float | None
    temperature_c: float | None
    # Containers Docker gave this GPU.
    instances: list[str]


class ServerWatchRead(BaseModel):
    model_config = _READ

    server_id: int
    state: WatchState
    since: datetime | None
    message: str | None
    docker: DockerStatus
    docker_message: str | None
    # When instances were last looked for, and when usage was last read.
    found_at: datetime | None
    read_at: datetime | None
    # Sorted by name.
    instances: list[WatchedInstanceRead]
    # Removed in the last 7 days and not back since, newest first.
    removed: list[RemovedInstanceRead] = []
    # None when nvidia-smi isn't available (gpu_message says why) or hasn't run yet.
    gpus: list[GpuRead] | None
    gpu_message: str | None
    usage_interval_seconds: float


class WatchSummaryRead(BaseModel):
    """What a server card needs."""

    model_config = _READ

    server_id: int
    state: WatchState
    since: datetime | None
    docker: DockerStatus
    # Only states with at least one instance.
    counts: dict[InstanceState, int]


class ServerCountsRead(BaseModel):
    """A workspace's watched servers (jump hosts aren't watched), by how they're doing."""

    model_config = _READ

    total: int
    up: int
    not_tested: int
    unreachable: int
    # Unreachable, sign-in failed, or host key changed.
    trouble: int
    # Connected, but Docker can't be used, so its instances can't be seen.
    docker_problem: int


class GpuTotalsRead(BaseModel):
    model_config = _READ

    count: int
    # Over the GPUs that report both; None when none do.
    memory_used_mib: float | None
    memory_total_mib: float | None


class WorkspaceOverviewRead(BaseModel):
    """What a workspace's card on the landing page needs."""

    model_config = _READ

    workspace_id: int
    servers: ServerCountsRead
    # Only states with at least one instance.
    instances: dict[InstanceState, int]
    # None when no server has GPU readings.
    gpus: GpuTotalsRead | None
    # Models of ready instances, once each, sorted.
    models: list[str]


class InstanceHistoryRead(BaseModel):
    model_config = _READ

    name: str
    interval_seconds: float
    points: list[UsagePointRead]
