import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.enums import WorkspaceRole
from tests.sshd import FakeSSHD
from tests.watch_fakes import FakeVLLM, docker_host

Sshd = Callable[..., FakeSSHD]


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
    assert (view["state"], view["docker"], view["instances"][0]["state"]) == ("connected", "sudo", "ready")
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
) -> None:  # Review Focus 1 and 5
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
