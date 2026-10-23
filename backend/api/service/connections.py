"""Turning stored servers into SSH hops, testing them, and recording their host keys."""

import asyncio
from contextlib import AsyncExitStack

import asyncssh
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import AuthType
from api.models import SavedKey, Server
from api.schemas.connection import ConnectionTestResult, HopResult
from api.service.servers import MAX_JUMP_HOSTS
from api.ssh.connect import Hop, connect_chain, fetch_host_key, run_connection_test
from api.ssh.keys import InvalidKey, fingerprint_of, load_private_key


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
        if jump is None:
            raise ValueError(f"Jump server {jump_id} does not exist")
        chain.append(jump)
        jump_id = jump.jump_server_id
    chain.reverse()
    return [(stored, await _hop(session, stored)) for stored in chain]


async def check_server_connection(session: AsyncSession, server: Server, timeout: float) -> ConnectionTestResult:
    """Test the server through its jump chain. Every saved server in the chain that logged in
    and has no recorded host key gets the one it presented."""
    pairs = await build_hops(session, server)
    report = await run_connection_test([hop for _, hop in pairs], timeout)
    hops = []
    for (stored, _), outcome in zip(pairs, report.hops):
        if stored.id is not None and outcome.ok and stored.host_key is None and outcome.host_key:
            stored.host_key = outcome.host_key
        hops.append(HopResult(server_id=stored.id, name=outcome.name, ok=outcome.ok,
                              fingerprint=outcome.fingerprint, reason=outcome.reason, message=outcome.message))
    await session.commit()
    return ConnectionTestResult(ok=report.ok, hostname=report.hostname, elapsed_ms=report.elapsed_ms, hops=hops)


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
    await session.commit()
