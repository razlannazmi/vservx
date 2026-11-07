"""Launch snapshots: secret rules, launch settings from docker inspect, the rebuilt command,
and differences between two snapshots."""

from datetime import UTC, datetime

from api.db.crypto import init_crypto
from api.snapshots.command import docker_run
from api.snapshots.config import LaunchConfig, config_from_json, config_to_json, launch_config
from api.snapshots.diff import Difference, Point, differences, same_launch
from api.snapshots.fingerprint import check_key, fingerprint
from api.snapshots.secrets import is_secret_env, mask_args
from api.watch.docker import ImageDefaults, is_template_error, parse_image_inspect, parse_inspect
from api.watch.shell import CommandResult
from tests.helpers import DEFAULT_HOST, image_line, inspect_line


def test_secret_env_names() -> None:
    for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "VLLM_API_KEY", "OPENAI_API_KEY",
                 "AWS_SECRET_ACCESS_KEY", "WANDB_API_KEY", "DB_PASSWORD", "MY_KEY", "hf_token"):
        assert is_secret_env(name), name
    for name in ("VLLM_ATTENTION_BACKEND", "CUDA_VISIBLE_DEVICES", "KEYBOARD", "HF_HOME", "NVIDIA_VISIBLE_DEVICES"):
        assert not is_secret_env(name), name


def test_mask_args() -> None:
    assert mask_args(["serve", "m", "--api-key", "k1", "--hf-token=hf_x", "--tokenizer", "t", "--api-key"]) == [
        "serve", "m", "--api-key", "<VLLM_API_KEY>", "--hf-token=<HF_TOKEN>", "--tokenizer", "t", "--api-key"]
    assert mask_args(["-c", "vllm serve m --api-key 'k 2' --port 8000"]) == [
        "-c", "vllm serve m --api-key <VLLM_API_KEY> --port 8000"]


def test_inspect_keeps_launch_settings_but_no_secret_values() -> None:
    # The template already sent HF_TOKEN as a bare name; MY_SECRET slipped through and must be caught on arrival.
    [c] = parse_inspect(inspect_line(env=["VLLM_API_KEY=k1", "HF_TOKEN", "OPTS=a=b c", "MY_SECRET=leak", None]) + "\n")
    assert c.id.startswith("4ab1e07c9d10") and c.image_id.startswith("sha256:")
    assert c.created_at == datetime(2026, 11, 7, 14, 32, 0, 500000, tzinfo=UTC)
    assert c.env == {"VLLM_API_KEY": "k1"}
    assert c.launch.env == ("HF_TOKEN", "MY_SECRET", "OPTS=a=b c", "VLLM_API_KEY")
    assert c.launch.env_values_hidden is False
    assert "leak" not in repr(c) and "k1" not in repr(c)


def test_image_defaults_and_template_errors() -> None:
    [(image_id, defaults)] = parse_image_inspect(image_line(env=["PATH=/usr/bin", "HF_TOKEN", None]) + "\n").items()
    assert image_id.startswith("sha256:") and defaults.entrypoint == ("vllm",)
    assert defaults.env == frozenset({"PATH=/usr/bin", "HF_TOKEN"})
    assert is_template_error(CommandResult(1, "", 'template parsing error: template: :1: function "upper" not defined'))
    assert not is_template_error(CommandResult(1, "", "Error: No such object: vllm-x"))


IMAGE = ImageDefaults(entrypoint=("vllm",), cmd=(), env=frozenset({"PATH=/usr/bin"}), user="", workdir="")
QWEN_ARGS = ["serve", "Qwen/Qwen2.5-32B-Instruct", "--max-model-len", "16384", "--api-key", "k1"]
QWEN = dict(
    name="/vllm-qwen", image="vllm/vllm-openai:v0.7.1", path="vllm", args=QWEN_ARGS, entrypoint=["vllm"], cmd=QWEN_ARGS,
    device_requests=[{"Count": 0, "DeviceIDs": ["0", "1"], "Capabilities": [["gpu"]]}],
    host=DEFAULT_HOST | {"port_bindings": {"8000/tcp": [{"HostIp": "", "HostPort": "8000"}]}, "ipc_mode": "host",
                         "restart_policy": {"Name": "unless-stopped", "MaximumRetryCount": 0}},
    mounts=[{"Type": "bind", "Source": "/data/hf", "Destination": "/root/.cache/huggingface", "RW": True}],
    env=["VLLM_API_KEY=k1", "HF_TOKEN", "OPTS=a=b c", "PATH=/usr/bin", None],
)


def _container(fields: dict, hidden: bool = False):
    return parse_inspect(inspect_line(**fields) + "\n", env_values_hidden=hidden)[0]


def test_docker_run_from_a_container() -> None:
    config = launch_config(_container(QWEN), IMAGE)
    assert docker_run("vllm-qwen", config) == (
        "docker run -d --name vllm-qwen \\\n"
        "  --gpus '\"device=0,1\"' \\\n"
        "  --ipc host \\\n"
        "  -p 8000:8000 \\\n"
        "  -v /data/hf:/root/.cache/huggingface \\\n"
        "  -e HF_TOKEN=<HF_TOKEN> \\\n"
        "  -e 'OPTS=a=b c' \\\n"
        "  -e VLLM_API_KEY=<VLLM_API_KEY> \\\n"
        "  --restart unless-stopped \\\n"
        "  vllm/vllm-openai:v0.7.1 \\\n"
        "  serve \\\n"
        "  Qwen/Qwen2.5-32B-Instruct \\\n"
        "  --max-model-len 16384 \\\n"
        "  --api-key <VLLM_API_KEY>")
    assert config_from_json(config_to_json(config)) == config
    # Docker listing the same things in another order is not a change.
    shuffled = QWEN | {"env": ["PATH=/usr/bin", "OPTS=a=b c", "HF_TOKEN", "VLLM_API_KEY=k1", None]}
    assert launch_config(_container(shuffled), IMAGE) == config


def test_docker_run_with_entrypoint_and_hidden_env() -> None:
    fields = dict(path="python3", entrypoint=["python3", "-m", "vllm.entrypoints.openai.api_server"],
                  cmd=["--model", "m"], env=["CUDA_VISIBLE_DEVICES", None])
    config = launch_config(_container(fields, hidden=True), IMAGE)
    lines = docker_run("x", config).splitlines()
    assert config.env_values_hidden
    assert "  -e CUDA_VISIBLE_DEVICES=<CUDA_VISIBLE_DEVICES> \\" in lines
    assert "  --entrypoint python3 \\" in lines and "  -m vllm.entrypoints.openai.api_server \\" in lines
    assert lines[-1] == "  --model m"


def test_differences_between_any_two() -> None:
    a = Point("c1" * 6, "sha256:a", LaunchConfig("vllm/vllm-openai:v0.6.3", args=("m", "--max-model-len", "8192")), "aaaa1111", "k1")
    b = Point("c2" * 6, "sha256:b", LaunchConfig("vllm/vllm-openai:v0.7.1", args=("m", "--max-model-len", "16384"),
                                                env=("HF_TOKEN", "VLLM_ATTENTION_BACKEND=FLASHINFER")), "bbbb2222", "k1")
    assert differences(a, b) == [
        Difference("image", "vllm/vllm-openai:v0.6.3", "vllm/vllm-openai:v0.7.1"),
        Difference("--max-model-len", "8192", "16384"),
        Difference("-e HF_TOKEN", None, "<HF_TOKEN>"),
        Difference("-e VLLM_ATTENTION_BACKEND", None, "FLASHINFER"),
        Difference("API key", "aaaa1111", "bbbb2222"),
        Difference("container", "c1" * 6, "c2" * 6),
    ]
    repulled = Point("c3" * 6, "sha256:z", a.config, "aaaa1111", "k1")
    assert differences(a, repulled)[0] == Difference("image", "vllm/vllm-openai:v0.6.3", "vllm/vllm-openai:v0.6.3", "re-pulled")
    rekeyed = Point("c1" * 6, "sha256:a", a.config, "ffff0000", "k2")
    assert same_launch(a, rekeyed)
    assert Difference("API key", None, None, "can't compare (vservx's key file was replaced)") in differences(a, rekeyed)


def test_fingerprint_checks(tmp_path) -> None:
    init_crypto(tmp_path / "secret.key")
    stored, key_id = fingerprint("vllm-key")
    assert len(stored) == 8 and fingerprint("vllm-key") == (stored, key_id) and "vllm" not in stored
    assert check_key(" vllm-key\n", stored, key_id) is True
    assert check_key("other", stored, key_id) is False
    assert check_key("vllm-key", stored, "00000000") is None
