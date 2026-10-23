from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import AuthType, UserRole
from api.models import Server
from tests.helpers import Db, create_saved_key

PASSWORD_SERVER = {"name": "gpu-1", "host": "10.0.0.1", "username": "ubuntu",
                   "auth_type": "password", "password": "hunter2"}


@pytest.fixture
def key_server(api: TestClient) -> dict:
    key_id, _ = create_saved_key(api)
    return {"name": "gpu-2", "host": "10.0.0.2", "port": 2222, "username": "ubuntu",
            "auth_type": "key", "ssh_key_id": key_id}


def _create(api: TestClient, data: dict) -> int:
    response = api.post("/api/servers", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _behind(api: TestClient, name: str, jump_id: int | None, **extra) -> int:
    return _create(api, PASSWORD_SERVER | {"name": name, "jump_server_id": jump_id} | extra)


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
    assert "hunter2" not in response.text


def test_password_encrypted_at_rest(api: TestClient, db: Db) -> None:
    server_id = _create(api, PASSWORD_SERVER)

    assert "hunter2" not in db(lambda s: s.scalar(text("SELECT password FROM servers")))
    assert _stored(db, server_id).password == "hunter2"


def test_validation_error_does_not_echo_secrets(api: TestClient) -> None:
    # Key auth plus a password fails the model-level validator, whose input is the whole body.
    response = api.post("/api/servers", json=PASSWORD_SERVER | {"auth_type": "key", "ssh_key_id": 1})

    assert response.status_code == 422
    assert "hunter2" not in response.text
    assert "password is only allowed" in response.json()["detail"][0]["msg"]


def test_update_changes_only_sent_fields(api: TestClient, db: Db) -> None:
    server_id = _create(api, PASSWORD_SERVER)

    response = api.patch(f"/api/servers/{server_id}", json={"host": "10.0.0.9"})

    assert response.status_code == 200
    assert response.json()["host"] == "10.0.0.9"
    assert response.json()["name"] == "gpu-1"
    assert _stored(db, server_id).password == "hunter2"


def test_update_rejects_mismatched_credentials(api: TestClient, db: Db) -> None:
    server_id = _create(api, PASSWORD_SERVER)
    key_id, _ = create_saved_key(api)

    for change in ({"auth_type": "key", "ssh_key_id": key_id},  # stored password left behind
                   {"password": None}):  # password auth with no password
        assert api.patch(f"/api/servers/{server_id}", json=change).status_code == 422

    stored = _stored(db, server_id)
    assert (stored.auth_type, stored.password) == (AuthType.PASSWORD, "hunter2")


def test_saved_key_in_use_cannot_be_deleted(api: TestClient, key_server: dict) -> None:
    _create(api, key_server)
    key_id = key_server["ssh_key_id"]

    assert api.get(f"/api/ssh-keys/{key_id}").json()["server_count"] == 1
    response = api.delete(f"/api/ssh-keys/{key_id}")
    assert response.status_code == 409
    assert "1 server" in response.json()["detail"]


def test_bad_jump_links_rejected(api: TestClient) -> None:
    a = _behind(api, "a", None)
    b = _behind(api, "b", a)

    assert api.post("/api/servers", json=PASSWORD_SERVER | {"jump_server_id": 999}).status_code == 422
    assert api.patch(f"/api/servers/{a}", json={"jump_server_id": a}).status_code == 422
    assert api.patch(f"/api/servers/{a}", json={"jump_server_id": b}).status_code == 422
    assert api.get(f"/api/servers/{a}").json()["jump_server_id"] is None


def test_at_most_eight_jump_hosts(api: TestClient) -> None:
    chain = []
    for i in range(9):  # s8 has 8 jump hosts in front of it
        chain.append(_behind(api, f"s{i}", chain[-1] if chain else None))

    assert api.post("/api/servers", json=PASSWORD_SERVER | {"name": "s9", "jump_server_id": chain[-1]}).status_code == 422
    # Putting a jump host in front of s0 would give s8 nine.
    top = _behind(api, "top", None)
    assert api.patch(f"/api/servers/{chain[0]}", json={"jump_server_id": top}).status_code == 422


def test_jump_host_in_use_cannot_be_deleted(api: TestClient) -> None:
    bastion = _behind(api, "bastion", None)
    _behind(api, "gpu", bastion)

    response = api.delete(f"/api/servers/{bastion}")

    assert response.status_code == 409
    assert "1 server" in response.json()["detail"]


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
    assert client.post("/api/servers", json=PASSWORD_SERVER | {"name": "x"}, headers=headers).status_code == 403
    assert client.patch(f"/api/servers/{server_id}", json={"host": "x"}, headers=headers).status_code == 403
    assert client.delete(f"/api/servers/{server_id}", headers=headers).status_code == 403
