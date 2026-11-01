"""What a GPU server answers, as vservx sees it: `docker ps`, `docker inspect` in INSPECT_FORMAT's
shape, `nvidia-smi`, and vLLM's /metrics."""

import json

_PS = [
    {"ID": "a1", "Names": "vllm-llama", "Image": "vllm/vllm-openai:v0.11.0", "State": "running",
     "Command": '"vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8001 --max-model-len 32768"',
     "Status": "Up 3 days"},
    {"ID": "b2", "Names": "vllm-custom", "Image": "registry.local/llm:2026.10", "State": "running",
     "Command": '"python3 -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-7B-Instruct"',
     "Status": "Up 6 hours"},
    {"ID": "c3", "Names": "nginx", "Image": "nginx:1.27", "State": "running",
     "Command": "\"/docker-entrypoint.sh nginx -g 'daemon off;'\"", "Status": "Up 3 days"},
]
PS_OUTPUT = "\n".join(json.dumps(line) for line in _PS) + "\n"


def _state(status: str = "running", exit_code: int = 0, oom_killed: bool = False) -> dict:
    return {"Status": status, "Running": status == "running", "Paused": status == "paused",
            "Restarting": status == "restarting", "OOMKilled": oom_killed, "Dead": status == "dead",
            "Pid": 4242, "ExitCode": exit_code, "Error": "",
            "StartedAt": "2026-10-29T08:00:00.123456789Z", "FinishedAt": "0001-01-01T00:00:00Z"}


def inspect_line(**fields: object) -> str:
    """One line of `docker inspect --format INSPECT_FORMAT`; fields override the vllm-llama defaults."""
    line = {
        "name": "/vllm-llama", "image": "vllm/vllm-openai:v0.11.0", "path": "vllm",
        "args": ["serve", "meta-llama/Llama-3.1-8B-Instruct", "--port", "8001", "--max-model-len", "32768"],
        "state": _state(), "restart_count": 0, "network_mode": "bridge",
        "ports": {"8001/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18001"}]},
        "networks": {"bridge": {"IPAddress": "172.17.0.2", "Gateway": "172.17.0.1"}},
        "device_requests": [{"Driver": "", "Count": 0, "DeviceIDs": ["0", "1"], "Capabilities": [["gpu"]]}],
        "env": [None],
    }
    return json.dumps(line | fields)


INSPECT_OUTPUT = "\n".join([
    inspect_line(),
    inspect_line(
        name="/vllm-custom", image="registry.local/llm:2026.10", path="python3",
        args=["-m", "vllm.entrypoints.openai.api_server", "--model", "Qwen/Qwen2.5-7B-Instruct"],
        ports={}, networks={"bridge": {"IPAddress": "172.17.0.3"}}, device_requests=None,
        env=["VLLM_API_KEY=custom-key", "HF_TOKEN=hf_secret", None],
    ),
]) + "\n"

NVIDIA_SMI_OUTPUT = (
    "0, GPU-aaa, NVIDIA H100 80GB HBM3, 94, 74100, 81559, 71\n"
    "1, GPU-bbb, NVIDIA H100 80GB HBM3, 0, 0, 81559, [N/A]\n"
)


def metrics_text(prompt_tokens: float = 5000, generation_tokens: float = 1200) -> str:
    """/metrics of a recent vLLM with two engines (data parallel), in Prometheus text format."""
    labels = 'engine="{}",model_name="meta-llama/Llama-3.1-8B-Instruct"'
    return "\n".join([
        "# HELP vllm:num_requests_running Number of requests in model execution batches.",
        "# TYPE vllm:num_requests_running gauge",
        f"vllm:num_requests_running{{{labels.format(0)}}} 7.0",
        f"vllm:num_requests_running{{{labels.format(1)}}} 5.0",
        "# TYPE vllm:num_requests_waiting gauge",
        f"vllm:num_requests_waiting{{{labels.format(0)}}} 3.0",
        "# TYPE vllm:kv_cache_usage_perc gauge",
        f"vllm:kv_cache_usage_perc{{{labels.format(0)}}} 0.5",
        f"vllm:kv_cache_usage_perc{{{labels.format(1)}}} 0.7",
        "# TYPE vllm:prompt_tokens_total counter",
        f"vllm:prompt_tokens_total{{{labels.format(0)}}} {prompt_tokens}",
        f"vllm:prompt_tokens_created{{{labels.format(0)}}} 1.7617e+09",
        "# TYPE vllm:generation_tokens_total counter",
        f"vllm:generation_tokens_total{{{labels.format(0)}}} {generation_tokens}",
        "# TYPE vllm:time_to_first_token_seconds histogram",
        f'vllm:time_to_first_token_seconds_bucket{{{labels.format(0)},le="0.1"}} 5.0',
        f'vllm:time_to_first_token_seconds_bucket{{{labels.format(0)},le="+Inf"}} 20.0',
        f"vllm:time_to_first_token_seconds_count{{{labels.format(0)}}} 20.0",
        f"vllm:time_to_first_token_seconds_sum{{{labels.format(0)}}} 8.0",
        "",
    ])


METRICS_V011 = metrics_text()

# Before the KV cache metric's rename (vLLM v0.10 and older), with no time-to-first-token yet.
METRICS_OLD = "\n".join([
    'vllm:num_requests_running{model_name="m"} 1.0',
    'vllm:num_requests_waiting{model_name="m"} 0.0',
    'vllm:gpu_cache_usage_perc{model_name="m"} 0.25',
    'vllm:prompt_tokens_total{model_name="m"} 10.0',
    'vllm:generation_tokens_total{model_name="m"} 20.0',
    "",
])
