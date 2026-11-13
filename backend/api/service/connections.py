"""Turning stored servers into SSH hops, testing them, and recording their host keys."""

import asyncio
import time
from contextlib import AsyncExitStack

import asyncssh
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.db.base import utcnow
from api.enums import AuthType, ConnectionFailure
from api.models import SavedKey, Server
from api.schemas.connection import ConnectionTestResult, HopResult
from api.service.servers import MAX_JUMP_HOSTS
from api.ssh.connect import Hop, connect_chain, fetch_host_key, run_connection_test
from api.ssh.keys import InvalidKey, fingerprint_of, load_private_key
from api.watch import local
from api.watch.docker import probe_docker


class HostKeyMismatch(Exception):
    """The server presents a different key than the one the admin approved."""


class ChainUnreachable(Exception):
    """A jump host or the server itself couldn't be reached. str(exc) says which and why."""


async def _client_key(session: AsyncSession, server: Server) -> asyncssh.SSHKey | None:
    """The server's saved key, or None if it can't be decrypted or loaded."""
    if server.auth_type is not AuthType.KEY or server.ssh_key_id is None:
        return None
    saved = await session.get(SavedKey, server.ssh_key_id)
    if saved is None or saved.private_key is None:
        return None
    try:
        # Unlocking an encrypted key is deliberately slow; keep it off the event loop.
        return await asyncio.to_thread(load_private_key, saved.private_key, saved.passphrase)
    except InvalidKey:
        return None


async def _hop(session: AsyncSession, server: Server) -> Hop:
    password = server.password if server.auth_type is AuthType.PASSWORD else None
    return Hop(name=server.name, host=server.host, port=server.port, username=server.username,
               password=password, client_key=await _client_key(session, server), host_key=server.host_key)


async def build_hops(session: AsyncSession, server: Server) -> list[tuple[Server, Hop]]:
    """The server's chain, outermost jump host first and the server last. Works for an
    unsaved server (id None)."""
    chain = [server]
    jump_id = server.jump_server_id
    while jump_id is not None:
        # check_links prevents both; this guards against a database edited by hand.
        if jump_id == server.id or any(s.id == jump_id for s in chain):
            raise ValueError("The jump host chain loops back on itself")
        if len(chain) > MAX_JUMP_HOSTS:
            raise ValueError(f"More than {MAX_JUMP_HOSTS} jump hosts in front of {server.name}")
        jump = await session.get(Server, jump_id)
        if jump is None or jump.workspace_id != server.workspace_id:
            raise ValueError(f"Jump server {jump_id} does not exist")
        chain.append(jump)
        jump_id = jump.jump_server_id
    chain.reverse()
    return [(stored, await _hop(session, stored)) for stored in chain]


def _remember_test(server: Server, result: ConnectionTestResult) -> None:
    server.last_test_at = utcnow()
    server.last_test_ok = result.ok
    server.last_test_elapsed_ms = result.elapsed_ms
    server.last_test_hostname = result.hostname[:255] if result.ok and result.hostname else None
    # On failure the failing hop is the last one attempted.
    failed = result.hops[-1] if not result.ok and result.hops else None
    server.last_test_failure = failed.reason if failed else None
    server.last_test_failed_hop = failed.name[:255] if failed else None
    server.last_test_message = failed.message if failed else None


async def check_server_connection(session: AsyncSession, server: Server, timeout: float) -> ConnectionTestResult:
    """Test the server through its jump chain. Every saved server in the chain that logged in
    and has no recorded host key gets the one it presented. A saved server remembers the result."""
    pairs = await build_hops(session, server)
    report = await run_connection_test([hop for _, hop in pairs], timeout)
    hops = []
    for (stored, _), outcome in zip(pairs, report.hops):
        if stored.id is not None and outcome.ok and stored.host_key is None and outcome.host_key:
            stored.host_key = outcome.host_key
            stored.host_key_recorded_at = utcnow()
        hops.append(HopResult(server_id=stored.id, name=outcome.name, ok=outcome.ok,
                              fingerprint=outcome.fingerprint, reason=outcome.reason, message=outcome.message))
    result = ConnectionTestResult(ok=report.ok, hostname=report.hostname, elapsed_ms=report.elapsed_ms, hops=hops)
    if server.id is not None:
        _remember_test(server, result)
    await session.commit()
    return result


def _this_machine_result(server: Server, started: float, hostname: str | None, ok: bool,
                         reason: ConnectionFailure | None, message: str | None) -> ConnectionTestResult:
    hop = HopResult(server_id=server.id, name=server.name, ok=ok, fingerprint=None, reason=reason, message=message)
    return ConnectionTestResult(ok=ok, hostname=hostname, elapsed_ms=int((time.monotonic() - started) * 1000), hops=[hop])


async def check_this_machine(session: AsyncSession, server: Server) -> ConnectionTestResult:
    """Test this machine: that a command runs here, then whether Docker and systemd can be reached.
    Only a command that can't run fails the test; a Docker or systemd problem is in the message.
    A saved server remembers the result."""
    started = time.monotonic()
    timeout = get_settings().ssh_connect_timeout
    result = await _test_this_machine(server, started, timeout)
    if server.id is not None:
        _remember_test(server, result)
    await session.commit()
    return result


async def _test_this_machine(server: Server, started: float, timeout: float) -> ConnectionTestResult:
    if reason := local.unavailable_reason():
        return _this_machine_result(server, started, None, False, ConnectionFailure.ERROR, reason)
    hints = local.container_hints()
    shell = local.LocalShell(timeout)
    try:
        systemd = await shell.run("systemctl show --property=Version --value")
        docker, ps = await probe_docker(shell, server.sudo_password)
    except TimeoutError:
        return _this_machine_result(server, started, None, False, ConnectionFailure.TIMEOUT,
                                    f"No answer within {timeout:g} seconds")
    except OSError as exc:
        return _this_machine_result(server, started, None, False, ConnectionFailure.ERROR, str(exc))
    if ps is not None:
        parts = ["Docker: reachable"]
    else:
        parts = [f"Docker: {hints.get('docker') or docker.message or 'not reachable'}"]
    if systemd.exit_status == 0:
        parts.append("systemd: reachable")
    else:
        first = next((line.strip() for line in systemd.stderr.splitlines() if line.strip()), "systemctl failed")
        parts.append(f"systemd: {hints.get('systemd') or first}")
    parts += [hints[name] for name in ("pid", "gpus") if name in hints]
    return _this_machine_result(server, started, local.machine_hostname(), True, None, "; ".join(parts))


async def accept_host_key(session: AsyncSession, server: Server, fingerprint: str, timeout: float) -> None:
    """Record the key the server presents now, if it's the one the admin approved.

    Jump hosts in front are connected with their usual checks; the server itself is only
    asked for its key, never logged in to.
    """
    pairs = await build_hops(session, server)
    jumps, target = [hop for _, hop in pairs[:-1]], pairs[-1][1]
    where = f"{target.host}:{target.port}"
    async with AsyncExitStack() as stack:
        result = await connect_chain(jumps, timeout, stack)
        if jumps and result.connection is None:
            failed = result.outcomes[-1]
            raise ChainUnreachable(f"Jump host {failed.name}: {failed.message}")
        try:
            presented = await fetch_host_key(target.host, target.port, tunnel=result.connection,
                                             timeout=timeout, like=server.host_key)
        except TimeoutError:
            raise ChainUnreachable(f"No answer from {where} within {timeout:g} seconds") from None
        except (OSError, asyncssh.Error, ValueError) as exc:
            raise ChainUnreachable(f"Can't reach {where}: {exc}") from None
    if fingerprint_of(presented) != fingerprint:
        raise HostKeyMismatch
    server.host_key = presented
    server.host_key_recorded_at = utcnow()
    await session.commit()
