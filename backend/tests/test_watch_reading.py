from dataclasses import replace

from api.enums import InstanceState
from api.watch.docker import parse_inspect, parse_ps, target
from api.watch.frameworks import framework_for
from api.watch.gpus import gpu_users, parse_gpus
from api.watch.states import Probe, instance_state
from api.watch.vllm import VLLM
from tests.watch_samples import INSPECT_OUTPUT, NVIDIA_SMI_OUTPUT, PS_OUTPUT


def test_recognises_vllm_containers_only() -> None:
    entries = parse_ps(PS_OUTPUT)
    assert [e.name for e in entries if framework_for(e.image, e.command)] == ["vllm-llama", "vllm-custom"]


def test_describes_vllm_containers() -> None:
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
