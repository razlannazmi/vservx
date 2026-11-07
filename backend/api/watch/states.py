"""An instance's state, from its container and from asking it for its health."""

from enum import StrEnum

from api.enums import InstanceState
from api.watch.frameworks import Container


class Probe(StrEnum):
    """What asking a running instance for its health got."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    PORT_CLOSED = "port_closed"
    # vservx has no way to reach the port at all.
    CANT_REACH = "cant_reach"


def instance_state(container: Container, probe: Probe | None, ever_ready: bool) -> InstanceState:
    """`ever_ready`: the instance has been healthy since its container last started. Until then,
    anything but healthy is Starting, whatever the framework does with its port while loading."""
    match container.status:
        case "running":
            if probe is Probe.HEALTHY:
                return InstanceState.READY
            if probe is Probe.CANT_REACH:
                return InstanceState.UNREACHABLE
            return InstanceState.NOT_RESPONDING if ever_ready else InstanceState.STARTING
        case "restarting":
            return InstanceState.RESTARTING
        case "paused":
            return InstanceState.PAUSED
        case "exited":
            stopped_cleanly = not container.oom_killed and container.exit_code in (0, None)
            return InstanceState.STOPPED if stopped_cleanly else InstanceState.CRASHED
        case "dead":
            return InstanceState.CRASHED
        case _:
            return InstanceState.STOPPED
