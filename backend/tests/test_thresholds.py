"""An instance's warning and critical thresholds: defaults, setting, clearing, resetting, and who may change them."""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.base import utcnow
from api.enums import WorkspaceRole
from api.models import Instance
from tests.helpers import SERVER_BODY, Db


async def _add_instance(session: AsyncSession, server_id: int, name: str) -> None:
    now = utcnow()
    session.add(Instance(server_id=server_id, name=name, container_id="a1", model=None, first_seen=now, last_seen=now))


# Thresholds need only an instances row, so the test inserts one; no watcher runs.
def test_thresholds(client: TestClient, api: TestClient, w: str, db: Db,
                    member_headers: Callable[[WorkspaceRole], dict[str, str]]) -> None:
    server_id = api.post(f"{w}/servers", json=SERVER_BODY).json()["id"]
    db(lambda session: _add_instance(session, server_id, "vllm-llama"))
    base = f"{w}/servers/{server_id}/instances/vllm-llama/thresholds"
    by_metric = lambda: {t["metric"]: t for t in api.get(base).json()["thresholds"]}  # noqa: E731
    assert by_metric() == {
        "waiting": {"metric": "waiting", "warning": None, "critical": None, "is_default": True},
        "kv_cache_percent": {"metric": "kv_cache_percent", "warning": 90, "critical": 98, "is_default": True},
        "ttft_seconds": {"metric": "ttft_seconds", "warning": None, "critical": None, "is_default": True},
    }
    assert api.put(f"{base}/ttft_seconds", json={"warning": 1.5, "critical": 3}).json() == {
        "metric": "ttft_seconds", "warning": 1.5, "critical": 3, "is_default": False}
    assert by_metric()["ttft_seconds"]["warning"] == 1.5
    # Both empty means no lines, which is not the default.
    api.put(f"{base}/kv_cache_percent", json={"warning": None, "critical": None})
    assert by_metric()["kv_cache_percent"] == {
        "metric": "kv_cache_percent", "warning": None, "critical": None, "is_default": False}
    assert api.delete(f"{base}/kv_cache_percent").json()["warning"] == 90
    for body in ({"warning": 3, "critical": 3}, {"warning": -1, "critical": None}):
        assert api.put(f"{base}/ttft_seconds", json=body).status_code == 422
    assert api.put(f"{base}/kv_cache_percent", json={"warning": 90, "critical": 101}).status_code == 422
    viewer = member_headers(WorkspaceRole.VIEWER)
    assert client.get(base, headers=viewer).status_code == 200
    assert client.put(f"{base}/waiting", json={"warning": 5, "critical": None}, headers=viewer).status_code == 403
    assert api.get(f"{w}/servers/{server_id}/instances/nope/thresholds").status_code == 404
