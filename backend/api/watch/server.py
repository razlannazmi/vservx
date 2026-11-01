"""Watching one server: one SSH connection kept open, looking for instances every so often, and
reading their health and usage, and the GPUs, every round."""

import asyncio
import random
from collections import Counter
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import asyncssh

from api.config import Settings
from api.db.base import utcnow
from api.enums import ConnectionFailure, DockerStatus, InstanceState, WatchState
from api.schemas.watch import GpuRead, ServerWatchRead, UsagePointRead, WatchedInstanceRead, WatchSummaryRead
from api.ssh.connect import Hop, connect_chain
from api.watch.docker import (
    PS_ARGS,
    DockerAccess,
    inspect_args,
    parse_inspect,
    parse_ps,
    probe_docker,
    run_docker,
    target,
)
from api.watch.frameworks import Container, Framework, HttpResponse, InstanceInfo, InstanceSpec, framework_for
from api.watch.gpus import GPU_COMMAND, Gpu, gpu_users, parse_gpus
from api.watch.shell import CantReachPort, PortClosed, Shell
from api.watch.states import Probe, instance_state
from api.watch.usage import UsageHistory, UsagePoint

# Waits before reconnecting: doubling from the first to the last.
RECONNECT_FIRST = 10.0
RECONNECT_MAX = 300.0
# Refresh looks for instances at most this often.
REFRESH_GAP = timedelta(seconds=5)
NO_GPUS = "nvidia-smi isn't available on this server."

# Docker answers that only a change to the server's settings can fix (which starts a new
# ServerWatch), so they're not asked again. A rejected sudo password, tried again, can lock the account.
_SETTLED = frozenset({DockerStatus.NEEDS_SUDO_PASSWORD, DockerStatus.SUDO_PASSWORD_REJECTED, DockerStatus.SUDO_NEEDS_TTY})
# Sign-in problems retrying won't fix; retrying a rejected password is how addresses get banned.
_STOPS = {ConnectionFailure.AUTH_FAILED: WatchState.SIGN_IN_FAILED,
          ConnectionFailure.CREDENTIALS_UNREADABLE: WatchState.SIGN_IN_FAILED,
          ConnectionFailure.HOST_KEY_CHANGED: WatchState.HOST_KEY_CHANGED}


@dataclass(frozen=True)
class WatchConfig:
    server_id: int
    # Outermost jump host first. Every hop has a recorded host key.
    hops: list[Hop]
    sudo_password: str | None = field(repr=False)


@dataclass
class _Instance:
    container: Container
    framework: Framework
    spec: InstanceSpec
    state: InstanceState
    # Healthy at least once since the container last started.
    ever_ready: bool = False
    info: InstanceInfo | None = None
    message: str | None = None


def usage_read(point: UsagePoint) -> UsagePointRead:
    return UsagePointRead(at=point.at, running=point.running, waiting=point.waiting,
                          kv_cache_percent=point.kv_cache_percent, tokens_in_per_s=point.tokens_in_per_s,
                          tokens_out_per_s=point.tokens_out_per_s, ttft_seconds=point.ttft_seconds)


class ServerWatch:
    def __init__(self, config: WatchConfig, settings: Settings, limiter: asyncio.Semaphore,
                 histories: dict[str, UsageHistory]) -> None:
        """`histories` (container name -> history) belongs to the caller, so it outlives this
        watch when the server's settings change and a new one takes over."""
        self.config = config
        self._settings = settings
        self._limiter = limiter
        self._histories = histories
        self._history_length = max(1, round(settings.history_minutes * 60 / settings.usage_interval_seconds))
        self._round_limit = 2 * settings.ssh_connect_timeout
        # Set when run() has ended for good.
        self.stopped_at: datetime | None = None
        self._state = WatchState.CHECKING
        self._since: datetime | None = None
        self._message: str | None = None
        self._docker = DockerAccess(DockerStatus.UNKNOWN, None, None)
        self._instances: dict[str, _Instance] = {}
        self._gpus: list[Gpu] | None = None
        self._gpu_message: str | None = None
        self._found_at: datetime | None = None
        self._read_at: datetime | None = None
        self._last_discovery: datetime | None = None
        self._discovery_due = True
        self._wake = asyncio.Event()
        self._round_done = asyncio.Event()

    # Running

    async def run(self) -> None:
        """Watch until cancelled, or until a sign-in problem that retrying won't fix."""
        # Out of step with the other servers, so they don't all poll on the same second.
        await asyncio.sleep(random.uniform(0, self._settings.usage_interval_seconds))
        wait = RECONNECT_FIRST
        while True:
            async with AsyncExitStack() as stack:
                shell = await self._connect(stack)
                if shell is not None:
                    wait = RECONNECT_FIRST
                    await self._watch(shell)
                    continue
            if self.stopped_at is not None:
                return
            await asyncio.sleep(wait)
            wait = min(wait * 2, RECONNECT_MAX)

    async def refresh(self) -> None:
        """Look for instances and read usage now; return once that round is done."""
        if self._state is not WatchState.CONNECTED:
            return
        if self._last_discovery is not None and utcnow() - self._last_discovery < REFRESH_GAP:
            return
        self._discovery_due = True
        done = self._round_done
        self._wake.set()
        try:
            await asyncio.wait_for(done.wait(), self._round_limit)
        except TimeoutError:
            pass

    def _set_state(self, state: WatchState, message: str | None) -> None:
        # "since" is when the state began: an unreachable server stays unreachable since its first failure.
        if state is not self._state:
            self._since = utcnow()
        self._state = state
        self._message = message

    async def _connect(self, stack: AsyncExitStack) -> Shell | None:
        async with self._limiter:
            result = await connect_chain(self.config.hops, self._settings.ssh_connect_timeout, stack)
        if result.connection is not None:
            self._set_state(WatchState.CONNECTED, None)
            return Shell(result.connection, self._settings.ssh_connect_timeout)
        failed = result.outcomes[-1]
        stop = _STOPS.get(failed.reason) if failed.reason else None
        self._set_state(stop or WatchState.UNREACHABLE, failed.message)
        if stop is not None:
            self.stopped_at = utcnow()
        return None

    async def _watch(self, shell: Shell) -> None:
        """Rounds until the connection fails."""
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            try:
                async with self._limiter:
                    await asyncio.wait_for(self._round(shell), self._round_limit)
            except TimeoutError:
                self._set_state(WatchState.UNREACHABLE, f"No answer within {self._round_limit:g} seconds")
                return
            except (asyncssh.Error, OSError) as exc:
                self._set_state(WatchState.UNREACHABLE, str(exc) or "The connection was lost")
                return
            finally:
                self._round_done.set()
                self._round_done = asyncio.Event()
            remaining = self._settings.usage_interval_seconds - (loop.time() - started)
            try:
                await asyncio.wait_for(self._wake.wait(), max(0.0, remaining))
            except TimeoutError:
                pass
            self._wake.clear()

    async def _round(self, shell: Shell) -> None:
        overdue = (self._last_discovery is None or utcnow() - self._last_discovery
                   >= timedelta(seconds=self._settings.discovery_interval_seconds))
        if self._discovery_due or overdue:
            await self._discover(shell)
        for instance in self._instances.values():
            if instance.container.status == "running":
                await self._probe(shell, instance)
        await self._read_gpus(shell, retry=overdue)
        self._read_at = utcnow()

    # Looking for instances

    async def _discover(self, shell: Shell) -> None:
        self._discovery_due = False
        self._last_discovery = utcnow()
        sudo_password = self.config.sudo_password
        if self._docker.status in _SETTLED:
            return
        ps = None
        if self._docker.prefix is not None:
            ps = await run_docker(shell, self._docker, PS_ARGS, sudo_password)
        if ps is None or ps.exit_status != 0:
            # Not known yet, or the way that worked has stopped working (group or sudoers changed).
            self._docker, ps = await probe_docker(shell, sudo_password)
        if ps is None:
            return
        frameworks = {entry.name: framework for entry in parse_ps(ps.stdout)
                      if (framework := framework_for(entry.image, entry.command))}
        containers: list[Container] = []
        if frameworks:
            inspected = await run_docker(shell, self._docker, inspect_args(list(frameworks)), sudo_password)
            if inspected.exit_status != 0 and not inspected.stdout.strip():
                return  # keep what's known rather than lose every instance's history to one bad answer
            containers = parse_inspect(inspected.stdout)
        found = set()
        for container in containers:
            framework = frameworks.get(container.name)
            if framework is None:
                continue
            found.add(container.name)
            known = self._instances.get(container.name)
            if known is None or known.container.started_at != container.started_at:
                # New, or restarted: it has to become healthy again, and its version may have changed.
                self._instances[container.name] = _Instance(
                    container, framework, framework.describe(container), instance_state(container, None, False))
                continue
            known.container, known.spec = container, framework.describe(container)
            if container.status != "running":
                known.state, known.message = instance_state(container, None, known.ever_ready), None
        for name in list(self._instances):
            if name not in found:
                del self._instances[name]
                self._histories.pop(name, None)
        self._found_at = utcnow()

    # Reading usage

    async def _probe(self, shell: Shell, instance: _Instance) -> None:
        host, port = target(instance.container, instance.spec.port)

        async def get(path: str, headers: dict[str, str]) -> HttpResponse:
            return await shell.http_get(host, port, path, headers)

        message = None
        try:
            health = await get(instance.framework.health_path, {})
            probe = Probe.HEALTHY if health.status == 200 else Probe.UNHEALTHY
        except PortClosed:
            probe = Probe.PORT_CLOSED
        except CantReachPort as exc:
            probe, message = Probe.CANT_REACH, str(exc)
        except TimeoutError:
            probe = Probe.UNHEALTHY
        was_ready = instance.state is InstanceState.READY
        if probe is Probe.HEALTHY:
            instance.ever_ready = True
            try:
                if instance.info is None:
                    instance.info = await instance.framework.read_info(get, instance.spec)
                metrics = await get(instance.framework.metrics_path, {})
                if metrics.status == 200:
                    history = self._histories.setdefault(instance.container.name, UsageHistory(self._history_length))
                    history.add(instance.framework.read_metrics(metrics.body), utcnow())
            except (PortClosed, CantReachPort, TimeoutError):
                pass  # a hiccup between the health check and the metrics; next round reads them
        instance.state = instance_state(instance.container, probe, instance.ever_ready)
        instance.message = message
        if was_ready and instance.state is not InstanceState.READY:
            # It may have stopped: see what Docker says at the next round, not in a minute.
            self._discovery_due = True

    async def _read_gpus(self, shell: Shell, retry: bool) -> None:
        # A server without nvidia-smi is asked again only when instances are looked for.
        if self._gpus is None and self._gpu_message is not None and not retry:
            return
        result = await shell.run(GPU_COMMAND)
        if result.exit_status == 0:
            self._gpus, self._gpu_message = parse_gpus(result.stdout), None
            return
        self._gpus = None
        if result.exit_status == 127:
            self._gpu_message = NO_GPUS
        else:
            reason = next((line.strip() for line in (result.stderr + result.stdout).splitlines() if line.strip()), "")
            self._gpu_message = f"nvidia-smi failed: {reason}" if reason else NO_GPUS

    # Reading back

    def _instance_read(self, instance: _Instance) -> WatchedInstanceRead:
        container, spec, info = instance.container, instance.spec, instance.info
        history = self._histories.get(container.name)
        latest = history.latest if history else None
        return WatchedInstanceRead(
            name=container.name,
            framework=instance.framework.name,
            state=instance.state,
            message=instance.message,
            image=container.image,
            model=(info.model if info and info.model else None) or spec.model,
            port=spec.port,
            max_model_len=spec.max_model_len or (info.max_model_len if info else None),
            version=info.version if info else None,
            gpus=container.gpus,
            started_at=container.started_at,
            finished_at=container.finished_at,
            exit_code=container.exit_code,
            oom_killed=container.oom_killed,
            restart_count=container.restart_count,
            usage=usage_read(latest) if latest and instance.state is InstanceState.READY else None,
            running_trend=[point.running for point in history.points] if history else [],
        )

    def view(self) -> ServerWatchRead:
        instances = sorted(self._instances.values(), key=lambda instance: instance.container.name)
        gpus = None
        if self._gpus is not None:
            users = gpu_users(self._gpus, [instance.container for instance in instances])
            gpus = [GpuRead(index=gpu.index, name=gpu.name, utilization_percent=gpu.utilization,
                            memory_used_mib=gpu.memory_used, memory_total_mib=gpu.memory_total,
                            temperature_c=gpu.temperature, instances=users.get(gpu.index, []))
                    for gpu in self._gpus]
        return ServerWatchRead(
            server_id=self.config.server_id, state=self._state, since=self._since, message=self._message,
            docker=self._docker.status, docker_message=self._docker.message,
            found_at=self._found_at, read_at=self._read_at,
            instances=[self._instance_read(instance) for instance in instances],
            gpus=gpus, gpu_message=self._gpu_message,
            usage_interval_seconds=self._settings.usage_interval_seconds,
        )

    def summary(self) -> WatchSummaryRead:
        counts = Counter(instance.state for instance in self._instances.values())
        return WatchSummaryRead(server_id=self.config.server_id, state=self._state, since=self._since,
                                docker=self._docker.status, counts=dict(counts))
