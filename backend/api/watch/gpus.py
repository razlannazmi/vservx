"""A server's GPUs, from nvidia-smi, and which containers and services use them."""

from dataclasses import dataclass

from api.watch.frameworks import Container

GPU_COMMAND = ("nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu "
               "--format=csv,noheader,nounits")
# The processes computing on each GPU, to match a systemd service's processes to its GPUs.
COMPUTE_APPS_COMMAND = "nvidia-smi --query-compute-apps=pid,gpu_uuid --format=csv,noheader"


@dataclass(frozen=True)
class Gpu:
    index: int
    uuid: str
    name: str
    utilization: float | None
    # MiB
    memory_used: float | None
    memory_total: float | None
    temperature: float | None


def _number(text: str) -> float | None:
    # nvidia-smi says "[N/A]" or "[Not Supported]" for what a GPU doesn't report.
    try:
        return float(text)
    except ValueError:
        return None


def parse_gpus(stdout: str) -> list[Gpu]:
    gpus = []
    for line in stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 7 or not fields[0].isdigit():
            continue
        index, uuid, name, utilization, used, total, temperature = fields[:7]
        gpus.append(Gpu(index=int(index), uuid=uuid, name=name, utilization=_number(utilization),
                        memory_used=_number(used), memory_total=_number(total), temperature=_number(temperature)))
    return gpus


def parse_compute_apps(stdout: str) -> dict[int, str]:
    """COMPUTE_APPS_COMMAND's answer: PID -> UUID of the GPU it computes on."""
    apps = {}
    for line in stdout.splitlines():
        pid, sep, uuid = (part.strip() for part in line.partition(","))
        if sep and pid.isdigit() and uuid:
            apps[int(pid)] = uuid
    return apps


def gpu_users(gpus: list[Gpu], containers: list[Container]) -> dict[int, list[str]]:
    """GPU index -> names of the running containers (Docker's, or systemd services) that use it."""
    users: dict[int, list[str]] = {}
    for container in containers:
        if container.status != "running" or not container.gpus:
            continue
        for gpu in gpus:
            if "all" in container.gpus or str(gpu.index) in container.gpus or gpu.uuid in container.gpus:
                users.setdefault(gpu.index, []).append(container.name)
    return users
