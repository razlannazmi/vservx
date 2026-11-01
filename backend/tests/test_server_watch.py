import asyncio
from collections.abc import Callable

from api.enums import DockerStatus, InstanceState, WatchState
from api.watch.server import ServerWatch, WatchConfig
from tests.helpers import make_key, public_line
from tests.sshd import FakeSSHD
from tests.watch_fakes import FakeVLLM, config_for, docker_host, fast_settings, until

Sshd = Callable[..., FakeSSHD]


def _watch(config: WatchConfig) -> ServerWatch:
    return ServerWatch(config, fast_settings(), asyncio.Semaphore(8), {})


def _ready_with_rates(watch: ServerWatch) -> bool:
    view = watch.view()
    return (bool(view.instances) and view.instances[0].usage is not None
            and view.instances[0].usage.tokens_out_per_s is not None)


def test_watch_reads_instances_usage_and_gpus(sshd: Sshd, fake_vllm: FakeVLLM) -> None:
    host = sshd(password="ssh-pw", commands=docker_host(fake_vllm, sudo_password="ssh-pw"))
    watch = _watch(config_for(host))

    async def scenario() -> None:
        task = asyncio.create_task(watch.run())
        await until(lambda: _ready_with_rates(watch))
        task.cancel()

    asyncio.run(scenario())
    view = watch.view()
    assert (view.state, view.docker) == (WatchState.CONNECTED, DockerStatus.SUDO)
    [llama] = view.instances
    assert (llama.name, llama.state, llama.model, llama.max_model_len, llama.version) == (
        "vllm-llama", InstanceState.READY, "meta-llama/Llama-3.1-8B-Instruct", 32768, "0.11.0")
    assert fake_vllm.authorized_model_requests >= 1
    assert [(g.index, g.instances) for g in view.gpus or []] == [(0, ["vllm-llama"]), (1, [])]
    text = view.model_dump_json()
    assert "vllm-key" not in text and "hf_secret" not in text and "ssh-pw" not in text


def test_unreachable_keeps_last_known(sshd: Sshd, fake_vllm: FakeVLLM) -> None:  # Review Focus 2
    host = sshd(password="ssh-pw", commands=docker_host(fake_vllm, sudo_password="ssh-pw"))
    watch = _watch(config_for(host))

    async def scenario() -> None:
        task = asyncio.create_task(watch.run())
        await until(lambda: bool(watch.view().instances))
        await asyncio.to_thread(host.stop)
        await until(lambda: watch.view().state is WatchState.UNREACHABLE)
        task.cancel()

    asyncio.run(scenario())
    view = watch.view()
    assert view.since is not None and [i.name for i in view.instances] == ["vllm-llama"]


def test_changed_host_key_stops_watching(sshd: Sshd, fake_vllm: FakeVLLM) -> None:  # Review Focus 3
    host = sshd(password="ssh-pw", commands=docker_host(fake_vllm, sudo_password="ssh-pw"))
    watch = _watch(config_for(host, host_key=public_line(make_key()[1])))
    asyncio.run(asyncio.wait_for(watch.run(), 10))  # returns by itself
    assert watch.view().state is WatchState.HOST_KEY_CHANGED and watch.stopped_at is not None
    assert host.auth_attempts == []  # checked before any credential is sent
