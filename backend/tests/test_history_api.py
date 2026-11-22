import socket
import time
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.config import Settings, get_settings
from tests.helpers import USER_PASSWORD, login_headers


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def store_url(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point VSERVX_HISTORY_URL at the URL the test is parametrized with. List it before `client`."""
    monkeypatch.setenv("VSERVX_HISTORY_URL", request.param)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("store_url", [f"postgresql://u:p@127.0.0.1:{_closed_port()}/x"], indirect=True)
def test_unreachable_store_does_not_block_startup(
    store_url: None, client: TestClient, admin_headers: dict[str, str], add_user: Callable[..., None]
) -> None:
    assert client.get("/api/health").status_code == 200
    status = client.get("/api/history/status", headers=admin_headers).json()
    assert status["persistent"] is True
    assert status["state"] == "unreachable"

    add_user("member@example.com")
    member = login_headers(client, "member@example.com", USER_PASSWORD)
    assert client.get("/api/history/status", headers=member).json()["queued"] is None


def test_rejects_non_postgres_url() -> None:
    with pytest.raises(ValidationError, match="postgresql://"):
        Settings(history_url="influxdb://x")


def test_history_status_without_store(api: TestClient) -> None:
    status = api.get("/api/history/status").json()
    assert status["persistent"] is False
    assert status["state"] == "off"


def test_database_reports_the_store(
    history_url: str, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    monkeypatch.setenv("VSERVX_HISTORY_URL", history_url)
    get_settings.cache_clear()
    # Requested only now, so the app starts with the store set.
    api: TestClient = request.getfixturevalue("api")
    deadline = time.monotonic() + 10
    while api.get("/api/history/status").json()["state"] != "ok":
        assert time.monotonic() < deadline, "the store never became ready"
        time.sleep(0.05)
    assert api.get("/api/database").json()["history"]["state"] == "current"
