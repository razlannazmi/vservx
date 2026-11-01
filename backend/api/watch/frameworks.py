"""The shapes every serving framework is read into, and the frameworks vservx knows.

Everything specific to one framework (how its containers look, where it listens, what its
metrics are called) lives in that framework's module. The rest of vservx only sees these shapes.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from typing import Protocol


@dataclass(frozen=True)
class Container:
    """What Docker says about one container."""

    # Without Docker's leading "/".
    name: str
    image: str
    # Path then Args. May hold --api-key, so it's never shown or logged.
    command: list[str] = field(repr=False)
    # Docker's State.Status: running, restarting, paused, exited, dead, created or removing.
    status: str
    exit_code: int | None
    oom_killed: bool
    restart_count: int
    started_at: datetime | None
    finished_at: datetime | None
    network_mode: str
    # Container tcp port -> (host ip, host port).
    published: dict[int, tuple[str, int]]
    # The container's IPs on its networks.
    addresses: list[str]
    # Device ids or uuids, ["all"], or None when Docker doesn't say.
    gpus: list[str] | None
    # Only VLLM_API_KEY and NVIDIA_VISIBLE_DEVICES; nothing else from the environment is kept.
    env: dict[str, str] = field(repr=False)


@dataclass(frozen=True)
class InstanceSpec:
    """What a container's settings say about the instance in it."""

    port: int
    model: str | None
    max_model_len: int | None
    api_key: str | None = field(repr=False)


@dataclass(frozen=True)
class InstanceInfo:
    """What the instance says about itself, read once per container start."""

    version: str | None
    # The served model name.
    model: str | None
    max_model_len: int | None


@dataclass(frozen=True)
class MetricSample:
    """One reading of an instance's metrics. Token and time-to-first-token values are counters."""

    running: float | None
    waiting: float | None
    # 0..1
    kv_cache: float | None
    prompt_tokens: float | None
    generation_tokens: float | None
    ttft_sum: float | None
    ttft_count: float | None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


# GET a path on the instance with these headers.
Get = Callable[[str, Mapping[str, str]], Awaitable[HttpResponse]]


class Framework(Protocol):
    name: str
    health_path: str
    metrics_path: str

    def recognises(self, image: str, command: str) -> bool: ...

    def describe(self, container: Container) -> InstanceSpec: ...

    async def read_info(self, get: Get, spec: InstanceSpec) -> InstanceInfo: ...

    def read_metrics(self, text: str) -> MetricSample: ...


@cache
def _frameworks() -> tuple[Framework, ...]:
    # Imported here because each framework's module imports the shapes above.
    from api.watch.vllm import VLLM

    return (VLLM(),)


def framework_for(image: str, command: str) -> Framework | None:
    """The framework a container runs, judged by its image and command; None for anything else."""
    return next((framework for framework in _frameworks() if framework.recognises(image, command)), None)
