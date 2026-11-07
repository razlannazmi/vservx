import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import AuthType
from api.models import SavedKey, Server
from tests.helpers import Db, FakeSSHD, Sshd, create_saved_key, make_key, public_line

PASSWORD_SERVER = {"name": "gpu-1", "host": "10.0.0.1", "username": "ubuntu",
                   "auth_type": "password", "password": "hunter2"}


def _create(api: TestClient, w: str, data: dict) -> int:
    response = api.post(f"{w}/servers", json=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _behind(api: TestClient, w: str, name: str, jump_id: int | None, **extra) -> int:
    return _create(api, w, PASSWORD_SERVER | {"name": name, "jump_server_id": jump_id} | extra)


def _stored(db: Db, model: type, row_id: int):
    async def get(session: AsyncSession):
        return await session.get(model, row_id)

    return db(get)


# --- Servers


def test_passwords_stored_encrypted_and_never_returned(api: TestClient, w: str, db: Db) -> None:
    response = api.post(f"{w}/servers", json=PASSWORD_SERVER | {"sudo_password": "sudo-secret"})
    assert response.status_code == 201
    body = response.json()
    assert (body["port"], body["has_password"], body["has_sudo_password"]) == (22, True, True)
    assert "hunter2" not in response.text and "sudo-secret" not in response.text
    assert "hunter2" not in db(lambda s: s.scalar(text("SELECT password FROM servers")))
    # Fields left out of an update stay as they were.
    updated = api.patch(f"{w}/servers/{body['id']}", json={"host": "10.0.0.9"}).json()
    assert (updated["host"], updated["name"], updated["has_sudo_password"]) == ("10.0.0.9", "gpu-1", True)
    stored = _stored(db, Server, body["id"])
    assert (stored.password, stored.sudo_password) == ("hunter2", "sudo-secret")
    assert api.patch(f"{w}/servers/{body['id']}", json={"sudo_password": None}).json()["has_sudo_password"] is False


def test_validation_error_does_not_echo_secrets(api: TestClient, w: str) -> None:
    # Key auth plus a password fails the model-level validator, whose input is the whole body.
    response = api.post(f"{w}/servers", json=PASSWORD_SERVER | {"auth_type": "key", "ssh_key_id": 1})

    assert response.status_code == 422
    assert "hunter2" not in response.text
    assert "password is only allowed" in response.json()["detail"][0]["msg"]


def test_update_rejects_mismatched_credentials(api: TestClient, w: str, db: Db) -> None:
    server_id = _create(api, w, PASSWORD_SERVER)
    key_id, _ = create_saved_key(api, w)

    for change in ({"auth_type": "key", "ssh_key_id": key_id},  # stored password left behind
                   {"password": None}):  # password auth with no password
        assert api.patch(f"{w}/servers/{server_id}", json=change).status_code == 422

    stored = _stored(db, Server, server_id)
    assert (stored.auth_type, stored.password) == (AuthType.PASSWORD, "hunter2")


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


def test_key_and_jump_host_in_use_cannot_be_deleted(api: TestClient, w: str) -> None:
    key_id, _ = create_saved_key(api, w)
    bastion = _behind(api, w, "bastion", None)
    _behind(api, w, "gpu", bastion, auth_type="key", ssh_key_id=key_id, password=None)

    assert api.get(f"{w}/ssh-keys/{key_id}").json()["server_count"] == 1
    for path in (f"{w}/ssh-keys/{key_id}", f"{w}/servers/{bastion}"):
        response = api.delete(path)
        assert response.status_code == 409 and "1 server" in response.json()["detail"], path


# --- Saved keys


def test_saved_key_stored_encrypted_and_never_returned(api: TestClient, w: str, db: Db) -> None:
    key_text, key = make_key(passphrase="key-passphrase")
    body = {"name": "lab-key", "private_key": key_text, "passphrase": "key-passphrase"}

    response = api.post(f"{w}/ssh-keys", json=body)

    assert response.status_code == 201
    saved = response.json()
    assert (saved["name"], saved["key_type"], saved["fingerprint"]) == ("lab-key", "ssh-ed25519", key.get_fingerprint())
    assert (saved["has_passphrase"], saved["server_count"]) == (True, 0)
    assert "PRIVATE KEY" not in response.text and "key-passphrase" not in response.text

    async def raw(session: AsyncSession):
        return (await session.execute(text("SELECT private_key, passphrase FROM ssh_keys"))).one()

    row = db(raw)
    assert key_text not in row.private_key and "key-passphrase" not in row.passphrase
    stored = _stored(db, SavedKey, saved["id"])
    assert (stored.private_key, stored.passphrase) == (key_text, "key-passphrase")


def test_create_rejects_unusable_keys(api: TestClient, w: str) -> None:
    encrypted, _ = make_key(passphrase="pw")

    for body in ({"private_key": "hello"},
                 {"private_key": encrypted},
                 {"private_key": encrypted, "passphrase": "wrong"},
                 {"private_key": "A" * 20_000}):
        assert api.post(f"{w}/ssh-keys", json={"name": "k"} | body).status_code == 422

    assert api.get(f"{w}/ssh-keys").json() == []


# --- Connection tests, against in-process SSH servers


def _body(sshd_server: FakeSSHD, name: str = "gpu-7", **fields) -> dict:
    return {"name": name, "host": sshd_server.host, "port": sshd_server.port, "username": "ubuntu",
            "auth_type": "password", "password": "pw"} | fields


def _server(api: TestClient, w: str, sshd_server: FakeSSHD, name: str = "gpu-7", **fields) -> int:
    return _create(api, w, _body(sshd_server, name, **fields))


def _fingerprint(api: TestClient, w: str, server_id: int) -> str | None:
    return api.get(f"{w}/servers/{server_id}").json()["host_key_fingerprint"]


def _pin_other_key(db: Db, server_id: int, algorithm: str = "ssh-ed25519") -> str:
    _, other = make_key(algorithm=algorithm)
    db(lambda s: s.execute(update(Server).where(Server.id == server_id).values(host_key=public_line(other))))
    return other.get_fingerprint()


def test_test_records_host_key_and_result(api: TestClient, w: str, sshd: Sshd, closed_port: int) -> None:
    server = sshd(password="pw", hostname="gpu-7")
    server_id = _server(api, w, server)

    body = api.post(f"{w}/servers/{server_id}/test").json()

    assert (body["ok"], body["hostname"], body["hops"][0]["server_id"]) == (True, "gpu-7", server_id)
    saved = api.get(f"{w}/servers/{server_id}").json()
    assert saved["host_key_fingerprint"] == server.host_key.get_fingerprint()
    assert saved["last_test"]["ok"] is True and saved["host_key_recorded_at"] and saved["host_key_type"]
    api.patch(f"{w}/servers/{server_id}", json={"host": "127.0.0.1", "port": closed_port})
    api.post(f"{w}/servers/{server_id}/test")
    saved = api.get(f"{w}/servers/{server_id}").json()
    assert (saved["last_test"]["ok"], saved["last_test"]["failure"], saved["last_test"]["failed_hop"]) == (
        False, "unreachable", "gpu-7")
    assert saved["host_key_recorded_at"] is None  # new address, identity forgotten


def test_failed_login_records_no_host_key(api: TestClient, w: str, sshd: Sshd) -> None:
    server_id = _server(api, w, sshd(password="pw"), password="wrong")

    response = api.post(f"{w}/servers/{server_id}/test")

    assert response.status_code == 200
    assert (response.json()["ok"], response.json()["hops"][0]["reason"]) == (False, "auth_failed")
    assert _fingerprint(api, w, server_id) is None


# The fake server offers only ed25519, so a recorded RSA key is one it no longer offers.
@pytest.mark.parametrize("algorithm", ["ssh-ed25519", "ssh-rsa"])
def test_changed_host_key_reported_and_kept(api: TestClient, w: str, sshd: Sshd, db: Db, algorithm: str) -> None:
    server = sshd(password="pw")
    server_id = _server(api, w, server)
    pinned = _pin_other_key(db, server_id, algorithm)

    hop = api.post(f"{w}/servers/{server_id}/test").json()["hops"][0]

    assert (hop["reason"], hop["fingerprint"]) == ("host_key_changed", server.host_key.get_fingerprint())
    assert server.auth_attempts == []  # refused before any password or key was sent
    assert _fingerprint(api, w, server_id) == pinned


def test_jump_chain_records_every_hop(api: TestClient, w: str, sshd: Sshd) -> None:
    bastion, gpu = sshd(password="pw", hostname="bastion-1"), sshd(password="pw", hostname="gpu-7")
    bastion_id = _server(api, w, bastion, "bastion-1", jump_only=True)
    gpu_id = _server(api, w, gpu, "gpu-7", jump_server_id=bastion_id)

    body = api.post(f"{w}/servers/{gpu_id}/test").json()

    assert body["ok"] is True
    assert [(h["server_id"], h["name"]) for h in body["hops"]] == [(bastion_id, "bastion-1"), (gpu_id, "gpu-7")]
    assert (_fingerprint(api, w, bastion_id), _fingerprint(api, w, gpu_id)) == (
        bastion.host_key.get_fingerprint(), gpu.host_key.get_fingerprint())


def test_key_auth_server_uses_saved_key(api: TestClient, w: str, sshd: Sshd) -> None:
    key_id, key = create_saved_key(api, w, passphrase="pw")
    server_id = _server(api, w, sshd(client_key=key), auth_type="key", ssh_key_id=key_id, password=None)

    assert api.post(f"{w}/servers/{server_id}/test").json()["ok"] is True


def test_unsaved_test_saves_nothing_but_records_saved_jump_host(api: TestClient, w: str, sshd: Sshd) -> None:
    bastion, gpu = sshd(password="pw"), sshd(password="pw")
    bastion_id = _server(api, w, bastion, "bastion-1")

    response = api.post(f"{w}/servers/test", json=_body(gpu, "new", jump_server_id=bastion_id))

    assert response.json()["ok"] is True
    assert [s["name"] for s in api.get(f"{w}/servers").json()] == ["bastion-1"]
    assert _fingerprint(api, w, bastion_id) == bastion.host_key.get_fingerprint()


def test_accept_changed_host_key_behind_jump_host(api: TestClient, w: str, sshd: Sshd, db: Db) -> None:
    bastion, gpu = sshd(password="pw"), sshd(password="pw")
    gpu_id = _server(api, w, gpu, "gpu-7", jump_server_id=_server(api, w, bastion, "bastion-1"))
    pinned = _pin_other_key(db, gpu_id)
    accept = f"{w}/servers/{gpu_id}/host-key/accept"

    # Only the key the server presents right now can be accepted.
    assert api.post(accept, json={"fingerprint": make_key()[1].get_fingerprint()}).status_code == 409
    assert _fingerprint(api, w, gpu_id) == pinned
    response = api.post(accept, json={"fingerprint": gpu.host_key.get_fingerprint()})

    assert response.status_code == 200
    assert response.json()["host_key_fingerprint"] == gpu.host_key.get_fingerprint()
    assert api.post(f"{w}/servers/{gpu_id}/test").json()["ok"] is True
