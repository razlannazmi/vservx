import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import AuthType
from api.models import Server
from tests.helpers import Db, create_saved_key

PASSWORD_SERVER = {"name": "gpu-1", "host": "10.0.0.1", "username": "ubuntu",
                   "auth_type": "password", "password": "hunter2"}


@pytest.fixture
def key_server(api: TestClient, w: str) -> dict:
    key_id, _ = create_saved_key(api, w)
    return {"name": "gpu-2", "host": "10.0.0.2", "port": 2222, "username": "ubuntu",
            "auth_type": "key", "ssh_key_id": key_id}


def _create(api: TestClient, w: str, data: dict) -> int:
    response = api.post(f"{w}/servers", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _behind(api: TestClient, w: str, name: str, jump_id: int | None, **extra) -> int:
    return _create(api, w, PASSWORD_SERVER | {"name": name, "jump_server_id": jump_id} | extra)


def _stored(db: Db, server_id: int) -> Server | None:
    async def get(session: AsyncSession) -> Server | None:
        return await session.get(Server, server_id)

    return db(get)


def test_servers_require_login(client: TestClient) -> None:
    assert client.get("/api/workspaces/1/servers").status_code == 401
    assert client.post("/api/workspaces/1/servers", json=PASSWORD_SERVER).status_code == 401


def test_create_server_returns_it_without_secrets(api: TestClient, w: str) -> None:
    response = api.post(f"{w}/servers", json=PASSWORD_SERVER)

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["host"], body["port"]) == ("gpu-1", "10.0.0.1", 22)
    assert body["has_password"] is True
    assert "hunter2" not in response.text


def test_password_encrypted_at_rest(api: TestClient, w: str, db: Db) -> None:
    server_id = _create(api, w, PASSWORD_SERVER)

    assert "hunter2" not in db(lambda s: s.scalar(text("SELECT password FROM servers")))
    assert _stored(db, server_id).password == "hunter2"


def test_validation_error_does_not_echo_secrets(api: TestClient, w: str) -> None:
    # Key auth plus a password fails the model-level validator, whose input is the whole body.
    response = api.post(f"{w}/servers", json=PASSWORD_SERVER | {"auth_type": "key", "ssh_key_id": 1})

    assert response.status_code == 422
    assert "hunter2" not in response.text
    assert "password is only allowed" in response.json()["detail"][0]["msg"]


def test_update_changes_only_sent_fields(api: TestClient, w: str, db: Db) -> None:
    server_id = _create(api, w, PASSWORD_SERVER)

    response = api.patch(f"{w}/servers/{server_id}", json={"host": "10.0.0.9"})

    assert response.status_code == 200
    assert response.json()["host"] == "10.0.0.9"
    assert response.json()["name"] == "gpu-1"
    assert _stored(db, server_id).password == "hunter2"


def test_update_rejects_mismatched_credentials(api: TestClient, w: str, db: Db) -> None:
    server_id = _create(api, w, PASSWORD_SERVER)
    key_id, _ = create_saved_key(api, w)

    for change in ({"auth_type": "key", "ssh_key_id": key_id},  # stored password left behind
                   {"password": None}):  # password auth with no password
        assert api.patch(f"{w}/servers/{server_id}", json=change).status_code == 422

    stored = _stored(db, server_id)
    assert (stored.auth_type, stored.password) == (AuthType.PASSWORD, "hunter2")


def test_saved_key_in_use_cannot_be_deleted(api: TestClient, w: str, key_server: dict) -> None:
    _create(api, w, key_server)
    key_id = key_server["ssh_key_id"]

    assert api.get(f"{w}/ssh-keys/{key_id}").json()["server_count"] == 1
    response = api.delete(f"{w}/ssh-keys/{key_id}")
    assert response.status_code == 409
    assert "1 server" in response.json()["detail"]


def test_bad_jump_links_rejected(api: TestClient, w: str) -> None:
    a = _behind(api, w, "a", None)
    b = _behind(api, w, "b", a)

    assert api.post(f"{w}/servers", json=PASSWORD_SERVER | {"jump_server_id": 999}).status_code == 422
    assert api.patch(f"{w}/servers/{a}", json={"jump_server_id": a}).status_code == 422
    assert api.patch(f"{w}/servers/{a}", json={"jump_server_id": b}).status_code == 422
    assert api.get(f"{w}/servers/{a}").json()["jump_server_id"] is None


def test_at_most_eight_jump_hosts(api: TestClient, w: str) -> None:
    chain = []
    for i in range(9):  # s8 has 8 jump hosts in front of it
        chain.append(_behind(api, w, f"s{i}", chain[-1] if chain else None))

    assert api.post(f"{w}/servers", json=PASSWORD_SERVER | {"name": "s9", "jump_server_id": chain[-1]}).status_code == 422
    # Putting a jump host in front of s0 would give s8 nine.
    top = _behind(api, w, "top", None)
    assert api.patch(f"{w}/servers/{chain[0]}", json={"jump_server_id": top}).status_code == 422


def test_jump_host_in_use_cannot_be_deleted(api: TestClient, w: str) -> None:
    bastion = _behind(api, w, "bastion", None)
    _behind(api, w, "gpu", bastion)

    response = api.delete(f"{w}/servers/{bastion}")

    assert response.status_code == 409
    assert "1 server" in response.json()["detail"]


def test_sudo_password_is_stored_but_never_returned(api: TestClient, w: str, closed_port: int, db: Db) -> None:
    body = {"name": "gpu", "host": "127.0.0.1", "port": closed_port, "username": "u",
            "auth_type": "password", "password": "pw", "sudo_password": "sudo-secret"}
    created = api.post(f"{w}/servers", json=body)
    assert created.status_code == 201 and created.json()["has_sudo_password"] is True
    assert "sudo-secret" not in created.text
    server_id = created.json()["id"]
    stored = db(lambda s: s.scalar(select(Server.sudo_password).where(Server.id == server_id)))
    assert stored == "sudo-secret"
    assert api.patch(f"{w}/servers/{server_id}", json={"name": "gpu-2"}).json()["has_sudo_password"] is True
    assert api.patch(f"{w}/servers/{server_id}", json={"sudo_password": None}).json()["has_sudo_password"] is False
