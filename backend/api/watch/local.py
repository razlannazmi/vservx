"""Watching the machine vservx runs on, without SSH: what keeps it from being watched, and a runner with
the same two operations as the SSH Shell."""

import asyncio
import contextlib
import os
import shutil
import socket
import sys
from collections.abc import Mapping
from pathlib import Path

from api.watch.frameworks import HttpResponse
from api.watch.shell import HTTP_TIMEOUT, CommandResult, PortClosed, exchange, timeout_message

UNAVAILABLE = "This machine is only available when vservx runs on Linux."


def unavailable_reason() -> str | None:
    """Why this machine can't be watched, or None when it can."""
    return None if sys.platform.startswith("linux") else UNAVAILABLE


def machine_hostname() -> str:
    return socket.gethostname()


def in_container(root: Path = Path("/")) -> bool:
    """True when vservx itself runs inside a container."""
    return (root / ".dockerenv").exists() or (root / "run/.containerenv").exists()


def container_hints(root: Path = Path("/")) -> dict[str, str]:
    """For each part of the host that vservx can't see from inside its container, what to change.
    Empty outside a container. Keys: docker, systemd, pid, gpus."""
    if not in_container(root):
        return {}
    hints = {}
    if not os.environ.get("DOCKER_HOST") and not (root / "var/run/docker.sock").exists():
        hints["docker"] = "vservx runs in a container and can't reach Docker: start the socket proxy, or set DOCKER_HOST."
    if not (root / "run/dbus/system_bus_socket").exists() or not (root / "run/systemd/system").exists():
        hints["systemd"] = ("vservx runs in a container without the host's systemd mounts "
                            "(/run/dbus/system_bus_socket, /run/systemd/system), so systemd services can't be read.")
    try:
        init = (root / "proc/1/comm").read_text().strip()
    except OSError:
        init = ""
    if init not in ("systemd", "init"):
        hints["pid"] = ("vservx runs in a container without the host's PID namespace (pid: host), "
                        "so GPUs can't be matched to systemd services.")
    if shutil.which("nvidia-smi") is None:
        hints["gpus"] = "vservx runs in a container without GPUs: start it with the NVIDIA runtime to see them."
    return hints


# Seconds to wait for a killed command to be reaped before giving up on it.
REAP_TIMEOUT = 1.0


class LocalShell:
    """Runs commands through /bin/sh and reads ports on this machine, with the same two operations as Shell."""

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout

    async def run(self, command: str, stdin: str | None = None) -> CommandResult:
        process = await asyncio.create_subprocess_exec(
            "/bin/sh", "-c", command,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin.encode() if stdin is not None else None), self._timeout)
        except BaseException:
            # A timeout, or the watch being cancelled: don't leave the command running.
            if process.returncode is None:
                process.kill()
                # Bounded: wait() also waits for pipes an orphaned child (sudo's docker) may still hold,
                # and a child stuck in the kernel ignores the kill.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), REAP_TIMEOUT)
            raise
        return CommandResult(
            # Negative when a signal ended it.
            exit_status=process.returncode if process.returncode is not None and process.returncode >= 0 else -1,
            stdout=stdout.decode("utf-8", "replace"),
            stderr=stderr.decode("utf-8", "replace"),
        )

    async def http_get(self, host: str, port: int, path: str, headers: Mapping[str, str] | None = None) -> HttpResponse:
        received = bytearray()

        async def get() -> HttpResponse:
            reader, writer = await asyncio.open_connection(host, port)
            return await exchange(reader, writer, host, port, path, dict(headers or {}), received)

        try:
            return await asyncio.wait_for(get(), HTTP_TIMEOUT)
        except TimeoutError:
            raise TimeoutError(timeout_message(host, port, path, received)) from None
        except OSError as exc:
            raise PortClosed(str(exc)) from None
