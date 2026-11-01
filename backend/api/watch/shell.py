"""Running commands on a server, and talking HTTP to its instances, over one SSH connection."""

import asyncio
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import asyncssh

from api.watch.frameworks import HttpResponse

HTTP_TIMEOUT = 5.0
# Plenty for the metrics of a busy instance; anything longer is cut short.
MAX_BODY = 8 * 1024 * 1024
CANT_REACH_PORT = "vservx can't reach vLLM's port: SSH port forwarding is off and curl isn't installed"


@dataclass(frozen=True)
class CommandResult:
    # -1 when the command ended without one (a signal).
    exit_status: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    async def run(self, command: str, stdin: str | None = None) -> CommandResult: ...


class PortClosed(Exception):
    """Nothing is accepting connections on the instance's port."""


class CantReachPort(Exception):
    """vservx has no way to reach the port; str(exc) is the message for people."""


def _response(raw: bytes) -> HttpResponse:
    head, _, body = raw.partition(b"\r\n\r\n")
    parts = head.split(b"\r\n", 1)[0].split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return HttpResponse(status, body.decode("utf-8", "replace"))


class Shell:
    def __init__(self, connection: asyncssh.SSHClientConnection, timeout: float) -> None:
        self._connection = connection
        self._timeout = timeout
        # Port forwarding is tried first; False once sshd refused it (AllowTcpForwarding no).
        self._forwarding = True

    async def run(self, command: str, stdin: str | None = None) -> CommandResult:
        completed = await asyncio.wait_for(self._connection.run(command, input=stdin, check=False), self._timeout)
        return CommandResult(
            exit_status=completed.exit_status if completed.exit_status is not None else -1,
            stdout=str(completed.stdout or ""),
            stderr=str(completed.stderr or ""),
        )

    async def http_get(self, host: str, port: int, path: str, headers: Mapping[str, str] | None = None) -> HttpResponse:
        """GET from the server's point of view, so the instance's port never needs exposing."""
        headers = dict(headers or {})
        if self._forwarding:
            try:
                return await asyncio.wait_for(self._forwarded_get(host, port, path, headers), HTTP_TIMEOUT)
            except asyncssh.ChannelOpenError as exc:
                if exc.code != asyncssh.OPEN_ADMINISTRATIVELY_PROHIBITED:
                    raise PortClosed(exc.reason) from None
                self._forwarding = False
        return await self._curl_get(host, port, path, headers)

    async def _forwarded_get(self, host: str, port: int, path: str, headers: dict[str, str]) -> HttpResponse:
        reader, writer = await self._connection.open_connection(host, port)
        try:
            # HTTP/1.0: the answer ends when the connection closes, never chunked.
            lines = [f"GET {path} HTTP/1.0", f"Host: {host}:{port}", *(f"{k}: {v}" for k, v in headers.items()), "", ""]
            writer.write("\r\n".join(lines).encode())
            chunks: list[bytes] = []
            size = 0
            while size < MAX_BODY:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        finally:
            writer.close()
        return _response(b"".join(chunks))

    async def _curl_get(self, host: str, port: int, path: str, headers: dict[str, str]) -> HttpResponse:
        command = ["curl", "-sS", "--max-time", f"{HTTP_TIMEOUT:g}", "-o", "-", "-w", "\\n%{http_code}"]
        # Headers (an API key) go on stdin, never on the command line where `ps` would show them.
        if headers:
            command += ["-H", "@-"]
        command.append(f"http://{host}:{port}{path}")
        stdin = "".join(f"{k}: {v}\n" for k, v in headers.items()) if headers else None
        result = await self.run(" ".join(map(shlex.quote, command)), stdin)
        if result.exit_status == 0:
            body, _, status = result.stdout.rpartition("\n")
            return HttpResponse(int(status) if status.isdigit() else 0, body)
        if result.exit_status == 127:
            raise CantReachPort(CANT_REACH_PORT)
        if result.exit_status == 28:
            raise TimeoutError(f"No answer from {host}:{port} within {HTTP_TIMEOUT:g} seconds")
        raise PortClosed(result.stderr.strip())
