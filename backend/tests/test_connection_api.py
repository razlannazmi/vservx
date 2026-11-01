from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import update

from api.models import Server
from tests.helpers import Db, create_saved_key, make_key, public_line
from tests.sshd import FakeSSHD

Sshd = Callable[..., FakeSSHD]


def _body(sshd_server: FakeSSHD, name: str = "gpu-7", **fields) -> dict:
    return {"name": name, "host": sshd_server.host, "port": sshd_server.port, "username": "ubuntu",
            "auth_type": "password", "password": "pw"} | fields


def _server(api: TestClient, w: str, sshd_server: FakeSSHD, name: str = "gpu-7", **fields) -> int:
    response = api.post(f"{w}/servers", json=_body(sshd_server, name, **fields))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _fingerprint(api: TestClient, w: str, server_id: int) -> str | None:
    return api.get(f"{w}/servers/{server_id}").json()["host_key_fingerprint"]


def _pin_other_key(db: Db, server_id: int) -> str:
    _, other = make_key()
    db(lambda s: s.execute(update(Server).where(Server.id == server_id).values(host_key=public_line(other))))
    return other.get_fingerprint()


def test_saved_server_test_records_host_key(api: TestClient, w: str, sshd: Sshd) -> None:
    server = sshd(password="pw", hostname="gpu-7")
    server_id = _server(api, w, server)

    body = api.post(f"{w}/servers/{server_id}/test").json()

    assert (body["ok"], body["hostname"], body["hops"][0]["server_id"]) == (True, "gpu-7", server_id)
    assert _fingerprint(api, w, server_id) == server.host_key.get_fingerprint()


def test_failed_login_records_no_host_key(api: TestClient, w: str, sshd: Sshd) -> None:
    server_id = _server(api, w, sshd(password="pw"), password="wrong")

    response = api.post(f"{w}/servers/{server_id}/test")

    assert response.status_code == 200
    assert (response.json()["ok"], response.json()["hops"][0]["reason"]) == (False, "auth_failed")
    assert _fingerprint(api, w, server_id) is None


def test_changed_host_key_reported_and_kept(api: TestClient, w: str, sshd: Sshd, db: Db) -> None:
    server = sshd(password="pw")
    server_id = _server(api, w, server)
    pinned = _pin_other_key(db, server_id)

    hop = api.post(f"{w}/servers/{server_id}/test").json()["hops"][0]

    assert (hop["reason"], hop["fingerprint"]) == ("host_key_changed", server.host_key.get_fingerprint())
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
    _pin_other_key(db, gpu_id)

    response = api.post(f"{w}/servers/{gpu_id}/host-key/accept",
                        json={"fingerprint": gpu.host_key.get_fingerprint()})

    assert response.status_code == 200
    assert response.json()["host_key_fingerprint"] == gpu.host_key.get_fingerprint()
    assert api.post(f"{w}/servers/{gpu_id}/test").json()["ok"] is True


def test_latest_test_is_remembered(api: TestClient, w: str, sshd: Sshd, closed_port: int) -> None:
    server_id = _server(api, w, sshd(password="pw"), "gpu")
    api.post(f"{w}/servers/{server_id}/test")
    server = api.get(f"{w}/servers/{server_id}").json()
    assert server["last_test"]["ok"] is True and server["last_test"]["hostname"]
    assert server["host_key_recorded_at"] and server["host_key_type"]
    api.patch(f"{w}/servers/{server_id}", json={"host": "127.0.0.1", "port": closed_port})
    api.post(f"{w}/servers/{server_id}/test")
    server = api.get(f"{w}/servers/{server_id}").json()
    assert (server["last_test"]["ok"], server["last_test"]["failure"], server["last_test"]["failed_hop"]) == (
        False, "unreachable", "gpu")
    assert server["host_key_recorded_at"] is None  # new address, identity forgotten


def test_accept_refuses_other_fingerprint(api: TestClient, w: str, sshd: Sshd, db: Db) -> None:
    server_id = _server(api, w, sshd(password="pw"))
    pinned = _pin_other_key(db, server_id)
    _, impostor = make_key()

    response = api.post(f"{w}/servers/{server_id}/host-key/accept",
                        json={"fingerprint": impostor.get_fingerprint()})

    assert response.status_code == 409
    assert _fingerprint(api, w, server_id) == pinned
