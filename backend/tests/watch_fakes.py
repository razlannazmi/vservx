"""A GPU server for watching tests: Docker behind sudo, nvidia-smi, and vLLM's HTTP endpoints."""

import asyncio
import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from api.config import Settings
from api.ssh.connect import Hop
from api.watch.server import WatchConfig
from tests.helpers import public_line
from tests.sshd import Commands, FakeSSHD
from tests.watch_samples import NVIDIA_SMI_OUTPUT, inspect_line, metrics_text

API_KEY = "vllm-key"
MODEL = "meta-llama/Llama-3.1-8B-Instruct"


class FakeVLLM:
    """vLLM's endpoints on 127.0.0.1. /v1/models needs the API key, as with `--api-key`, and the
    token counters grow by 100 on every read of /metrics."""

    def __init__(self) -> None:
        self.authorized_model_requests = 0
        self._prompt_tokens = 5000
        self._generation_tokens = 1200
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, body = fake._answer(self.path, self.headers.get("Authorization"))
                encoded = body.encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port: int = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def _answer(self, path: str, authorization: str | None) -> tuple[int, str]:
        with self._lock:
            if path == "/health":
                return 200, ""
            if path == "/version":
                return 200, json.dumps({"version": "0.11.0"})
            if path == "/v1/models":
                if authorization != f"Bearer {API_KEY}":
                    return 401, json.dumps({"error": "Unauthorized"})
                self.authorized_model_requests += 1
                return 200, json.dumps({"object": "list", "data": [{"id": MODEL, "max_model_len": 32768}]})
            if path == "/metrics":
                self._prompt_tokens += 100
                self._generation_tokens += 100
                return 200, metrics_text(self._prompt_tokens, self._generation_tokens)
            return 404, ""

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def docker_host(vllm: FakeVLLM, *, sudo_password: str) -> Commands:
    """Answers like a GPU server where docker needs sudo with a password: one vLLM container on
    the host network (its port is `vllm`'s, so port forwards reach it), plus nginx."""
    ps = "\n".join(json.dumps(row) for row in [
        {"Names": "vllm-llama", "Image": "vllm/vllm-openai:v0.11.0", "State": "running",
         "Command": f'"vllm serve {MODEL} --port {vllm.port}"'},
        {"Names": "nginx", "Image": "nginx:1.27", "State": "running", "Command": '"nginx -g daemon off;"'},
    ]) + "\n"
    inspect = inspect_line(
        args=["serve", MODEL, "--port", str(vllm.port)], network_mode="host", ports={}, networks={"host": {}},
        device_requests=[{"Count": 0, "DeviceIDs": ["0"], "Capabilities": [["gpu"]]}],
        env=[f"VLLM_API_KEY={API_KEY}", "HF_TOKEN=hf_secret", None],
    ) + "\n"

    def answer(command: str, stdin: str) -> tuple[str, str, int]:
        if command == "hostname":
            return "gpu-7\n", "", 0
        if command.startswith("docker "):
            return "", "permission denied while trying to connect to the Docker daemon socket\n", 1
        if command.startswith("sudo -n "):
            return "", "sudo: a password is required\n", 1
        if command.startswith("sudo -S "):
            if stdin != sudo_password + "\n":
                return "", "Sorry, try again.\nsudo: 1 incorrect password attempt\n", 1
            args = command.split(" docker ", 1)[1]
            if args.startswith("ps "):
                return ps, "", 0
            if args.startswith("inspect "):
                return inspect, "", 0
        if command.startswith("nvidia-smi "):
            return NVIDIA_SMI_OUTPUT, "", 0
        return "", f"bash: {command.split()[0]}: command not found\n", 127

    return answer


def fast_settings() -> Settings:
    return Settings(usage_interval_seconds=0.1, discovery_interval_seconds=0.3, ssh_connect_timeout=2.0)


def config_for(host: FakeSSHD, *, password: str = "ssh-pw", host_key: str | None = None) -> WatchConfig:
    hop = Hop(name="gpu-7", host=host.host, port=host.port, username="ubuntu", password=password,
              client_key=None, host_key=host_key or public_line(host.host_key))
    return WatchConfig(server_id=1, hops=[hop], sudo_password=password)


async def until(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.05)
