from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import AuthType, UserRole
from api.models import Server
from tests.helpers import Db

PASSWORD_SERVER = {"name": "gpu-1", "host": "10.0.0.1", "username": "ubuntu",
                   "auth_type": "password", "password": "hunter2"}
KEY_SERVER = {"name": "gpu-2", "host": "10.0.0.2", "port": 2222, "username": "ubuntu",
              "auth_type": "key", "key_path": "~/.ssh/id_ed25519", "key_passphrase": "s3cret"}


@pytest.fixture
def api(client: TestClient, admin_headers: dict[str, str]) -> TestClient:
    client.headers.update(admin_headers)
    return client


def _create(api: TestClient, data: dict) -> int:
    response = api.post("/api/servers", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _stored(db: Db, server_id: int) -> Server | None:
    async def get(session: AsyncSession) -> Server | None:
        return await session.get(Server, server_id)

    return db(get)


def test_servers_require_login(client: TestClient) -> None:
    assert client.get("/api/servers").status_code == 401
    assert client.post("/api/servers", json=PASSWORD_SERVER).status_code == 401


def test_create_server_returns_it_without_secrets(api: TestClient) -> None:
    response = api.post("/api/servers", json=PASSWORD_SERVER)

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["host"], body["port"]) == ("gpu-1", "10.0.0.1", 22)
    assert body["has_password"] is True
    assert body["has_key_passphrase"] is False
    assert "hunter2" not in response.text


def test_create_server_stores_secret_values(api: TestClient, db: Db) -> None:
    password_id = _create(api, PASSWORD_SERVER)
    key_id = _create(api, KEY_SERVER)

    assert _stored(db, password_id).password == "hunter2"
    key_server = _stored(db, key_id)
    assert key_server.key_passphrase == "s3cret"
    assert key_server.key_path == "~/.ssh/id_ed25519"
    assert key_server.password is None


def test_list_servers_sorted_by_name(api: TestClient) -> None:
    _create(api, KEY_SERVER | {"name": "b-node"})
    _create(api, PASSWORD_SERVER | {"name": "a-node"})

    assert [s["name"] for s in api.get("/api/servers").json()] == ["a-node", "b-node"]


def test_get_server(api: TestClient) -> None:
    created = api.post("/api/servers", json=KEY_SERVER).json()

    response = api.get(f"/api/servers/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize(("method", "body"), [("GET", None), ("PATCH", {"host": "x"}), ("DELETE", None)])
def test_unknown_server_is_404(api: TestClient, method: str, body: dict | None) -> None:
    assert api.request(method, "/api/servers/999", json=body).status_code == 404


def test_duplicate_name_conflicts(api: TestClient) -> None:
    _create(api, PASSWORD_SERVER)
    other_id = _create(api, KEY_SERVER)

    assert api.post("/api/servers", json=PASSWORD_SERVER).status_code == 409
    assert api.patch(f"/api/servers/{other_id}", json={"name": "gpu-1"}).status_code == 409


def test_update_changes_only_sent_fields(api: TestClient, db: Db) -> None:
    server_id = _create(api, PASSWORD_SERVER)

    response = api.patch(f"/api/servers/{server_id}", json={"host": "10.0.0.9"})

    assert response.status_code == 200
    assert response.json()["host"] == "10.0.0.9"
    assert response.json()["name"] == "gpu-1"
    assert _stored(db, server_id).password == "hunter2"


def test_update_replaces_password(api: TestClient, db: Db) -> None:
    server_id = _create(api, PASSWORD_SERVER)

    assert api.patch(f"/api/servers/{server_id}", json={"password": "new-pass"}).status_code == 200

    assert _stored(db, server_id).password == "new-pass"


def test_update_switches_to_key_auth(api: TestClient, db: Db) -> None:
    server_id = _create(api, PASSWORD_SERVER)

    response = api.patch(f"/api/servers/{server_id}",
                         json={"auth_type": "key", "key_path": "~/.ssh/id", "password": None})

    assert response.status_code == 200
    assert response.json()["has_password"] is False
    stored = _stored(db, server_id)
    assert (stored.auth_type, stored.key_path, stored.password) == (AuthType.KEY, "~/.ssh/id", None)


@pytest.mark.parametrize(
    "change",
    [
        {"auth_type": "key", "key_path": "~/.ssh/id"},  # stored password left behind
        {"password": None},  # password auth with no password
    ],
)
def test_update_rejects_mismatched_credentials(api: TestClient, db: Db, change: dict) -> None:
    server_id = _create(api, PASSWORD_SERVER)

    assert api.patch(f"/api/servers/{server_id}", json=change).status_code == 422

    stored = _stored(db, server_id)
    assert (stored.auth_type, stored.password) == (AuthType.PASSWORD, "hunter2")


def test_delete_server(api: TestClient, db: Db) -> None:
    server_id = _create(api, PASSWORD_SERVER)

    assert api.delete(f"/api/servers/{server_id}").status_code == 204

    assert _stored(db, server_id) is None


@pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.OPERATOR])
def test_only_admins_change_servers(
    client: TestClient,
    admin_headers: dict[str, str],
    role_headers: Callable[[UserRole], dict[str, str]],
    role: UserRole,
) -> None:
    server_id = client.post("/api/servers", json=PASSWORD_SERVER, headers=admin_headers).json()["id"]
    headers = role_headers(role)

    assert client.get("/api/servers", headers=headers).status_code == 200
    assert client.get(f"/api/servers/{server_id}", headers=headers).status_code == 200
    assert client.post("/api/servers", json=KEY_SERVER, headers=headers).status_code == 403
    assert client.patch(f"/api/servers/{server_id}", json={"host": "x"}, headers=headers).status_code == 403
    assert client.delete(f"/api/servers/{server_id}", headers=headers).status_code == 403
