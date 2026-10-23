"""Connecting to a server through a chain of jump hosts.

Nothing here touches the database: callers turn stored servers into Hops. Connections never
use the machine's own SSH setup (config file, agent, key files, known_hosts); each hop
carries exactly the credentials and host key vservx has stored for it.
"""

import asyncio
import time
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from typing import Any

import asyncssh

from api.enums import ConnectionFailure
from api.ssh.keys import fingerprint_of


@dataclass(frozen=True)
class Hop:
    """One server in a chain. Neither password nor client_key means its stored credentials
    couldn't be read."""

    name: str
    host: str
    port: int
    username: str
    password: str | None = field(repr=False)
    client_key: asyncssh.SSHKey | None = field(repr=False)
    # The recorded OpenSSH public key line; None trusts the key the server presents.
    host_key: str | None


@dataclass(frozen=True)
class HopOutcome:
    name: str
    ok: bool
    # What the server presented, when the handshake got that far.
    host_key: str | None
    fingerprint: str | None
    reason: ConnectionFailure | None
    message: str | None


@dataclass
class ChainResult:
    outcomes: list[HopOutcome]
    # The last hop's connection, set only when every hop succeeded.
    connection: asyncssh.SSHClientConnection | None


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    hostname: str | None
    elapsed_ms: int
    # Every hop attempted, in order; on failure the failing hop is last.
    hops: list[HopOutcome]


def _key_line(key: asyncssh.SSHKey) -> str:
    return key.export_public_key().decode().strip()


def _failed(hop: Hop, reason: ConnectionFailure, message: str, host_key: str | None = None) -> HopOutcome:
    fingerprint = fingerprint_of(host_key) if host_key else None
    return HopOutcome(hop.name, False, host_key, fingerprint, reason, message)


def _connect_options(hop: Hop, timeout: float) -> dict[str, Any]:
    return {
        "host": hop.host,
        "port": hop.port,
        "username": hop.username,
        "password": hop.password,
        "client_keys": [hop.client_key] if hop.client_key else None,
        # A recorded key is the only one accepted, and negotiation asks for its type. The check
        # happens in the handshake, before any password or key is sent.
        "known_hosts": ([asyncssh.import_public_key(hop.host_key)], [], []) if hop.host_key else None,
        # Ignore the local ~/.ssh/config, ssh-agent and Kerberos setup.
        "config": None,
        "agent_path": None,
        "gss_host": None,
        "connect_timeout": timeout,
    }


async def _close(connection: asyncssh.SSHClientConnection) -> None:
    connection.close()
    await connection.wait_closed()


async def _server_host_key(
    host: str, port: int, tunnel: asyncssh.SSHClientConnection | None, timeout: float, algs: Sequence[str]
) -> str:
    key = await asyncio.wait_for(
        asyncssh.get_server_host_key(host, port, tunnel=tunnel, server_host_key_algs=algs, config=None),
        timeout,
    )
    if key is None:
        raise ValueError(f"{host}:{port} presented no host key")
    return _key_line(key)


async def fetch_host_key(
    host: str, port: int, *, tunnel: asyncssh.SSHClientConnection | None, timeout: float, like: str | None = None
) -> str:
    """The OpenSSH public key line the server presents, without logging in.

    `like` asks for the same key type as that public key (a server with several host keys
    presents a different one depending on what's asked for), falling back to the server's
    default if it no longer offers that type.
    """
    if like is not None:
        algs = [alg.decode() for alg in asyncssh.import_public_key(like).sig_algorithms]
        try:
            return await _server_host_key(host, port, tunnel, timeout, algs)
        except asyncssh.KeyExchangeFailed:
            pass
    return await _server_host_key(host, port, tunnel, timeout, ())


async def _presented_key(hop: Hop, tunnel: asyncssh.SSHClientConnection | None, timeout: float) -> str | None:
    try:
        return await fetch_host_key(hop.host, hop.port, tunnel=tunnel, timeout=timeout, like=hop.host_key)
    except (OSError, asyncssh.Error, ValueError):
        return None


async def _connect_hop(
    hop: Hop, tunnel: asyncssh.SSHClientConnection | None, timeout: float
) -> tuple[HopOutcome, asyncssh.SSHClientConnection | None]:
    if hop.password is None and hop.client_key is None:
        return _failed(hop, ConnectionFailure.CREDENTIALS_UNREADABLE,
                       "The stored password or key can't be decrypted (the encryption key changed); "
                       "re-enter it"), None
    where = f"{hop.host}:{hop.port}"
    key_changed = f"{where} presented a different host key than the one recorded; an admin must accept the new key"
    try:
        connection = await asyncssh.connect(tunnel=tunnel, **_connect_options(hop, timeout))
    except asyncssh.HostKeyNotVerifiable:
        presented = await _presented_key(hop, tunnel, timeout)
        return _failed(hop, ConnectionFailure.HOST_KEY_CHANGED, key_changed, presented), None
    except asyncssh.KeyExchangeFailed as exc:
        # A server that no longer offers the recorded key's type fails negotiation instead.
        if hop.host_key is not None:
            presented = await _presented_key(hop, tunnel, timeout)
            if presented is not None and fingerprint_of(presented) != fingerprint_of(hop.host_key):
                return _failed(hop, ConnectionFailure.HOST_KEY_CHANGED, key_changed, presented), None
        return _failed(hop, ConnectionFailure.ERROR, str(exc)), None
    except asyncssh.PermissionDenied:
        credential = "key" if hop.client_key else "password"
        return _failed(hop, ConnectionFailure.AUTH_FAILED,
                       f"{where} rejected the {credential} for user {hop.username}"), None
    except TimeoutError:
        return _failed(hop, ConnectionFailure.TIMEOUT, f"No answer from {where} within {timeout:g} seconds"), None
    except OSError as exc:
        return _failed(hop, ConnectionFailure.UNREACHABLE, f"Can't reach {where}: {exc.strerror or exc}"), None
    except asyncssh.ChannelOpenError as exc:
        # The jump host in front couldn't open a connection to this hop.
        return _failed(hop, ConnectionFailure.UNREACHABLE,
                       f"Can't reach {where} from the previous hop: {exc.reason}"), None
    except (asyncssh.Error, ValueError) as exc:
        return _failed(hop, ConnectionFailure.ERROR, str(exc)), None
    key = connection.get_server_host_key()
    if key is None:
        return HopOutcome(hop.name, True, None, None, None, None), connection
    return HopOutcome(hop.name, True, _key_line(key), key.get_fingerprint(), None, None), connection


async def connect_chain(hops: Sequence[Hop], timeout: float, stack: AsyncExitStack) -> ChainResult:
    """Connect hop by hop, each through the one before. Never raises for a connection
    failure; it's the last outcome. Connections are closed when `stack` unwinds."""
    outcomes: list[HopOutcome] = []
    connection: asyncssh.SSHClientConnection | None = None
    for hop in hops:
        outcome, next_connection = await _connect_hop(hop, connection, timeout)
        outcomes.append(outcome)
        if next_connection is None:
            return ChainResult(outcomes, None)
        stack.push_async_callback(_close, next_connection)
        connection = next_connection
    return ChainResult(outcomes, connection)


async def run_connection_test(hops: Sequence[Hop], timeout: float) -> ChainReport:
    """Connect through the chain, run `hostname` on the last server to prove a shell works,
    and disconnect."""
    started = time.monotonic()
    hostname = None
    async with AsyncExitStack() as stack:
        result = await connect_chain(hops, timeout, stack)
        outcomes = result.outcomes
        if result.connection is not None:
            try:
                completed = await asyncio.wait_for(result.connection.run("hostname"), timeout)
                hostname = str(completed.stdout or "").strip() or None
            except TimeoutError:
                outcomes[-1] = replace(outcomes[-1], ok=False, reason=ConnectionFailure.TIMEOUT,
                                       message=f"Logged in, but no answer to a command within {timeout:g} seconds")
            except (asyncssh.Error, OSError) as exc:
                outcomes[-1] = replace(outcomes[-1], ok=False, reason=ConnectionFailure.ERROR,
                                       message=f"Logged in, but couldn't run a command: {exc}")
    ok = bool(outcomes) and all(outcome.ok for outcome in outcomes)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ChainReport(ok, hostname if ok else None, elapsed_ms, outcomes)
