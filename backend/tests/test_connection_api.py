from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import update

from api.enums import UserRole
from api.models import Server
from tests.helpers import Db, create_saved_key, make_key, public_line
from tests.sshd import FakeSSHD

Sshd = Callable[..., FakeSSHD]


def _body(sshd_server: FakeSSHD, name: str = "gpu-7", **fields) -> dict:
    return {"name": name, "host": sshd_server.host, "port": sshd_server.port, "username": "ubuntu",
            "auth_type": "password", "password": "pw"} | fields


def _server(api: TestClient, sshd_server: FakeSSHD, name: str = "gpu-7", **fields) -> int:
    response = api.post("/api/servers", json=_body(sshd_server, name, **fields))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _fingerprint(api: TestClient, server_id: int) -> str | None:
    return api.get(f"/api/servers/{server_id}").json()["host_key_fingerprint"]


def _pin_other_key(db: Db, server_id: int) -> str:
    _, other = make_key()
    db(lambda s: s.execute(update(Server).where(Server.id == server_id).values(host_key=public_line(other))))
    return other.get_fingerprint()


def test_saved_server_test_records_host_key(api: TestClient, sshd: Sshd) -> None:
    server = sshd(password="pw", hostname="gpu-7")
    server_id = _server(api, server)

    body = api.post(f"/api/servers/{server_id}/test").json()

    assert (body["ok"], body["hostname"], body["hops"][0]["server_id"]) == (True, "gpu-7", server_id)
    assert _fingerprint(api, server_id) == server.host_key.get_fingerprint()


def test_failed_login_records_no_host_key(api: TestClient, sshd: Sshd) -> None:
    server_id = _server(api, sshd(password="pw"), password="wrong")

    response = api.post(f"/api/servers/{server_id}/test")

    assert response.status_code == 200
    assert (response.json()["ok"], response.json()["hops"][0]["reason"]) == (False, "auth_failed")
    assert _fingerprint(api, server_id) is None


def test_changed_host_key_reported_and_kept(api: TestClient, sshd: Sshd, db: Db) -> None:
    server = sshd(password="pw")
    server_id = _server(api, server)
    pinned = _pin_other_key(db, server_id)

    hop = api.post(f"/api/servers/{server_id}/test").json()["hops"][0]

    assert (hop["reason"], hop["fingerprint"]) == ("host_key_changed", server.host_key.get_fingerprint())
    assert _fingerprint(api, server_id) == pinned


def test_jump_chain_records_every_hop(api: TestClient, sshd: Sshd) -> None:
    bastion, gpu = sshd(password="pw", hostname="bastion-1"), sshd(password="pw", hostname="gpu-7")
    bastion_id = _server(api, bastion, "bastion-1", jump_only=True)
    gpu_id = _server(api, gpu, "gpu-7", jump_server_id=bastion_id)

    body = api.post(f"/api/servers/{gpu_id}/test").json()

    assert body["ok"] is True
    assert [(h["server_id"], h["name"]) for h in body["hops"]] == [(bastion_id, "bastion-1"), (gpu_id, "gpu-7")]
    assert (_fingerprint(api, bastion_id), _fingerprint(api, gpu_id)) == (
        bastion.host_key.get_fingerprint(), gpu.host_key.get_fingerprint())


def test_key_auth_server_uses_saved_key(api: TestClient, sshd: Sshd) -> None:
    key_id, key = create_saved_key(api, passphrase="pw")
    server_id = _server(api, sshd(client_key=key), auth_type="key", ssh_key_id=key_id, password=None)

    assert api.post(f"/api/servers/{server_id}/test").json()["ok"] is True


def test_unsaved_test_saves_nothing_but_records_saved_jump_host(api: TestClient, sshd: Sshd) -> None:
    bastion, gpu = sshd(password="pw"), sshd(password="pw")
    bastion_id = _server(api, bastion, "bastion-1")

    response = api.post("/api/servers/test", json=_body(gpu, "new", jump_server_id=bastion_id))

    assert response.json()["ok"] is True
    assert [s["name"] for s in api.get("/api/servers").json()] == ["bastion-1"]
    assert _fingerprint(api, bastion_id) == bastion.host_key.get_fingerprint()


def test_any_user_tests_saved_but_only_admin_tests_unsaved_or_accepts(
    client: TestClient,
    admin_headers: dict[str, str],
    role_headers: Callable[[UserRole], dict[str, str]],
    sshd: Sshd,
) -> None:
    server = sshd(password="pw")
    server_id = client.post("/api/servers", json=_body(server), headers=admin_headers).json()["id"]
    headers = role_headers(UserRole.OPERATOR)

    assert client.post(f"/api/servers/{server_id}/test", headers=headers).status_code == 200
    assert client.post("/api/servers/test", json=_body(server, "x"), headers=headers).status_code == 403
    accept = {"fingerprint": server.host_key.get_fingerprint()}
    assert client.post(f"/api/servers/{server_id}/host-key/accept", json=accept, headers=headers).status_code == 403


def test_accept_changed_host_key_behind_jump_host(api: TestClient, sshd: Sshd, db: Db) -> None:
    bastion, gpu = sshd(password="pw"), sshd(password="pw")
    gpu_id = _server(api, gpu, "gpu-7", jump_server_id=_server(api, bastion, "bastion-1"))
    _pin_other_key(db, gpu_id)

    response = api.post(f"/api/servers/{gpu_id}/host-key/accept",
                        json={"fingerprint": gpu.host_key.get_fingerprint()})

    assert response.status_code == 200
    assert response.json()["host_key_fingerprint"] == gpu.host_key.get_fingerprint()
    assert api.post(f"/api/servers/{gpu_id}/test").json()["ok"] is True


def test_accept_refuses_other_fingerprint(api: TestClient, sshd: Sshd, db: Db) -> None:
    server_id = _server(api, sshd(password="pw"))
    pinned = _pin_other_key(db, server_id)
    _, impostor = make_key()

    response = api.post(f"/api/servers/{server_id}/host-key/accept",
                        json={"fingerprint": impostor.get_fingerprint()})

    assert response.status_code == 409
    assert _fingerprint(api, server_id) == pinned
