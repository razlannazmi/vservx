"""What vservx has seen on the servers it watches. Read from memory; nothing here is stored."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import DockerStatus, InstanceState, WatchState

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

    # The container's name: an instance's identity on its server.
    name: str
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


class InstanceHistoryRead(BaseModel):
    model_config = _READ

    name: str
    interval_seconds: float
    points: list[UsagePointRead]
