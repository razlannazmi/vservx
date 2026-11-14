"""A workspace at a glance: its watched servers' views added up, for its landing-page card."""

from collections import Counter
from collections.abc import Iterable

from api.enums import DockerStatus, InstanceState, SystemdStatus, WatchState
from api.schemas.watch import GpuTotalsRead, ServerCountsRead, ServerWatchRead, WorkspaceOverviewRead
from api.watch.docker import DOCKER_MISSING

# Connected, but Docker can't be used, so nothing on the server can be seen.
_DOCKER_PROBLEMS = {DockerStatus.NEEDS_SUDO_PASSWORD, DockerStatus.SUDO_PASSWORD_REJECTED,
                    DockerStatus.SUDO_NEEDS_TTY, DockerStatus.UNAVAILABLE}
_TROUBLE = {WatchState.UNREACHABLE, WatchState.SIGN_IN_FAILED, WatchState.HOST_KEY_CHANGED}


def _docker_problem(view: ServerWatchRead) -> bool:
    if view.state is not WatchState.CONNECTED or view.docker not in _DOCKER_PROBLEMS:
        return False
    # No Docker at all, but its systemd services are read: nothing on it is hidden.
    return not (view.systemd is SystemdStatus.AVAILABLE and view.docker_message == DOCKER_MISSING)


def workspace_overview(workspace_id: int, views: Iterable[ServerWatchRead]) -> WorkspaceOverviewRead:
    views = list(views)
    states = Counter(view.state for view in views)
    docker_problem = sum(1 for view in views if _docker_problem(view))
    servers = ServerCountsRead(
        total=len(views),
        up=states[WatchState.CONNECTED] - docker_problem,
        not_tested=states[WatchState.NOT_TESTED],
        unreachable=states[WatchState.UNREACHABLE],
        trouble=sum(states[state] for state in _TROUBLE),
        docker_problem=docker_problem,
    )
    # A server that's down keeps what it last saw in its view; only connected ones are current.
    live = [view for view in views if view.state is WatchState.CONNECTED]
    instances = [instance for view in live for instance in view.instances]
    models = sorted({instance.model for instance in instances if instance.state is InstanceState.READY and instance.model})
    return WorkspaceOverviewRead(
        workspace_id=workspace_id,
        servers=servers,
        instances=dict(Counter(instance.state for instance in instances)),
        gpus=_gpu_totals(live),
        models=models,
    )


def _gpu_totals(views: list[ServerWatchRead]) -> GpuTotalsRead | None:
    gpus = [gpu for view in views for gpu in view.gpus or []]
    if not gpus:
        return None
    measured = [gpu for gpu in gpus if gpu.memory_used_mib is not None and gpu.memory_total_mib is not None]
    if not measured:
        return GpuTotalsRead(count=len(gpus), memory_used_mib=None, memory_total_mib=None)
    return GpuTotalsRead(count=len(gpus), memory_used_mib=sum(gpu.memory_used_mib for gpu in measured),
                         memory_total_mib=sum(gpu.memory_total_mib for gpu in measured))
