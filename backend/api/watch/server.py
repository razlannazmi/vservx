"""Watching one server: one SSH connection kept open, looking for instances every so often, and
reading their health and usage, and the GPUs, every round."""

import asyncio
import logging
import random
from collections import Counter
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import asyncssh

from api.config import Settings
from api.db.base import utcnow
from api.enums import ConnectionFailure, DockerStatus, InstanceSource, InstanceState, ServerKind, WatchState
from api.schemas.watch import (
    GpuRead,
    RemovedInstanceRead,
    ServerWatchRead,
    UsagePointRead,
    WatchedInstanceRead,
    WatchSummaryRead,
)
from api.snapshots.config import LaunchConfig, launch_config
from api.snapshots.fingerprint import fingerprint
from api.snapshots.recorder import REMOVED_ROW_DAYS, Seen, SnapshotRecorder
from api.ssh.connect import Hop, connect_chain
from api.watch import local
from api.watch.docker import (
    PS_ARGS,
    DockerAccess,
    ImageDefaults,
    image_inspect_args,
    inspect_args,
    is_template_error,
    parse_image_inspect,
    parse_inspect,
    parse_ps,
    probe_docker,
    run_docker,
    target,
)
from api.watch.frameworks import (
    Container,
    Framework,
    HttpResponse,
    InstanceInfo,
    InstanceSpec,
    framework_for,
    instance_key,
)
from api.watch.gpus import GPU_COMMAND, Gpu, gpu_users, parse_gpus
from api.watch.shell import CantReachPort, CommandResult, PortClosed, ServerShell, Shell
from api.watch.states import Probe, instance_state
from api.watch.usage import UsageHistory, UsagePoint

logger = logging.getLogger(__name__)

# Waits before reconnecting: doubling from the first to the last.
RECONNECT_FIRST = 10.0
RECONNECT_MAX = 300.0
# Refresh looks for instances at most this often.
REFRESH_GAP = timedelta(seconds=5)
# Instances read at the same moment on one server. Read through curl, each is an SSH session,
# and sshd allows 10 per connection by default (MaxSessions).
PROBES_AT_ONCE = 4
NO_GPUS = "nvidia-smi isn't available on this server."
USE_HOST_NETWORKING = "vservx runs in a container: use host networking (network_mode: host) to reach this port."
# Discoveries an image's own settings are asked for before snapshots go ahead without them.
IMAGE_TRIES = 3

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
    # This machine is watched through a LocalShell: no hops, no SSH.
    kind: ServerKind = ServerKind.SSH


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
    # What last went wrong reading it, as logged; None while it reads fine.
    problem: str | None = None


def usage_read(point: UsagePoint) -> UsagePointRead:
    return UsagePointRead(at=point.at, running=point.running, waiting=point.waiting,
                          kv_cache_percent=point.kv_cache_percent, tokens_in_per_s=point.tokens_in_per_s,
                          tokens_out_per_s=point.tokens_out_per_s, ttft_seconds=point.ttft_seconds)


class ServerWatch:
    def __init__(self, config: WatchConfig, settings: Settings, limiter: asyncio.Semaphore,
                 histories: dict[str, UsageHistory], recorder: SnapshotRecorder | None = None) -> None:
        """`histories` (instance_key -> history) belongs to the caller, so it outlives this
        watch when the server's settings change and a new one takes over. `recorder` writes launch
        snapshots; without one, none are taken."""
        self.config = config
        self._recorder = recorder
        # Image ID -> its own settings; None once they couldn't be read IMAGE_TRIES times, so they aren't asked again.
        self._image_defaults: dict[str, ImageDefaults | None] = {}
        self._image_failures: dict[str, int] = {}
        # Set once this server's Docker can't run the env filter: env names only from then on.
        self._env_names_only = False
        # What was last written: name -> (container ID, config, fingerprint). None until a write succeeds.
        self._recorded: dict[str, tuple[str, LaunchConfig, str | None]] | None = None
        self._record_failing = False
        self._changed_at: dict[str, datetime] = {}
        self._removed: list[RemovedInstanceRead] = []
        self._settings = settings
        self._limiter = limiter
        self._histories = histories
        self._history_length = max(1, round(settings.history_minutes * 60 / settings.usage_interval_seconds))
        self._round_limit = 2 * settings.ssh_connect_timeout
        # In a container, what this machine can't see of its host, by part (see local.container_hints).
        this_machine = config.kind is ServerKind.THIS_MACHINE
        self._hints = local.container_hints() if this_machine else {}
        self._in_container = this_machine and local.in_container()
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

    async def _connect(self, stack: AsyncExitStack) -> ServerShell | None:
        if self.config.kind is ServerKind.THIS_MACHINE:
            self._set_state(WatchState.CONNECTED, None)
            return local.LocalShell(self._settings.ssh_connect_timeout)
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

    async def _watch(self, shell: ServerShell) -> None:
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

    async def _round(self, shell: ServerShell) -> None:
        overdue = (self._last_discovery is None or utcnow() - self._last_discovery
                   >= timedelta(seconds=self._settings.discovery_interval_seconds))
        if self._discovery_due or overdue:
            await self._discover(shell)
        await self._probe_all(shell, [instance for instance in self._instances.values()
                                      if instance.container.status == "running"])
        await self._read_gpus(shell, retry=overdue)
        self._read_at = utcnow()

    # Looking for instances

    async def _discover(self, shell: ServerShell) -> None:
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
            if ps is None and "docker" in self._hints:
                self._docker = replace(self._docker, message=self._hints["docker"])
        if ps is None:
            return
        frameworks = {entry.name: framework for entry in parse_ps(ps.stdout)
                      if (framework := framework_for(entry.image, entry.command))}
        containers: list[Container] = []
        if frameworks:
            inspected = await self._inspect(shell, list(frameworks))
            if inspected.exit_status != 0 and not inspected.stdout.strip():
                return  # keep what's known rather than lose every instance's history to one bad answer
            containers = parse_inspect(inspected.stdout, env_values_hidden=self._env_names_only)
        found = set()
        for container in containers:
            framework = frameworks.get(container.name)
            if framework is None:
                continue
            key = instance_key(container.source, container.name)
            found.add(key)
            known = self._instances.get(key)
            if known is None or known.container.started_at != container.started_at:
                # New, or restarted: it has to become healthy again, and its version may have changed.
                self._instances[key] = _Instance(
                    container, framework, framework.describe(container), instance_state(container, None, False))
                continue
            known.container, known.spec = container, framework.describe(container)
            if container.status != "running":
                known.state, known.message = instance_state(container, None, known.ever_ready), None
        for key in list(self._instances):
            if key not in found:
                del self._instances[key]
                self._histories.pop(key, None)
        self._found_at = utcnow()
        await self._record(shell, [container for container in containers
                                   if instance_key(container.source, container.name) in found])

    async def _inspect(self, shell: ServerShell, names: list[str]) -> CommandResult:
        """docker inspect, falling back for good to env names only when Docker can't run the filter."""
        sudo_password = self.config.sudo_password
        result = await run_docker(shell, self._docker, inspect_args(names, not self._env_names_only), sudo_password)
        if not self._env_names_only and is_template_error(result):
            logger.warning("Server %s: Docker can't run the env filter, so env values won't be shown",
                           self.config.server_id)
            self._env_names_only = True
            result = await run_docker(shell, self._docker, inspect_args(names, False), sudo_password)
        return result

    # Recording snapshots

    async def _image_settings(self, shell: ServerShell, containers: list[Container]) -> bool:
        """Read the images' own settings once each. False while one couldn't be read yet: a config
        built without them would hold the image's inherited env and entrypoint, then change once
        they read fine. An image still unreadable after IMAGE_TRIES discoveries is given up on."""
        missing = sorted({c.image_id for c in containers if c.image_id and c.image_id not in self._image_defaults})
        if not missing:
            return True
        result = await run_docker(shell, self._docker, image_inspect_args(missing, not self._env_names_only),
                                  self.config.sudo_password)
        try:
            found = parse_image_inspect(result.stdout)
        except (ValueError, KeyError):
            found = {}
        known = True
        for image_id in missing:
            if image_id in found:
                self._image_defaults[image_id] = found[image_id]
                self._image_failures.pop(image_id, None)
                continue
            failures = self._image_failures.get(image_id, 0) + 1
            if failures >= IMAGE_TRIES:
                self._image_defaults[image_id] = None
                self._image_failures.pop(image_id, None)
            else:
                self._image_failures[image_id] = failures
                known = False
        return known

    async def _record(self, shell: ServerShell, containers: list[Container]) -> None:
        """Hand what was found to the recorder, unless nothing changed since the last write. A
        failed write is tried again at the next discovery; watching carries on regardless."""
        if self._recorder is None:
            return
        if not await self._image_settings(shell, containers):
            return  # tried again at the next discovery
        seen = []
        for container in containers:
            spec = self._instances[instance_key(container.source, container.name)].spec
            key_fingerprint, key_id = fingerprint(spec.api_key) if spec.api_key else (None, None)
            seen.append(Seen(
                name=container.name, container_id=container.id, created_at=container.created_at,
                started_at=container.started_at, restart_count=container.restart_count, image_id=container.image_id,
                model=spec.model, config=launch_config(container, self._image_defaults.get(container.image_id)),
                key_fingerprint=key_fingerprint, key_id=key_id, source=container.source,
            ))
        signature = {instance_key(s.source, s.name): (s.container_id, s.config, s.key_fingerprint) for s in seen}
        if signature == self._recorded:
            return
        try:
            recorded = await self._recorder.record(self.config.server_id, seen, utcnow(),
                                                   frozenset({InstanceSource.DOCKER}))
        except Exception:
            if not self._record_failing:
                logger.exception("Server %s: couldn't save launch snapshots; trying again at the next discovery",
                                 self.config.server_id)
            self._record_failing = True
            return
        self._record_failing = False
        self._recorded, self._changed_at, self._removed = signature, recorded.changed_at, recorded.removed

    async def _fill_version(self, instance: _Instance) -> None:
        if self._recorder is None or instance.info is None or not instance.info.version:
            return
        try:
            await self._recorder.fill_version(self.config.server_id, instance.container.source,
                                              instance.container.name, instance.container.id, instance.info.version)
        except Exception:
            logger.exception("Server %s: couldn't save instance %s's vLLM version", self.config.server_id,
                             instance.container.name)

    # Reading usage

    async def _probe_all(self, shell: ServerShell, instances: list[_Instance]) -> None:
        """Read the instances side by side, so a few slow ones can't push the round past its time
        limit and get the whole server called unreachable."""
        at_once = asyncio.Semaphore(PROBES_AT_ONCE)

        async def probe(instance: _Instance) -> None:
            async with at_once:
                await self._probe(shell, instance)

        try:
            async with asyncio.TaskGroup() as group:
                for instance in instances:
                    group.create_task(probe(instance))
        except ExceptionGroup as failed:
            # The connection broke under one of them, and the rest were cancelled: the round fails
            # on that error, as it did when they were read one at a time.
            raise failed.exceptions[0] from None

    async def _probe(self, shell: ServerShell, instance: _Instance) -> None:
        host, port = target(instance.container, instance.spec.port, instance.spec.host)

        async def get(path: str, headers: dict[str, str]) -> HttpResponse:
            return await shell.http_get(host, port, path, headers)

        health_path = instance.framework.health_path
        message = problem = None
        try:
            health = await get(health_path, {})
            probe = Probe.HEALTHY if health.status == 200 else Probe.UNHEALTHY
            if probe is Probe.UNHEALTHY:
                problem = f"GET {health_path} on {host}:{port} answered {health.status or 'without an HTTP status line'}"
        except PortClosed as exc:
            probe, problem = Probe.PORT_CLOSED, f"nothing accepts connections on {host}:{port} ({exc})"
        except CantReachPort as exc:
            probe, message = Probe.CANT_REACH, str(exc)
            problem = message
        except TimeoutError as exc:
            probe, problem = Probe.UNHEALTHY, str(exc) or f"GET {health_path} on {host}:{port} timed out"
        was_ready = instance.state is InstanceState.READY
        if probe is Probe.HEALTHY:
            instance.ever_ready = True
            try:
                if instance.info is None:
                    instance.info = await instance.framework.read_info(get, instance.spec)
                    await self._fill_version(instance)
                metrics = await get(instance.framework.metrics_path, {})
                if metrics.status == 200:
                    history = self._histories.setdefault(self._key(instance), UsageHistory(self._history_length))
                    history.add(instance.framework.read_metrics(metrics.body), utcnow())
                else:
                    problem = f"GET {instance.framework.metrics_path} answered {metrics.status}"
            except (PortClosed, CantReachPort, TimeoutError) as exc:
                # A hiccup between the health check and the metrics; the next round reads them.
                problem = f"couldn't read usage: {exc or type(exc).__name__}"
        instance.state = instance_state(instance.container, probe, instance.ever_ready)
        if probe is Probe.PORT_CLOSED and self._in_container:
            message = USE_HOST_NETWORKING
        instance.message = message
        self._log_problem(instance, problem)
        if was_ready and instance.state is not InstanceState.READY:
            # It may have stopped: see what Docker says at the next round, not in a minute.
            self._discovery_due = True

    @staticmethod
    def _key(instance: _Instance) -> str:
        return instance_key(instance.container.source, instance.container.name)

    def _log_problem(self, instance: _Instance, problem: str | None) -> None:
        """Say what went wrong reading an instance, once each time that changes, so a log isn't
        flooded every round."""
        if problem == instance.problem:
            return
        name = instance.container.name
        if problem is not None:
            logger.warning("Server %s, instance %s (%s): %s", self.config.server_id, name, instance.state, problem)
        else:
            logger.warning("Server %s, instance %s: reading it again", self.config.server_id, name)
        instance.problem = problem

    async def _read_gpus(self, shell: ServerShell, retry: bool) -> None:
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
        if "gpus" in self._hints:
            self._gpu_message = self._hints["gpus"]

    # Reading back

    def _instance_read(self, instance: _Instance) -> WatchedInstanceRead:
        container, spec, info = instance.container, instance.spec, instance.info
        key = self._key(instance)
        history = self._histories.get(key)
        latest = history.latest if history else None
        return WatchedInstanceRead(
            name=container.name,
            source=container.source,
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
            changed_at=self._changed_at.get(key),
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
        since = utcnow() - timedelta(days=REMOVED_ROW_DAYS)
        removed = [row for row in self._removed
                   if row.removed_at >= since and instance_key(row.source, row.name) not in self._instances]
        return ServerWatchRead(
            server_id=self.config.server_id, state=self._state, since=self._since, message=self._message,
            docker=self._docker.status, docker_message=self._docker.message,
            found_at=self._found_at, read_at=self._read_at,
            instances=[self._instance_read(instance) for instance in instances],
            removed=removed,
            gpus=gpus, gpu_message=self._gpu_message,
            usage_interval_seconds=self._settings.usage_interval_seconds,
        )

    def summary(self) -> WatchSummaryRead:
        counts = Counter(instance.state for instance in self._instances.values())
        return WatchSummaryRead(server_id=self.config.server_id, state=self._state, since=self._since,
                                docker=self._docker.status, counts=dict(counts))
