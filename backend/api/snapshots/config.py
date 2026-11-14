"""A container's launch config: what Docker says about how it was started, reduced to what
`docker run` would need to start it again, with every default and secret value left out.

It's what snapshots compare, store and rebuild the command from. Lists are sorted so Docker
listing the same things in another order is never a change.
"""

from dataclasses import asdict, dataclass, fields
from typing import Any

from api.enums import InstanceSource
from api.snapshots.secrets import mask_args
from api.watch.docker import ImageDefaults
from api.watch.frameworks import Container

# Docker's default /dev/shm size, which `docker run` without --shm-size gives.
DEFAULT_SHM_SIZE = 67108864


@dataclass(frozen=True)
class LaunchConfig:
    image: str
    # None means the image's own entrypoint.
    entrypoint: tuple[str, ...] | None = None
    # Masked: secret flag values are placeholders.
    args: tuple[str, ...] = ()
    # Sorted, "K=V", or "K" for a secret (or a value the server's Docker couldn't separate).
    env: tuple[str, ...] = ()
    # Sorted docker -p values.
    ports: tuple[str, ...] = ()
    network: str | None = None
    ipc: str | None = None
    pid: str | None = None
    # Bytes.
    shm_size: int | None = None
    # The --gpus value.
    gpus: str | None = None
    runtime: str | None = None
    # Sorted -v values.
    volumes: tuple[str, ...] = ()
    restart: str | None = None
    ulimits: tuple[str, ...] = ()
    devices: tuple[str, ...] = ()
    privileged: bool = False
    cap_add: tuple[str, ...] = ()
    cap_drop: tuple[str, ...] = ()
    user: str | None = None
    workdir: str | None = None
    # The compose project, and its config files or else its working dir.
    compose: tuple[str, str] | None = None
    env_values_hidden: bool = False


@dataclass(frozen=True)
class UnitConfig:
    """A systemd unit as `systemctl cat` prints it, already masked. `scope` is the unit's source:
    systemd or systemd-user."""

    text: str
    scope: InstanceSource


Config = LaunchConfig | UnitConfig
_UNIT_SCOPES = (InstanceSource.SYSTEMD, InstanceSource.SYSTEMD_USER)


def _ports(bindings: dict[str, Any] | None) -> tuple[str, ...]:
    ports = []
    for key, hosts in (bindings or {}).items():
        port, _, protocol = key.partition("/")
        container_port = port if protocol in ("", "tcp") else f"{port}/{protocol}"
        for host in hosts or [{}]:
            host_ip = host.get("HostIp") or ""
            host_port = host.get("HostPort") or ""
            if not host_port:
                ports.append(container_port)
                continue
            prefix = "" if host_ip in ("", "0.0.0.0", "::") else f"{host_ip}:"
            ports.append(f"{prefix}{host_port}:{container_port}")
    return tuple(sorted(set(ports)))


def _gpus(device_requests: list[dict[str, Any]] | None) -> str | None:
    ids: list[str] = []
    count = 0
    for request in device_requests or []:
        if request.get("Count") == -1:
            return "all"
        ids.extend(request.get("DeviceIDs") or [])
        count = max(count, request.get("Count") or 0)
    if ids:
        # The CLI parses --gpus as CSV, so a list of devices needs its own double quotes.
        return f'"device={",".join(ids)}"'
    return str(count) if count > 0 else None


def _volumes(mounts: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    volumes = []
    for mount in mounts:
        kind = mount.get("Type")
        if kind not in ("bind", "volume"):
            continue
        source = mount.get("Source") if kind == "bind" else (mount.get("Name") or mount.get("Source"))
        volume = f"{source}:{mount.get('Destination')}"
        volumes.append(volume if mount.get("RW", True) else f"{volume}:ro")
    return tuple(sorted(volumes))


def _restart(policy: dict[str, Any] | None) -> str | None:
    name = (policy or {}).get("Name") or ""
    if name in ("", "no"):
        return None
    retries = (policy or {}).get("MaximumRetryCount") or 0
    return f"{name}:{retries}" if name == "on-failure" and retries else name


def _none_if(value: str | None, *defaults: str) -> str | None:
    return None if not value or value in defaults else value


def launch_config(container: Container, image: ImageDefaults | None) -> LaunchConfig:
    """The launch config of a container, given its image's own settings when known."""
    launch = container.launch
    if launch is None:
        return LaunchConfig(image=container.image)
    host = launch.host
    entrypoint = None
    if image is not None and launch.entrypoint != image.entrypoint:
        entrypoint = tuple(mask_args(launch.entrypoint or ()))
    inherited = image.env if image is not None else frozenset()
    compose = launch.compose
    return LaunchConfig(
        image=container.image,
        entrypoint=entrypoint,
        args=tuple(mask_args(launch.cmd or ())),
        env=tuple(entry for entry in launch.env if entry not in inherited),
        ports=_ports(host.get("port_bindings")),
        network=_none_if(container.network_mode, "default", "bridge"),
        ipc=_none_if(host.get("ipc_mode"), "private", "shareable"),
        pid=_none_if(host.get("pid_mode")),
        shm_size=None if host.get("shm_size") in (None, 0, DEFAULT_SHM_SIZE) else host["shm_size"],
        gpus=_gpus(host.get("device_requests")),
        runtime=_none_if(host.get("runtime"), "runc"),
        volumes=_volumes(launch.mounts),
        restart=_restart(host.get("restart_policy")),
        ulimits=tuple(sorted(f"{u['Name']}={u['Soft']}:{u['Hard']}" for u in host.get("ulimits") or [])),
        devices=tuple(sorted(
            f"{d['PathOnHost']}:{d['PathInContainer']}:{d['CgroupPermissions']}" for d in host.get("devices") or [])),
        privileged=bool(host.get("privileged")),
        cap_add=tuple(sorted(host.get("cap_add") or ())),
        cap_drop=tuple(sorted(host.get("cap_drop") or ())),
        user=_none_if(launch.user, *([image.user] if image else [])),
        workdir=_none_if(launch.workdir, *([image.workdir] if image else [])),
        compose=(compose["project"], compose["config_files"] or compose["working_dir"]) if compose.get("project") else None,
        env_values_hidden=launch.env_values_hidden,
    )


def config_to_json(config: Config) -> dict[str, Any]:
    if isinstance(config, UnitConfig):
        return {"source": config.scope.value, "text": config.text}
    return asdict(config)


def config_from_json(data: dict[str, Any]) -> Config:
    """The stored form back into a config. A systemd source gives a unit's config; anything else, a
    Docker one, so configs stored before there was a source still read. Unknown keys are ignored and
    missing ones take defaults, so configs stored by an older vservx still read."""
    if data.get("source") in _UNIT_SCOPES:
        return UnitConfig(text=data.get("text") or "", scope=InstanceSource(data["source"]))
    known = {f.name for f in fields(LaunchConfig)}
    return LaunchConfig(**{key: tuple(value) if isinstance(value, list) else value
                           for key, value in data.items() if key in known})
