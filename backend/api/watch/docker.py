"""Asking Docker about containers (through sudo when the server needs it), reading its answers,
and where a server reaches a container's port."""

import json
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from api.enums import DockerStatus
from api.watch.frameworks import Container
from api.watch.shell import CommandResult, CommandRunner

PS_ARGS = "ps -a --no-trunc --format '{{json .}}'"

NEEDS_SUDO_PASSWORD = "Docker on this server needs sudo. Add the sudo password in the server's settings."
SUDO_PASSWORD_REJECTED = "The sudo password was rejected. Check it in the server's settings."
SUDO_NEEDS_TTY = "sudo on this server needs a terminal (requiretty), so vservx can't use it."
DOCKER_MISSING = "Docker isn't installed on this server."

# The password goes on stdin (-S) with no prompt (-p ''), never on the command line.
_SUDO_WITH_PASSWORD = "sudo -S -p '' docker"

# Only the fields vservx needs, and from the environment only the two keys it keeps, so
# HF_TOKEN and the like never leave the server. Docker's templates have no "in" test, hence the
# two comparisons; the trailing null keeps the list valid JSON after the last comma.
INSPECT_FORMAT = (
    '{"name":{{json .Name}},"image":{{json .Config.Image}},"path":{{json .Path}},"args":{{json .Args}},'
    '"state":{{json .State}},"restart_count":{{json .RestartCount}},'
    '"network_mode":{{json .HostConfig.NetworkMode}},"ports":{{json .NetworkSettings.Ports}},'
    '"networks":{{json .NetworkSettings.Networks}},"device_requests":{{json .HostConfig.DeviceRequests}},'
    '"env":[{{range .Config.Env}}{{if or (eq (index (split . "=") 0) "VLLM_API_KEY") '
    '(eq (index (split . "=") 0) "NVIDIA_VISIBLE_DEVICES")}}{{json .}},{{end}}{{end}}null]}'
)

# A second guard behind the template: anything else in the environment is dropped on arrival.
KEPT_ENV = frozenset({"VLLM_API_KEY", "NVIDIA_VISIBLE_DEVICES"})

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


def inspect_args(names: list[str]) -> str:
    return " ".join(["inspect", "--format", shlex.quote(INSPECT_FORMAT), *map(shlex.quote, names)])


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


def parse_inspect(stdout: str) -> list[Container]:
    """`docker inspect --format INSPECT_FORMAT`, one container per line, in output order."""
    containers = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        state = row.get("state") or {}
        env = {}
        for item in row.get("env") or []:
            key, sep, value = (item or "").partition("=")
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
        ))
    return containers


def target(container: Container, port: int) -> tuple[str, int]:
    """Where the server itself reaches the container's port."""
    if container.network_mode == "host":
        return ("127.0.0.1", port)
    if binding := container.published.get(port):
        host, host_port = binding
        return ("127.0.0.1" if host in ("", "0.0.0.0", "::") else host, host_port)
    if container.addresses:
        return (container.addresses[0], port)
    return ("127.0.0.1", port)
