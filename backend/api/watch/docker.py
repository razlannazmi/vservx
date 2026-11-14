"""Asking Docker about containers (through sudo when the server needs it), reading its answers,
and where a server reaches a container's port."""

import json
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from api.enums import DockerStatus
from api.snapshots.secrets import SECRET_NAME_PARTS, SECRET_NAME_SUFFIXES, is_secret_env
from api.watch.frameworks import Container, RawLaunch
from api.watch.shell import CommandResult, CommandRunner

PS_ARGS = "ps -a --no-trunc --format '{{json .}}'"

NEEDS_SUDO_PASSWORD = "Docker on this server needs sudo. Add the sudo password in the server's settings."
SUDO_PASSWORD_REJECTED = "The sudo password was rejected. Check it in the server's settings."
SUDO_NEEDS_TTY = "sudo on this server needs a terminal (requiretty), so vservx can't use it."
DOCKER_MISSING = "Docker isn't installed on this server."

# The password goes on stdin (-S) with no prompt (-p ''), never on the command line.
_SUDO_WITH_PASSWORD = "sudo -S -p '' docker"

# The two env vars watching keeps with their values. VLLM_API_KEY's value is held in memory only,
# to call /v1/models and to fingerprint it.
KEPT_ENV = frozenset({"VLLM_API_KEY", "NVIDIA_VISIBLE_DEVICES"})
_KEPT_ORDER = ("VLLM_API_KEY", "NVIDIA_VISIBLE_DEVICES")

# The HostConfig fields snapshots use, one by one. Never the whole HostConfig: LogConfig options can
# hold tokens.
_HOST_FIELDS = (
    ("port_bindings", "PortBindings"), ("ipc_mode", "IpcMode"), ("pid_mode", "PidMode"), ("shm_size", "ShmSize"),
    ("restart_policy", "RestartPolicy"), ("runtime", "Runtime"), ("ulimits", "Ulimits"), ("devices", "Devices"),
    ("privileged", "Privileged"), ("cap_add", "CapAdd"), ("cap_drop", "CapDrop"),
)
_COMPOSE_LABELS = (
    ("project", "com.docker.compose.project"),
    ("working_dir", "com.docker.compose.project.working_dir"),
    ("config_files", "com.docker.compose.project.config_files"),
)


def _env_template(source: str, kept: tuple[str, ...], values: bool) -> str:
    """A JSON list of the env entries in `source`, filtered on the server. Kept names go out whole.
    With `values`, a secret-looking name goes out as its name only and every other entry whole;
    without, every other entry goes out as its name only (for Dockers that can't run the filter).
    The secret test is generated from the same constants as is_secret_env, so the two can't drift.
    Docker's templates have no "contains" or "ends with": a name contains X when splitting on X gives
    more than one part, and ends in X when the last part of that split is empty. The trailing null
    keeps the list valid JSON after the last comma."""
    name = '{{$k := index (split . "=") 0}}'
    if values:
        suffix_vars = "".join(
            f'{{{{$s{i} := ""}}}}{{{{range split $u "{suffix}"}}}}{{{{$s{i} = .}}}}{{{{end}}}}'
            for i, suffix in enumerate(SECRET_NAME_SUFFIXES))
        tests = [f'(gt (len (split $u "{part}")) 1)' for part in SECRET_NAME_PARTS]
        tests += [f'(eq $s{i} "")' for i in range(len(SECRET_NAME_SUFFIXES))]
        other = ('{{$u := upper $k}}' + suffix_vars
                 + '{{if or ' + " ".join(tests) + '}}{{json $k}},{{else}}{{json .}},{{end}}')
    else:
        other = '{{json $k}},'
    if kept:
        is_kept = "or " + " ".join(f'(eq $k "{n}")' for n in kept)
        body = name + '{{if ' + is_kept + '}}{{json .}},{{else}}' + other + '{{end}}'
    else:
        body = name + other
    return '{{range ' + source + '}}' + body + '{{end}}null'


def inspect_format(env_values: bool = True) -> str:
    """Only the fields vservx needs. From the environment: the two kept names in full, then other
    entries filtered by _env_template, so secret values never leave the server."""
    host = ",".join(f'"{key}":{{{{json .HostConfig.{field}}}}}' for key, field in _HOST_FIELDS)
    compose = ",".join(f'"{key}":{{{{json (index .Config.Labels "{label}")}}}}' for key, label in _COMPOSE_LABELS)
    return (
        '{"id":{{json .Id}},"created":{{json .Created}},"image_id":{{json .Image}},'
        '"name":{{json .Name}},"image":{{json .Config.Image}},"path":{{json .Path}},"args":{{json .Args}},'
        '"entrypoint":{{json .Config.Entrypoint}},"cmd":{{json .Config.Cmd}},'
        '"user":{{json .Config.User}},"workdir":{{json .Config.WorkingDir}},'
        '"state":{{json .State}},"restart_count":{{json .RestartCount}},'
        '"network_mode":{{json .HostConfig.NetworkMode}},"ports":{{json .NetworkSettings.Ports}},'
        '"networks":{{json .NetworkSettings.Networks}},"device_requests":{{json .HostConfig.DeviceRequests}},'
        '"mounts":{{json .Mounts}},"host":{' + host + '},"compose":{' + compose + '},'
        '"env":[' + _env_template(".Config.Env", _KEPT_ORDER, env_values) + ']}'
    )


INSPECT_FORMAT = inspect_format()


def image_format(env_values: bool = True) -> str:
    """An image's own settings, to tell what a container inherited. No names are kept whole here:
    an image's VLLM_API_KEY is only ever compared by name."""
    return (
        '{"id":{{json .Id}},"entrypoint":{{json .Config.Entrypoint}},"cmd":{{json .Config.Cmd}},'
        '"user":{{json .Config.User}},"workdir":{{json .Config.WorkingDir}},'
        '"env":[' + _env_template(".Config.Env", (), env_values) + ']}'
    )


IMAGE_FORMAT = image_format()

# Docker's "never" time, and nanoseconds, which datetime can't hold.
_ZERO_TIME = "0001-01-01"
_PAST_MICROSECONDS = re.compile(r"(\.\d{6})\d+")


@dataclass(frozen=True)
class DockerAccess:
    status: DockerStatus
    # How docker is run: "docker", "sudo -n docker" or the sudo-with-password form. None when it can't be.
    prefix: str | None
    # What to tell people, for every status but PLAIN and SUDO.
    message: str | None


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "no error message")


def _cant(stderr: str) -> DockerAccess:
    return DockerAccess(DockerStatus.UNAVAILABLE, None, f"Can't run docker: {_first_line(stderr)}")


async def probe_docker(runner: CommandRunner, sudo_password: str | None) -> tuple[DockerAccess, CommandResult | None]:
    """Find how docker runs here: plainly, through sudo without a password, or through sudo with
    one. Probing is `docker ps` itself, so a successful probe's output is returned for use."""
    plain = await runner.run(f"docker {PS_ARGS}")
    if plain.exit_status == 0:
        return DockerAccess(DockerStatus.PLAIN, "docker", None), plain
    if plain.exit_status == 127 or "not found" in plain.stderr:
        return DockerAccess(DockerStatus.UNAVAILABLE, None, DOCKER_MISSING), None
    if "permission denied" not in plain.stderr.lower():
        return _cant(plain.stderr), None

    no_password = await runner.run(f"sudo -n docker {PS_ARGS}")
    if no_password.exit_status == 0:
        return DockerAccess(DockerStatus.SUDO, "sudo -n docker", None), no_password
    if "tty" in no_password.stderr:
        return DockerAccess(DockerStatus.SUDO_NEEDS_TTY, None, SUDO_NEEDS_TTY), None
    if "password is required" not in no_password.stderr:
        return _cant(no_password.stderr), None
    if sudo_password is None:
        return DockerAccess(DockerStatus.NEEDS_SUDO_PASSWORD, None, NEEDS_SUDO_PASSWORD), None

    with_password = await runner.run(f"{_SUDO_WITH_PASSWORD} {PS_ARGS}", sudo_password + "\n")
    if with_password.exit_status == 0:
        return DockerAccess(DockerStatus.SUDO, _SUDO_WITH_PASSWORD, None), with_password
    # Not tried again: repeated wrong sudo passwords can lock the account.
    if "incorrect password" in with_password.stderr or "try again" in with_password.stderr:
        return DockerAccess(DockerStatus.SUDO_PASSWORD_REJECTED, None, SUDO_PASSWORD_REJECTED), None
    if "tty" in with_password.stderr:
        return DockerAccess(DockerStatus.SUDO_NEEDS_TTY, None, SUDO_NEEDS_TTY), None
    return _cant(with_password.stderr), None


async def run_docker(runner: CommandRunner, access: DockerAccess, args: str, sudo_password: str | None) -> CommandResult:
    """Run `docker <args>` the way the probe found works."""
    stdin = sudo_password + "\n" if access.prefix == _SUDO_WITH_PASSWORD and sudo_password else None
    return await runner.run(f"{access.prefix} {args}", stdin)


@dataclass(frozen=True)
class PsEntry:
    name: str
    image: str
    command: str


def parse_ps(stdout: str) -> list[PsEntry]:
    """`docker ps --format '{{json .}}'`, one container per line."""
    entries = []
    for line in stdout.splitlines():
        if line.strip():
            row = json.loads(line)
            entries.append(PsEntry(name=row["Names"].split(",")[0], image=row.get("Image") or "",
                                   command=row.get("Command") or ""))
    return entries


def inspect_args(names: list[str], env_values: bool = True) -> str:
    return " ".join(["inspect", "--format", shlex.quote(inspect_format(env_values)), *map(shlex.quote, names)])


def image_inspect_args(image_ids: list[str], env_values: bool = True) -> str:
    return " ".join(["inspect", "--type", "image", "--format", shlex.quote(image_format(env_values)),
                     *map(shlex.quote, image_ids)])


def is_template_error(result: CommandResult) -> bool:
    """Docker refused the --format template, as an old Docker does with functions it lacks."""
    return result.exit_status != 0 and "template" in result.stderr.lower()


def _guarded_env(entry: str) -> str:
    """The second guard behind the template: a secret-looking entry keeps only its name."""
    key, sep, _ = entry.partition("=")
    return key if not sep or is_secret_env(key) else entry


def _words(value: list[str] | None) -> tuple[str, ...] | None:
    return None if value is None else tuple(value)


@dataclass(frozen=True)
class ImageDefaults:
    """An image's own settings, which a container inherits unless it sets its own."""

    entrypoint: tuple[str, ...] | None
    cmd: tuple[str, ...] | None
    # "K=V", or "K" for a secret-looking name.
    env: frozenset[str]
    user: str
    workdir: str


def parse_image_inspect(stdout: str) -> dict[str, ImageDefaults]:
    """`docker inspect --type image --format IMAGE_FORMAT`, one image per line, by image ID."""
    images = {}
    for line in stdout.splitlines():
        if line.strip():
            row = json.loads(line)
            images[row["id"]] = ImageDefaults(
                entrypoint=_words(row.get("entrypoint")), cmd=_words(row.get("cmd")),
                env=frozenset(_guarded_env(item) for item in row.get("env") or [] if item is not None),
                user=row.get("user") or "", workdir=row.get("workdir") or "",
            )
    return images


def _time(text: str | None) -> datetime | None:
    if not text or text.startswith(_ZERO_TIME):
        return None
    return datetime.fromisoformat(_PAST_MICROSECONDS.sub(r"\1", text).replace("Z", "+00:00"))


def _published(ports: dict[str, Any] | None) -> dict[int, tuple[str, int]]:
    published = {}
    for key, bindings in (ports or {}).items():
        port, _, protocol = key.partition("/")
        if protocol == "tcp" and bindings:
            published[int(port)] = (bindings[0].get("HostIp") or "", int(bindings[0]["HostPort"]))
    return published


def _gpus(device_requests: list[dict[str, Any]] | None, env: dict[str, str]) -> list[str] | None:
    ids: list[str] = []
    for request in device_requests or []:
        if request.get("Count") == -1:
            return ["all"]
        ids.extend(request.get("DeviceIDs") or [])
    if ids:
        return ids
    visible = env.get("NVIDIA_VISIBLE_DEVICES")
    if visible is None:
        return None
    if visible == "all":
        return ["all"]
    return [part.strip() for part in visible.split(",") if part.strip() not in ("", "void", "none")]


def _launch(row: dict[str, Any], entries: list[str], env_values_hidden: bool) -> RawLaunch:
    compose = row.get("compose") or {}
    return RawLaunch(
        entrypoint=_words(row.get("entrypoint")),
        cmd=_words(row.get("cmd")),
        env=tuple(sorted(_guarded_env(entry) for entry in entries)),
        # GPUs come from DeviceRequests, read for watching too, kept beside the other HostConfig fields.
        host=(row.get("host") or {}) | {"device_requests": row.get("device_requests")},
        mounts=tuple(row.get("mounts") or ()),
        user=row.get("user") or "",
        workdir=row.get("workdir") or "",
        compose={key: compose.get(key) or "" for key in ("project", "working_dir", "config_files")},
        env_values_hidden=env_values_hidden,
    )


def parse_inspect(stdout: str, env_values_hidden: bool = False) -> list[Container]:
    """`docker inspect --format INSPECT_FORMAT`, one container per line, in output order.
    Each entry is split at its first "=" only, since values can hold "=" too."""
    containers = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        state = row.get("state") or {}
        entries = [item for item in row.get("env") or [] if item is not None]
        env = {}
        for item in entries:
            key, sep, value = item.partition("=")
            if sep and key in KEPT_ENV:
                env[key] = value
        networks = (row.get("networks") or {}).values()
        containers.append(Container(
            name=row["name"].lstrip("/"),
            image=row.get("image") or "",
            command=[word for word in [row.get("path"), *(row.get("args") or [])] if word],
            status=state.get("Status") or "",
            exit_code=state.get("ExitCode"),
            oom_killed=bool(state.get("OOMKilled")),
            restart_count=row.get("restart_count") or 0,
            started_at=_time(state.get("StartedAt")),
            finished_at=_time(state.get("FinishedAt")),
            network_mode=row.get("network_mode") or "",
            published=_published(row.get("ports")),
            addresses=[network["IPAddress"] for network in networks if network and network.get("IPAddress")],
            gpus=_gpus(row.get("device_requests"), env),
            env=env,
            id=row.get("id") or "",
            created_at=_time(row.get("created")),
            image_id=row.get("image_id") or "",
            launch=_launch(row, entries, env_values_hidden),
        ))
    return containers


def target(container: Container, port: int, bind_host: str | None = None) -> tuple[str, int]:
    """Where the server itself reaches the container's port. With host networking, `bind_host` is
    the address the instance was told to bind, when that's a specific one."""
    if container.network_mode == "host":
        return ("127.0.0.1" if bind_host in (None, "", "0.0.0.0", "::") else bind_host, port)
    if binding := container.published.get(port):
        host, host_port = binding
        return ("127.0.0.1" if host in ("", "0.0.0.0", "::") else host, host_port)
    if container.addresses:
        return (container.addresses[0], port)
    return ("127.0.0.1", port)
