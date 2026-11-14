"""Shared test constants, helpers and fakes. Fixtures live in conftest.py."""

import asyncio
import json
import shlex
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import asyncssh
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

ADMIN = {"email": "admin@example.com", "password": "admin-password"}
USER_PASSWORD = "user-password"

# Type of the `db` fixture: runs fn(session) against the test database and returns its result.
Db = Callable[[Callable[[AsyncSession], Awaitable[Any]]], Any]


def login_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def make_key(passphrase: str | None = None, algorithm: str = "ssh-ed25519") -> tuple[str, asyncssh.SSHKey]:
    """A fresh key: the private key text a user would paste, and the key itself."""
    key = asyncssh.generate_private_key(algorithm)
    return key.export_private_key("openssh", passphrase).decode(), key


def public_line(key: asyncssh.SSHKey) -> str:
    return key.export_public_key().decode().strip()


def create_saved_key(
    client: TestClient, base: str, name: str = "lab-key", passphrase: str | None = None
) -> tuple[int, asyncssh.SSHKey]:
    """Save a fresh key through the API into the workspace at base ("/api/workspaces/<id>").
    The client must carry an operator's headers."""
    text, key = make_key(passphrase)
    body = {"name": name, "private_key": text, "passphrase": passphrase}
    response = client.post(f"{base}/ssh-keys", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"], key


# --- An in-process SSH server. It runs on its own event loop thread so it outlives the event
# loop of each asyncio.run() or TestClient request that connects to it.

# (command, stdin) -> (stdout, stderr, exit status)
Commands = Callable[[str, str], tuple[str, str, int]]


class BackgroundLoop:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=30)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join()


class _Server(asyncssh.SSHServer):
    def __init__(self, fake: "FakeSSHD") -> None:
        self._fake = fake

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self._fake.connections.append(conn)

    def begin_auth(self, username: str) -> bool:
        return True  # always require authentication

    def password_auth_supported(self) -> bool:
        return self._fake.password is not None

    def validate_password(self, username: str, password: str) -> bool:
        self._fake.auth_attempts.append("password")
        return password == self._fake.password

    def public_key_auth_supported(self) -> bool:
        return self._fake.client_key is not None

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        self._fake.auth_attempts.append("publickey")
        return self._fake.client_key is not None and key.public_data == self._fake.client_key.public_data

    def connection_requested(self, dest_host: str, dest_port: int, orig_host: str, orig_port: int) -> bool:
        return True  # lets it act as a jump host


class FakeSSHD:
    """Accepts the given password and/or client key and answers any command with its hostname,
    or with `commands` when given. Port forwards go straight through, like a jump host's."""

    def __init__(
        self,
        loop: BackgroundLoop,
        *,
        password: str | None = None,
        client_key: asyncssh.SSHKey | None = None,
        hostname: str = "fake-host",
        commands: Commands | None = None,
    ) -> None:
        self.password = password
        self.client_key = client_key
        self.hostname = hostname
        self.commands = commands
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.auth_attempts: list[str] = []
        self.connections: list[asyncssh.SSHServerConnection] = []
        self.host = "127.0.0.1"
        self._loop = loop

        async def start() -> asyncssh.SSHAcceptor:
            return await asyncssh.create_server(
                lambda: _Server(self), self.host, 0, server_host_keys=[self.host_key], process_factory=self._handle,
            )

        self._acceptor = loop.run(start())
        self.port: int = self._acceptor.get_port()

    async def _handle(self, process: asyncssh.SSHServerProcess) -> None:
        if self.commands is None:
            process.stdout.write(f"{self.hostname}\n")
            process.exit(0)
            return
        command = process.command or ""
        # Only these commands are given anything on stdin; waiting for EOF on others would hang.
        stdin = await process.stdin.read() if command.startswith("sudo -S") or "-H @-" in command else ""
        stdout, stderr, status = self.commands(command, stdin)
        process.stdout.write(stdout)
        process.stderr.write(stderr)
        process.exit(status)

    def stop(self) -> None:
        """Stop listening and drop every open connection, like a server going off the network."""

        async def stop() -> None:
            self._acceptor.close()
            for connection in self.connections:
                connection.close()

        self._loop.run(stop())

    def close(self) -> None:
        async def stop() -> None:
            self._acceptor.close()
            # wait_closed waits for open connections too, such as a watcher's that outlives the test.
            for connection in self.connections:
                connection.close()
            await self._acceptor.wait_closed()

        self._loop.run(stop())


# Type of the `sshd` fixture: starts a FakeSSHD with the given keyword arguments.
Sshd = Callable[..., FakeSSHD]


# --- What a GPU server answers, as vservx sees it: `docker ps`, `docker inspect` in
# INSPECT_FORMAT's shape, `nvidia-smi`, and vLLM's /metrics.

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


# The HostConfig fields INSPECT_FORMAT sends under "host", as Docker reports a plain `docker run`.
DEFAULT_HOST = {
    "port_bindings": {"8001/tcp": [{"HostIp": "", "HostPort": "18001"}]},
    "ipc_mode": "private", "pid_mode": "", "shm_size": 67108864,
    "restart_policy": {"Name": "no", "MaximumRetryCount": 0}, "runtime": "runc",
    "ulimits": None, "devices": None, "privileged": False, "cap_add": None, "cap_drop": None,
}

_LLAMA_ARGS = ["serve", "meta-llama/Llama-3.1-8B-Instruct", "--port", "8001", "--max-model-len", "32768"]


def inspect_line(**fields: object) -> str:
    """One line of `docker inspect --format INSPECT_FORMAT`; fields override the vllm-llama defaults."""
    line = {
        "id": "4ab1e07c9d10" + "0" * 52, "created": "2026-11-07T14:32:00.500000123Z", "image_id": "sha256:" + "b" * 64,
        "name": "/vllm-llama", "image": "vllm/vllm-openai:v0.11.0", "path": "vllm",
        "args": _LLAMA_ARGS, "entrypoint": ["vllm"], "cmd": _LLAMA_ARGS,
        "state": _state(), "restart_count": 0, "network_mode": "bridge",
        "ports": {"8001/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18001"}]},
        "networks": {"bridge": {"IPAddress": "172.17.0.2", "Gateway": "172.17.0.1"}},
        "device_requests": [{"Driver": "", "Count": 0, "DeviceIDs": ["0", "1"], "Capabilities": [["gpu"]]}],
        "host": DEFAULT_HOST, "mounts": [], "user": "", "workdir": "",
        "compose": {"project": "", "working_dir": "", "config_files": ""},
        "env": [None],
    }
    return json.dumps(line | fields)


def image_line(**fields: object) -> str:
    """One line of `docker inspect --type image --format IMAGE_FORMAT`."""
    line = {"id": "sha256:" + "b" * 64, "entrypoint": ["vllm"], "cmd": None, "user": "", "workdir": "", "env": [None]}
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


# --- A GPU server for watching tests: Docker behind sudo, nvidia-smi, and vLLM's HTTP endpoints.

VLLM_API_KEY = "vllm-key"
MODEL = "meta-llama/Llama-3.1-8B-Instruct"


class FakeVLLM:
    """vLLM's endpoints on 127.0.0.1. /v1/models needs the API key, as with `--api-key`, and the
    token counters grow by 100 on every read of /metrics. Like the servers seen in the field, it
    keeps the connection open after a complete answer until the client hangs up."""

    def __init__(self) -> None:
        self.version = "0.11.0"
        self._prompt_tokens = 5000
        self._generation_tokens = 1200
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, body = fake._answer(self.path, self.headers.get("Authorization"))
                encoded = body.encode()
                self.send_response(status)
                if self.path == "/metrics":
                    # As uvicorn with httptools answers when the app gives no length: chunked, even to HTTP/1.0.
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    half = len(encoded) // 2
                    for part in (encoded[:half], encoded[half:], b""):
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
                else:
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                self.wfile.flush()
                self.rfile.read(1)  # returns once the client closes its end

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
                return 200, json.dumps({"version": self.version})
            if path == "/v1/models":
                if authorization != f"Bearer {VLLM_API_KEY}":
                    return 401, json.dumps({"error": "Unauthorized"})
                return 200, json.dumps({"object": "list", "data": [{"id": MODEL, "max_model_len": 32768}]})
            if path == "/metrics":
                self._prompt_tokens += 100
                self._generation_tokens += 100
                return 200, metrics_text(self._prompt_tokens, self._generation_tokens)
            return 404, ""

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


# The server body tests create servers with; tests that connect replace host and port.
SERVER_BODY = {"name": "gpu-7", "host": "127.0.0.1", "port": 22, "username": "ubuntu",
               "auth_type": "password", "password": "ssh-pw"}


def wait_for(get: Callable[[], Any], predicate: Callable[[Any], bool], timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    value = None
    while time.monotonic() < deadline:
        if predicate(value := get()):
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out; last value: {value}")


def watched_server(api: TestClient, w: str, host: FakeSSHD) -> int:
    """A server on `host`, tested so its host key is recorded and the watcher wakes for it."""
    server_id = api.post(f"{w}/servers", json=SERVER_BODY | {"host": host.host, "port": host.port}).json()["id"]
    assert api.post(f"{w}/servers/{server_id}/test").json()["ok"]
    return server_id


class DockerHost:
    """Answers like a GPU server where docker needs sudo with a password: one vLLM container on
    the host network (its port is `vllm`'s, so port forwards reach it), plus nginx. Tests change
    `ps` and `inspect` as they go; `ps` set to None makes `docker ps` fail."""

    def __init__(self, vllm: FakeVLLM, sudo_password: str) -> None:
        self._vllm = vllm
        self._sudo_password = sudo_password
        self.ps: str | None = "\n".join(json.dumps(row) for row in [
            {"Names": "vllm-llama", "Image": "vllm/vllm-openai:v0.11.0", "State": "running",
             "Command": f'"vllm serve {MODEL} --port {vllm.port}"'},
            {"Names": "nginx", "Image": "nginx:1.27", "State": "running", "Command": '"nginx -g daemon off;"'},
        ]) + "\n"
        self.inspect = self._inspect_line()
        # `docker inspect --type image` fails this many more times; and how often it was asked.
        self.image_failures = 0
        self.image_inspects = 0

    def _inspect_line(self, **fields: object) -> str:
        args = ["serve", MODEL, "--port", str(self._vllm.port)]
        return inspect_line(**({
            "args": args, "cmd": args, "network_mode": "host", "ports": {}, "networks": {"host": {}},
            "device_requests": [{"Count": 0, "DeviceIDs": ["0"], "Capabilities": [["gpu"]]}],
            "env": [f"VLLM_API_KEY={VLLM_API_KEY}", "HF_TOKEN=hf_secret", None],
        } | fields)) + "\n"

    def relaunch(self, container_id: str, *extra_args: str) -> None:
        """The container recreated with a new ID and these extra arguments."""
        args = ["serve", MODEL, "--port", str(self._vllm.port), *extra_args]
        self.inspect = self._inspect_line(id=container_id, args=args, cmd=args)

    def __call__(self, command: str, stdin: str) -> tuple[str, str, int]:
        if command == "hostname":
            return "gpu-7\n", "", 0
        if command.startswith("docker "):
            return "", "permission denied while trying to connect to the Docker daemon socket\n", 1
        if command.startswith("sudo -n "):
            return "", "sudo: a password is required\n", 1
        if command.startswith("sudo -S "):
            if stdin != self._sudo_password + "\n":
                return "", "Sorry, try again.\nsudo: 1 incorrect password attempt\n", 1
            args = command.split(" docker ", 1)[1]
            if args.startswith("ps "):
                if self.ps is None:
                    return "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock.\n", 1
                return self.ps, "", 0
            if args.startswith("inspect --type image "):
                self.image_inspects += 1
                if self.image_failures > 0:
                    self.image_failures -= 1
                    return "", "Error response from daemon: context deadline exceeded\n", 1
                return image_line() + "\n", "", 0
            if args.startswith("inspect "):
                return self.inspect, "", 0
        if command.startswith("nvidia-smi "):
            return NVIDIA_SMI_OUTPUT, "", 0
        return "", f"bash: {command.split()[0]}: command not found\n", 127


def docker_host(vllm: FakeVLLM, *, sudo_password: str) -> DockerHost:
    return DockerHost(vllm, sudo_password)


# --- A server running vLLM as systemd services.


def show_block(name: str, exec_start: str, *, active: str = "active", sub: str = "running", load: str = "loaded",
               env: str = "", control_group: str | None = None) -> str:
    """One unit's `systemctl show` block, as the env filter passes it on."""
    group = f"/system.slice/{name}" if control_group is None else control_group
    return "\n".join([
        f"Id={name}", f"LoadState={load}", f"ActiveState={active}", f"SubState={sub}", "Result=success",
        "ExecMainStatus=0", "ExecMainStartTimestamp=Thu 2026-11-12 08:00:00 UTC", "ExecMainExitTimestamp=",
        "NRestarts=0",
        f"ExecStart={{ path={exec_start.split()[0]} ; argv[]={exec_start} ; ignore_errors=no ; start_time=[n/a] ;"
        " stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }",
        f"Environment={env}", f"ControlGroup={group}", "",
    ])


def _not_found(name: str) -> str:
    return "\n".join([f"Id={name}", "LoadState=not-found", "ActiveState=inactive", "SubState=dead",
                      "Result=success", "ExecStart=", "Environment=", "ControlGroup=", ""])


class SystemdHost:
    """Answers like a server running vLLM as systemd services. `units` and `files` are what
    list-units and list-unit-files print, `show` the blocks `systemctl show` gives (a unit not in it
    is not-found), `cat` each unit's text (a short default for one not in it) and `procs` each control group's "PID argv" lines.
    `error` makes the system list fail; the user scope answers from `user_units` and `user_show`,
    or fails with `user_error`. Starts with one vLLM service, vllm-llama.service, on `vllm`'s port."""

    def __init__(self, vllm: FakeVLLM) -> None:
        self.units = "vllm-llama.service loaded active running vLLM\n"
        self.files = "vllm-llama.service enabled enabled\n"
        self.show = show_block("vllm-llama.service", f"/opt/venv/bin/vllm serve {MODEL} --port {vllm.port}",
                               env=f"VLLM_API_KEY={VLLM_API_KEY} CUDA_VISIBLE_DEVICES=0")
        self.cat: dict[str, str] = {}
        self.procs: dict[str, str] = {}
        self.error: str | None = None
        self.user_units = ""
        self.user_show = ""
        self.user_error: str | None = None
        self.compute_apps = ""
        self.docker_missing = True
        # Every unit name `systemctl show` was asked for.
        self.shown: list[str] = []

    def _systemctl(self, command: str) -> tuple[str, str, int]:
        words = shlex.split(command.removeprefix("TZ=UTC LC_ALL=C ").split(" | ", 1)[0])
        user = words[1] == "--user"
        if user and self.user_error is not None:
            return "", self.user_error, 1
        verb = words[2 if user else 1]
        if verb == "list-units":
            if not user and self.error is not None:
                return "", self.error, 1
            return self.user_units if user else self.units + self.files, "", 0
        if verb == "show":
            blocks = {block.split("\n", 1)[0].removeprefix("Id="): block
                      for block in (self.user_show if user else self.show).split("\n\n") if block.strip()}
            names = words[words.index("--") + 1:]
            self.shown += names
            return "\n".join(blocks.get(name, _not_found(name)).rstrip("\n") + "\n" for name in names), "", 0
        if verb == "cat":
            return self.cat.get(words[-1], f"# /etc/systemd/system/{words[-1]}\n[Service]\nExecStart=/bin/true\n"), "", 0
        return "", f"Unknown command verb {verb}.\n", 1

    def __call__(self, command: str, stdin: str) -> tuple[str, str, int]:
        if command == "hostname":
            return "gpu-7\n", "", 0
        if command.startswith(("systemctl ", "TZ=UTC LC_ALL=C systemctl ")):
            return self._systemctl(command)
        if command.startswith("cg="):
            group = shlex.split(command.split(";", 1)[0])[0].removeprefix("cg=")
            return self.procs.get(group, ""), "", 0
        if command.startswith("docker ") and not self.docker_missing:
            return "", "", 0
        if command.startswith("nvidia-smi --query-compute-apps"):
            return self.compute_apps, "", 0
        if command.startswith("nvidia-smi "):
            return NVIDIA_SMI_OUTPUT, "", 0
        return "", f"bash: {command.split()[0]}: command not found\n", 127
