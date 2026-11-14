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


class ServerShell(Protocol):
    """What watching a server needs: run a command there, and GET from a port on it."""

    async def run(self, command: str, stdin: str | None = None) -> CommandResult: ...

    async def http_get(
        self, host: str, port: int, path: str, headers: Mapping[str, str] | None = None
    ) -> HttpResponse: ...


class PortClosed(Exception):
    """Nothing is accepting connections on the instance's port."""


class CantReachPort(Exception):
    """vservx has no way to reach the port; str(exc) is the message for people."""


def url_host(host: str) -> str:
    """The host as a URL or a Host header writes it: an IPv6 literal (vLLM's --host ::1) in brackets, once."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _fields(head: bytes) -> dict[bytes, bytes]:
    """The header fields, by lowercase name."""
    fields = {}
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        fields[name.strip().lower()] = value.strip()
    return fields


def _chunked(fields: dict[bytes, bytes]) -> bool:
    # uvicorn with httptools chunks an answer that has no length, even to an HTTP/1.0 request.
    return b"chunked" in fields.get(b"transfer-encoding", b"").lower()


def _dechunk(body: bytes) -> bytes | None:
    """A chunked body's content, or None until its last (zero-size) chunk is in."""
    content = bytearray()
    at = 0
    while (line_end := body.find(b"\r\n", at)) != -1:
        size_text = body[at:line_end].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            return None
        if size == 0:
            return bytes(content)
        start = line_end + 2
        if len(body) < start + size + 2:
            return None
        content += body[start:start + size]
        at = start + size + 2
    return None


class _AnswerProgress:
    """Whether the whole answer is in yet, asked again after every read: the headers, then all of a
    Content-Length body or every chunk. Without either, the answer ends only when the connection
    closes. Each call looks only at what's new since the last, so an answer that arrives in many
    reads costs about as much as one that arrives in a single read."""

    def __init__(self) -> None:
        # How far the end of the headers has been looked for.
        self._searched = 0
        self._body_start: int | None = None
        self._chunked = False
        self._length: int | None = None
        # Where the next chunk's size line starts.
        self._next_chunk = 0

    def complete(self, raw: bytearray) -> bool:
        if self._body_start is None:
            # The blank line can straddle two reads, so look again from just before the last search ended.
            head_end = raw.find(b"\r\n\r\n", max(0, self._searched - 3))
            self._searched = len(raw)
            if head_end == -1:
                return False
            fields = _fields(bytes(raw[:head_end]))
            self._body_start = self._next_chunk = head_end + 4
            self._chunked = _chunked(fields)
            length = fields.get(b"content-length", b"")
            self._length = int(length) if length.isdigit() else None
        if self._chunked:
            return self._last_chunk_in(raw)
        return self._length is not None and len(raw) - self._body_start >= self._length

    def _last_chunk_in(self, raw: bytearray) -> bool:
        """Step over every chunk that's wholly in; True once the last (zero-size) one is reached."""
        while (line_end := raw.find(b"\r\n", self._next_chunk)) != -1:
            try:
                size = int(raw[self._next_chunk:line_end].split(b";", 1)[0].strip(), 16)
            except ValueError:
                return False
            if size == 0:
                return True
            chunk_end = line_end + 2 + size + 2
            if len(raw) < chunk_end:
                return False
            self._next_chunk = chunk_end
        return False


def _response(raw: bytes) -> HttpResponse:
    head, _, body = raw.partition(b"\r\n\r\n")
    parts = head.split(b"\r\n", 1)[0].split()
    status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if _chunked(_fields(head)):
        body = _dechunk(body) or b""
    return HttpResponse(status, body.decode("utf-8", "replace"))


async def exchange(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int, path: str,
    headers: Mapping[str, str], received: bytearray,
) -> HttpResponse:
    """Send a GET over an open connection and read the answer into `received` (so a caller that
    times out can say what arrived). Closes the writer."""
    try:
        # The answer ends after Content-Length bytes, after its last chunk, or when the connection
        # closes. Some servers (or what's between them and sshd) keep it open after a complete
        # answer, so don't wait for the close once the answer says it's all in.
        lines = [f"GET {path} HTTP/1.0", f"Host: {url_host(host)}:{port}", *(f"{k}: {v}" for k, v in headers.items()),
                 "", ""]
        writer.write("\r\n".join(lines).encode())
        progress = _AnswerProgress()
        while len(received) < MAX_BODY:
            chunk = await reader.read(65536)
            if not chunk:
                break
            received += chunk
            if progress.complete(received):
                break
    finally:
        writer.close()
    return _response(bytes(received))


def timeout_message(host: str, port: int, path: str, received: bytearray) -> str:
    """Whether an answer arrived tells "never answered" from "answered, but never ended"."""
    first = bytes(received).split(b"\r\n", 1)[0].decode("latin-1")
    arrived = f"{len(received)} bytes arrived, starting {first!r}" if received else "nothing arrived"
    return f"GET {path} on {host}:{port} didn't end within {HTTP_TIMEOUT:g} s; {arrived}"


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
            received = bytearray()
            try:
                return await asyncio.wait_for(self._forwarded_get(host, port, path, headers, received), HTTP_TIMEOUT)
            except asyncssh.ChannelOpenError as exc:
                if exc.code != asyncssh.OPEN_ADMINISTRATIVELY_PROHIBITED:
                    raise PortClosed(exc.reason) from None
                self._forwarding = False
            except TimeoutError:
                raise TimeoutError(timeout_message(host, port, path, received)) from None
        return await self._curl_get(host, port, path, headers)

    async def _forwarded_get(
        self, host: str, port: int, path: str, headers: dict[str, str], received: bytearray
    ) -> HttpResponse:
        reader, writer = await self._connection.open_connection(host, port)
        return await exchange(reader, writer, host, port, path, headers, received)

    async def _curl_get(self, host: str, port: int, path: str, headers: dict[str, str]) -> HttpResponse:
        # -g: no URL globbing, which takes an IPv6 host's [brackets] for a range.
        command = ["curl", "-g", "-sS", "--max-time", f"{HTTP_TIMEOUT:g}", "-o", "-", "-w", "\\n%{http_code}"]
        # Headers (an API key) go on stdin, never on the command line where `ps` would show them.
        if headers:
            command += ["-H", "@-"]
        command.append(f"http://{url_host(host)}:{port}{path}")
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
