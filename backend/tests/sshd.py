"""An in-process SSH server for tests. It runs on its own event loop thread so it outlives the
event loop of each asyncio.run() or TestClient request that connects to it."""

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

import asyncssh

# (command, stdin) -> (stdout, stderr, exit status)
Commands = Callable[[str, str], tuple[str, str, int]]


class BackgroundLoop:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join()


class _Server(asyncssh.SSHServer):
    def __init__(self, fake: "FakeSSHD") -> None:
        self._fake = fake

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self._fake.connections.append(conn)

    def begin_auth(self, username: str) -> bool:
        return True  # always require authentication

    def password_auth_supported(self) -> bool:
        return self._fake.password is not None

    def validate_password(self, username: str, password: str) -> bool:
        self._fake.auth_attempts.append("password")
        return password == self._fake.password

    def public_key_auth_supported(self) -> bool:
        return self._fake.client_key is not None

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        self._fake.auth_attempts.append("publickey")
        return self._fake.client_key is not None and key.public_data == self._fake.client_key.public_data

    def connection_requested(self, dest_host: str, dest_port: int, orig_host: str, orig_port: int) -> bool:
        return True  # lets it act as a jump host


class FakeSSHD:
    """Accepts the given password and/or client key and answers any command with its hostname,
    or with `commands` when given. Port forwards go straight through, like a jump host's."""

    def __init__(
        self,
        loop: BackgroundLoop,
        *,
        password: str | None = None,
        client_key: asyncssh.SSHKey | None = None,
        hostname: str = "fake-host",
        commands: Commands | None = None,
    ) -> None:
        self.password = password
        self.client_key = client_key
        self.hostname = hostname
        self.commands = commands
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.auth_attempts: list[str] = []
        self.connections: list[asyncssh.SSHServerConnection] = []
        self.host = "127.0.0.1"
        self._loop = loop

        async def start() -> asyncssh.SSHAcceptor:
            return await asyncssh.create_server(
                lambda: _Server(self), self.host, 0, server_host_keys=[self.host_key], process_factory=self._handle,
            )

        self._acceptor = loop.run(start())
        self.port: int = self._acceptor.get_port()

    async def _handle(self, process: asyncssh.SSHServerProcess) -> None:
        if self.commands is None:
            process.stdout.write(f"{self.hostname}\n")
            process.exit(0)
            return
        command = process.command or ""
        # Only these commands are given anything on stdin; waiting for EOF on others would hang.
        stdin = await process.stdin.read() if command.startswith("sudo -S") or "-H @-" in command else ""
        stdout, stderr, status = self.commands(command, stdin)
        process.stdout.write(stdout)
        process.stderr.write(stderr)
        process.exit(status)

    def stop(self) -> None:
        """Stop listening and drop every open connection, like a server going off the network."""

        async def stop() -> None:
            self._acceptor.close()
            for connection in self.connections:
                connection.close()

        self._loop.run(stop())

    def close(self) -> None:
        async def stop() -> None:
            self._acceptor.close()
            # wait_closed waits for open connections too, such as a watcher's that outlives the test.
            for connection in self.connections:
                connection.close()
            await self._acceptor.wait_closed()

        self._loop.run(stop())
