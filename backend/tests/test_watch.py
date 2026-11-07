import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.enums import DockerStatus, InstanceState, WatchState, WorkspaceRole
from api.ssh.connect import Hop
from api.watch.docker import parse_inspect, parse_ps, probe_docker, target
from api.watch.frameworks import MetricSample, framework_for
from api.schemas.watch import GpuRead, GpuTotalsRead, ServerCountsRead, ServerWatchRead, WatchedInstanceRead
from api.watch.gpus import gpu_users, parse_gpus
from api.watch.overview import workspace_overview
from api.watch.server import PROBES_AT_ONCE, ServerWatch, WatchConfig
from api.watch.shell import CommandResult, _AnswerProgress, _response
from api.watch.states import Probe, instance_state
from api.watch.usage import UsageHistory
from api.watch.vllm import VLLM
from tests.helpers import (
    INSPECT_OUTPUT, METRICS_OLD, METRICS_V011, NVIDIA_SMI_OUTPUT, PS_OUTPUT, FakeSSHD, FakeVLLM, Sshd, docker_host,
    make_key, public_line,
)

T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)


# --- Making sense of what a GPU server answers: no SSH, just the parsing and arithmetic


class FakeRunner:
    def __init__(self, replies: dict[str, CommandResult]) -> None:
        self.replies, self.calls = replies, []

    async def run(self, command: str, stdin: str | None = None) -> CommandResult:
        self.calls.append((command, stdin))
        return next(reply for prefix, reply in self.replies.items() if command.startswith(prefix))


def _sample(prompt: float, gen: float, ttft_sum: float, ttft_count: float) -> MetricSample:
    return MetricSample(2.0, 0.0, 0.5, prompt, gen, ttft_sum, ttft_count)


def test_docker_access_falls_back_to_sudo() -> None:
    denied = CommandResult(1, "", "permission denied while trying to connect to the Docker daemon socket")
    needs = CommandResult(1, "", "sudo: a password is required")
    ok = CommandResult(0, PS_OUTPUT, "")
    runner = FakeRunner({"docker ": denied, "sudo -n ": needs, "sudo -S ": ok})
    access, ps = asyncio.run(probe_docker(runner, "pw"))
    assert (access.status, ps.stdout) == (DockerStatus.SUDO, PS_OUTPUT)
    command, stdin = runner.calls[-1]
    assert stdin == "pw\n" and "pw" not in command
    assert asyncio.run(probe_docker(FakeRunner({"docker ": ok}), "pw"))[0].status is DockerStatus.PLAIN
    no_password = FakeRunner({"docker ": denied, "sudo -n ": needs})
    assert asyncio.run(probe_docker(no_password, None))[0].status is DockerStatus.NEEDS_SUDO_PASSWORD
    rejected = CommandResult(1, "", "Sorry, try again.\nsudo: 1 incorrect password attempt")
    runner = FakeRunner({"docker ": denied, "sudo -n ": needs, "sudo -S ": rejected})
    assert asyncio.run(probe_docker(runner, "bad"))[0].status is DockerStatus.SUDO_PASSWORD_REJECTED
    missing = FakeRunner({"docker ": CommandResult(127, "", "bash: docker: command not found")})
    assert asyncio.run(probe_docker(missing, None))[0].message == "Docker isn't installed on this server."


def test_recognises_and_describes_vllm_containers() -> None:
    entries = parse_ps(PS_OUTPUT)
    assert [e.name for e in entries if framework_for(e.image, e.command)] == ["vllm-llama", "vllm-custom"]
    llama, custom = parse_inspect(INSPECT_OUTPUT)
    spec = VLLM().describe(llama)
    assert (spec.port, spec.model, spec.max_model_len, spec.api_key) == (
        8001, "meta-llama/Llama-3.1-8B-Instruct", 32768, None)
    assert target(llama, spec.port) == ("127.0.0.1", 18001)
    assert llama.gpus == ["0", "1"]
    spec = VLLM().describe(custom)
    assert (spec.port, spec.model, spec.api_key) == (8000, "Qwen/Qwen2.5-7B-Instruct", "custom-key")
    assert target(custom, 8000) == ("172.17.0.3", 8000)
    assert custom.env == {"VLLM_API_KEY": "custom-key"}
    assert "custom-key" not in repr(custom) and "hf_secret" not in repr(custom)


def test_reads_gpus_and_who_uses_them() -> None:
    gpus = parse_gpus(NVIDIA_SMI_OUTPUT)
    assert [(g.index, g.utilization, g.memory_used, g.memory_total, g.temperature) for g in gpus] == [
        (0, 94.0, 74100.0, 81559.0, 71.0), (1, 0.0, 0.0, 81559.0, None)]
    assert gpu_users(gpus, parse_inspect(INSPECT_OUTPUT)) == {0: ["vllm-llama"], 1: ["vllm-llama"]}


def test_instance_states() -> None:
    base = parse_inspect(INSPECT_OUTPUT)[0]
    running = replace(base, status="running")
    assert instance_state(running, Probe.HEALTHY, ever_ready=False) is InstanceState.READY
    assert instance_state(running, Probe.PORT_CLOSED, ever_ready=False) is InstanceState.STARTING
    assert instance_state(running, Probe.UNHEALTHY, ever_ready=True) is InstanceState.NOT_RESPONDING
    assert instance_state(running, Probe.CANT_REACH, ever_ready=True) is InstanceState.UNREACHABLE
    assert instance_state(replace(base, status="exited", exit_code=0), None, False) is InstanceState.STOPPED
    assert instance_state(replace(base, status="exited", exit_code=137), None, False) is InstanceState.CRASHED
    assert instance_state(replace(base, status="exited", exit_code=0, oom_killed=True), None, False) is InstanceState.CRASHED
    assert instance_state(replace(base, status="restarting"), None, True) is InstanceState.RESTARTING
    assert instance_state(replace(base, status="paused"), None, True) is InstanceState.PAUSED


def test_reads_vllm_metrics() -> None:
    sample = VLLM().read_metrics(METRICS_V011)
    assert (sample.running, sample.waiting) == (12.0, 3.0)
    assert sample.kv_cache == pytest.approx(0.6)
    assert (sample.prompt_tokens, sample.generation_tokens, sample.ttft_sum, sample.ttft_count) == (
        5000.0, 1200.0, 8.0, 20.0)
    old = VLLM().read_metrics(METRICS_OLD)
    assert (old.kv_cache, old.ttft_count) == (0.25, None)


def test_usage_rates_and_ttft_window() -> None:
    history = UsageHistory(length=90)
    first = history.add(_sample(1000, 100, 1.0, 4), T0)
    assert (first.running, first.kv_cache_percent, first.tokens_out_per_s, first.ttft_seconds) == (2.0, 50.0, None, None)
    second = history.add(_sample(1500, 300, 3.0, 8), T0 + timedelta(seconds=10))
    assert (second.tokens_in_per_s, second.tokens_out_per_s, second.ttft_seconds) == (50.0, 20.0, 0.5)
    third = history.add(_sample(1500, 300, 4.0, 10), T0 + timedelta(seconds=70))  # the first reading left the window
    assert third.ttft_seconds == 0.5
    assert [p.at for p in history.points] == [T0, T0 + timedelta(seconds=10), T0 + timedelta(seconds=70)]


def test_counter_reset_skips_interval() -> None:
    history = UsageHistory(length=3)
    history.add(_sample(5000, 900, 2.0, 10), T0)
    reset = history.add(_sample(40, 10, 0.1, 1), T0 + timedelta(seconds=10))
    assert (reset.tokens_in_per_s, reset.tokens_out_per_s, reset.ttft_seconds) == (None, None, None)
    after = history.add(_sample(140, 60, 0.4, 3), T0 + timedelta(seconds=20))
    assert (after.tokens_in_per_s, after.tokens_out_per_s) == (10.0, 5.0)
    assert after.ttft_seconds == pytest.approx(0.15)
    history.add(_sample(240, 110, 0.4, 3), T0 + timedelta(seconds=30))
    assert len(history.points) == 3


@pytest.mark.parametrize("answer", [
    b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nhel\r\n2;ext=1\r\nlo\r\n0\r\n\r\n",
])
def test_http_answer_complete_once_all_in(answer: bytes) -> None:
    # However the answer is split across reads, it's complete exactly when the whole body is in.
    for read_size in (1, 7, len(answer)):
        progress, raw, done = _AnswerProgress(), bytearray(), False
        for at in range(0, len(answer), read_size):
            raw += answer[at:at + read_size]
            if done := progress.complete(raw):
                break
        assert done and _response(bytes(raw)).body == "hello", read_size
    # Neither a length nor chunks: it ends only when the connection closes.
    assert not _AnswerProgress().complete(bytearray(b"HTTP/1.0 200 OK\r\n\r\nhello"))


def test_instances_are_probed_side_by_side() -> None:
    watch = ServerWatch(WatchConfig(server_id=1, hops=[], sudo_password=None), Settings(), asyncio.Semaphore(8), {})
    running = most = 0

    async def probe(shell: object, instance: str) -> None:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.05)
        running -= 1
        if instance == "lost":
            raise OSError("The connection was lost")

    watch._probe = probe  # type: ignore[method-assign]
    asyncio.run(watch._probe_all(None, ["ok"] * 6))  # type: ignore[arg-type]
    assert most == PROBES_AT_ONCE
    # The error itself, not an ExceptionGroup, so the watch sees a lost connection as before.
    with pytest.raises(OSError, match="connection was lost"):
        asyncio.run(watch._probe_all(None, ["ok", "lost", "ok"]))  # type: ignore[arg-type]


def _view(state: WatchState, docker: DockerStatus = DockerStatus.PLAIN, instances=(), gpus=None) -> ServerWatchRead:
    return ServerWatchRead.model_construct(state=state, docker=docker, instances=list(instances), gpus=gpus)


def test_workspace_overview_adds_up() -> None:
    def ready(model: str) -> WatchedInstanceRead:
        return WatchedInstanceRead.model_construct(state=InstanceState.READY, model=model)

    def gpu(used: float | None, total: float | None) -> GpuRead:
        return GpuRead.model_construct(memory_used_mib=used, memory_total_mib=total)

    crashed = WatchedInstanceRead.model_construct(state=InstanceState.CRASHED, model="org/Old-1B")
    overview = workspace_overview(7, [
        _view(WatchState.CONNECTED, instances=[ready("meta/Llama-70B"), ready("meta/Llama-70B"), crashed],
              gpus=[gpu(1000.0, 2000.0), gpu(None, 2000.0)]),
        # Down: what it last saw stays in its view, but isn't current, so none of it counts.
        _view(WatchState.UNREACHABLE, instances=[ready("stale/Gone-7B")], gpus=[gpu(500.0, 1000.0)]),
        _view(WatchState.CONNECTED, docker=DockerStatus.NEEDS_SUDO_PASSWORD),
        _view(WatchState.NOT_TESTED),
    ])
    assert overview.servers == ServerCountsRead(total=4, up=1, not_tested=1, unreachable=1, trouble=1, docker_problem=1)
    assert overview.instances == {InstanceState.READY: 2, InstanceState.CRASHED: 1}
    assert overview.gpus == GpuTotalsRead(count=2, memory_used_mib=1000.0, memory_total_mib=2000.0)
    assert overview.models == ["meta/Llama-70B"]  # ready only, once each
    assert workspace_overview(8, [_view(WatchState.CONNECTED, gpus=[])]).gpus is None
    assert workspace_overview(9, [_view(WatchState.CONNECTED, gpus=[gpu(None, None)])]).gpus == GpuTotalsRead(
        count=1, memory_used_mib=None, memory_total_mib=None)


# --- One server's watcher, against an in-process SSH server


def _watch(host: FakeSSHD, host_key: str | None = None) -> ServerWatch:
    hop = Hop(name="gpu-7", host=host.host, port=host.port, username="ubuntu", password="ssh-pw",
              client_key=None, host_key=host_key or public_line(host.host_key))
    settings = Settings(usage_interval_seconds=0.1, discovery_interval_seconds=0.3, ssh_connect_timeout=2.0)
    return ServerWatch(WatchConfig(server_id=1, hops=[hop], sudo_password="ssh-pw"), settings, asyncio.Semaphore(8), {})


async def _until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.05)


def test_unreachable_keeps_last_known(sshd: Sshd, fake_vllm: FakeVLLM) -> None:
    host = sshd(password="ssh-pw", commands=docker_host(fake_vllm, sudo_password="ssh-pw"))
    watch = _watch(host)

    async def scenario() -> None:
        task = asyncio.create_task(watch.run())
        await _until(lambda: bool(watch.view().instances))
        await asyncio.to_thread(host.stop)
        await _until(lambda: watch.view().state is WatchState.UNREACHABLE)
        task.cancel()

    asyncio.run(scenario())
    view = watch.view()
    assert view.since is not None and [i.name for i in view.instances] == ["vllm-llama"]


def test_changed_host_key_stops_watching(sshd: Sshd, fake_vllm: FakeVLLM) -> None:
    host = sshd(password="ssh-pw", commands=docker_host(fake_vllm, sudo_password="ssh-pw"))
    watch = _watch(host, host_key=public_line(make_key()[1]))
    asyncio.run(asyncio.wait_for(watch.run(), 10))  # returns by itself
    assert watch.view().state is WatchState.HOST_KEY_CHANGED and watch.stopped_at is not None
    assert host.auth_attempts == []  # checked before any credential is sent


# --- The watch API, with the app's own watcher running


@pytest.fixture
def watching(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the watcher on with fast rounds. List it before `client` in a test's arguments."""
    for name, value in {"VSERVX_WATCH_ENABLED": "true", "VSERVX_USAGE_INTERVAL_SECONDS": "0.1",
                        "VSERVX_DISCOVERY_INTERVAL_SECONDS": "0.3", "VSERVX_SSH_CONNECT_TIMEOUT": "2"}.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def _wait(get: Callable[[], Any], predicate: Callable[[Any], bool], timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    value = None
    while time.monotonic() < deadline:
        if predicate(value := get()):
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out; last value: {value}")


def _watched_server(api: TestClient, w: str, host: FakeSSHD) -> int:
    body = {"name": "gpu-7", "host": host.host, "port": host.port, "username": "ubuntu",
            "auth_type": "password", "password": "ssh-pw"}
    server_id = api.post(f"{w}/servers", json=body).json()["id"]
    assert api.post(f"{w}/servers/{server_id}/test").json()["ok"]  # records the host key, wakes the watcher
    return server_id


def _state(api: TestClient, w: str, server_id: int) -> str:
    return api.get(f"{w}/servers/{server_id}/watch").json()["state"]


def _has_rates(view: dict) -> bool:
    return bool(view["instances"]) and (view["instances"][0]["usage"] or {}).get("tokens_out_per_s") is not None


def test_watch_api_shows_instances_without_secrets(
    watching: None, client: TestClient, api: TestClient, w: str, sshd: Sshd, fake_vllm: FakeVLLM,
    member_headers: Callable[[WorkspaceRole], dict[str, str]], outsider_headers: dict[str, str],
) -> None:
    host = sshd(password="ssh-pw", commands=docker_host(fake_vllm, sudo_password="ssh-pw"))
    server_id = _watched_server(api, w, host)
    view_path = f"{w}/servers/{server_id}/watch"
    history_path = f"{w}/servers/{server_id}/instances/vllm-llama/history"
    view = _wait(lambda: api.get(view_path).json(), _has_rates)
    [llama] = view["instances"]
    assert (view["state"], view["docker"], llama["state"]) == ("connected", "sudo", "ready")
    # max_model_len comes from /v1/models, which only answers with the container's API key.
    assert (llama["model"], llama["max_model_len"], llama["version"]) == (
        "meta-llama/Llama-3.1-8B-Instruct", 32768, "0.11.0")
    assert [(g["index"], g["instances"]) for g in view["gpus"]] == [(0, ["vllm-llama"]), (1, [])]
    assert api.get(f"{w}/watch").json() == [
        {"server_id": server_id, "state": "connected", "since": view["since"], "docker": "sudo", "counts": {"ready": 1}}]
    assert len(api.get(history_path).json()["points"]) >= 2
    assert api.get(f"{w}/servers/{server_id}/instances/nope/history").status_code == 404
    viewer = member_headers(WorkspaceRole.VIEWER)
    assert client.post(f"{w}/servers/{server_id}/refresh", headers=viewer).status_code == 200
    for path in (f"{w}/watch", view_path, history_path):
        assert client.get(path, headers=outsider_headers).status_code == 404
    everything = "".join(api.get(path).text for path in (f"{w}/watch", view_path, history_path, f"{w}/servers"))
    for secret in ("ssh-pw", "vllm-key", "hf_secret"):
        assert secret not in everything


def test_watch_follows_server_changes(
    watching: None, client: TestClient, api: TestClient, w: str, sshd: Sshd, fake_vllm: FakeVLLM,
) -> None:
    host = sshd(password="ssh-pw", commands=docker_host(fake_vllm, sudo_password="ssh-pw"))
    server_id = _watched_server(api, w, host)
    _wait(lambda: _state(api, w, server_id), lambda state: state == "connected")
    api.patch(f"{w}/servers/{server_id}", json={"password": "wrong"})
    _wait(lambda: _state(api, w, server_id), lambda state: state == "sign_in_failed")
    attempts = len(host.auth_attempts)
    time.sleep(0.5)
    assert len(host.auth_attempts) == attempts  # a rejected password isn't retried
    api.patch(f"{w}/servers/{server_id}", json={"password": "ssh-pw"})
    _wait(lambda: _state(api, w, server_id), lambda state: state == "connected")
    assert api.delete(f"{w}/servers/{server_id}").status_code == 204
    assert api.get(f"{w}/watch").json() == []
    assert api.get(f"{w}/servers/{server_id}/watch").status_code == 404
