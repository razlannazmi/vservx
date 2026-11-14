import asyncio
import sys

import pytest
from sqlalchemy import select

from api.enums import UserRole, WorkspaceRole
from api.models import User
from api.watch.local import LocalShell, container_hints
from api.watch.shell import CommandResult, PortClosed
from tests.helpers import ADMIN, SERVER_BODY, USER_PASSWORD, DockerHost, login_headers, wait_for

THIS = {"name": "box", "kind": "this_machine"}
OWNER_COPY = "This machine can only be in a workspace whose owner is an app admin"


@pytest.fixture(autouse=True)
def on_linux(monkeypatch):
    monkeypatch.setattr("api.watch.local.unavailable_reason", lambda: None)


def user_id(db, email):
    async def find(session):
        return await session.scalar(select(User.id).where(User.email == email))
    return db(find)


def test_admin_adds_this_machine(api, w):
    body = api.post(f"{w}/servers", json=THIS).json()
    assert body["kind"] == "this_machine" and body["host"] is None


def test_operator_cannot_add_this_machine(client, w, member_headers):
    r = client.post(f"{w}/servers", json=THIS, headers=member_headers(WorkspaceRole.OPERATOR))
    assert r.status_code == 403 and r.json()["detail"] == "Only app admins can add or change this machine"


def test_needs_an_admin_owned_workspace(client, db, add_user):
    add_user("owner@example.com")
    owner = login_headers(client, "owner@example.com", "user-password")
    workspace = client.post("/api/workspaces", json={"name": "Theirs"}, headers=owner).json()["id"]
    admin = login_headers(client, ADMIN["email"], ADMIN["password"])
    r = client.post(f"/api/workspaces/{workspace}/members",
                    json={"user_id": user_id(db, ADMIN["email"]), "role": "operator"}, headers=owner)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/workspaces/{workspace}/servers", json=THIS, headers=admin)
    assert r.status_code == 422 and r.json()["detail"] == OWNER_COPY


def test_second_this_machine_refused(api, w):
    assert api.post(f"{w}/servers", json=THIS).status_code == 201
    r = api.post(f"{w}/servers", json=THIS)
    assert r.status_code == 409 and r.json()["detail"] == "This workspace already has this machine"


def test_unavailable_platform(api, w, monkeypatch):
    monkeypatch.setattr("api.watch.local.unavailable_reason", lambda: "nope")
    r = api.post(f"{w}/servers", json=THIS)
    assert r.status_code == 422 and r.json()["detail"] == "nope"


def test_operator_can_rename_but_not_set_sudo_password(api, client, w, member_headers):
    server_id = api.post(f"{w}/servers", json=THIS).json()["id"]
    headers = member_headers(WorkspaceRole.OPERATOR)
    r = client.patch(f"{w}/servers/{server_id}", json={"name": "renamed"}, headers=headers)
    assert r.status_code == 200 and r.json()["name"] == "renamed"
    r = client.patch(f"{w}/servers/{server_id}", json={"sudo_password": "x"}, headers=headers)
    assert r.status_code == 403


def test_handover_to_non_admin_refused(api, w, db, member_headers):
    api.post(f"{w}/servers", json=THIS)
    member_headers(WorkspaceRole.OPERATOR)
    r = api.post(f"{w}/owner", json={"user_id": user_id(db, "operator@example.com")})
    assert r.status_code == 422
    assert r.json()["detail"] == ("This workspace has this machine in it, so only an app admin can own it. "
                                  "Remove this machine first, or pick an admin.")


def test_this_machine_cant_be_jump_host(api, w):
    machine = api.post(f"{w}/servers", json=THIS).json()["id"]
    r = api.post(f"{w}/servers", json=SERVER_BODY | {"jump_server_id": machine})
    assert r.status_code == 422 and r.json()["detail"] == "This machine can't be a jump host"
    # A server that others jump through can't become this machine.
    api.delete(f"{w}/servers/{machine}")
    jump = api.post(f"{w}/servers", json=SERVER_BODY).json()["id"]
    api.post(f"{w}/servers", json=SERVER_BODY | {"name": "behind", "jump_server_id": jump})
    r = api.patch(f"{w}/servers/{jump}", json={"kind": "this_machine"})
    assert r.status_code == 422 and r.json()["detail"] == "This machine can't be a jump host"


def test_local_shell_reads_fake_vllm(fake_vllm):
    response = asyncio.run(LocalShell(2).http_get("127.0.0.1", fake_vllm.port, "/health"))
    assert response.status == 200


def test_local_shell_refused_port_is_port_closed(closed_port):
    with pytest.raises(PortClosed):
        asyncio.run(LocalShell(2).http_get("127.0.0.1", closed_port, "/health"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /bin/sh")
def test_local_shell_runs_commands():
    assert asyncio.run(LocalShell(2).run("echo hi")).stdout == "hi\n"


def test_this_machine_is_watched(watching, client, api, w, fake_vllm, monkeypatch):
    host = DockerHost(fake_vllm, sudo_password="pw")

    async def answer(self, command, stdin=None):
        stdout, stderr, status = host(command, stdin or "")
        return CommandResult(status, stdout, stderr)

    monkeypatch.setattr(LocalShell, "run", answer)
    server_id = api.post(f"{w}/servers", json=THIS | {"sudo_password": "pw"}).json()["id"]
    view = wait_for(lambda: api.get(f"{w}/servers/{server_id}/watch").json(),
                    lambda v: v["instances"] and v["instances"][0]["state"] == "ready")
    assert view["instances"][0]["name"] == "vllm-llama"


def test_owner_losing_admin_stops_watching(watching, client, api, add_user, db, monkeypatch):
    async def refuse(self, command, stdin=None):
        return CommandResult(127, "", "not found")

    monkeypatch.setattr(LocalShell, "run", refuse)
    add_user("boss@example.com", role=UserRole.ADMIN)
    add_user("operator@example.com")
    boss = login_headers(client, "boss@example.com", USER_PASSWORD)
    workspace = client.post("/api/workspaces", json={"name": "Theirs"}, headers=boss).json()["id"]
    w = f"/api/workspaces/{workspace}"
    for email, role in ((ADMIN["email"], "operator"), ("operator@example.com", "operator")):
        r = client.post(f"{w}/members", json={"user_id": user_id(db, email), "role": role}, headers=boss)
        assert r.status_code == 201, r.text
    server_id = api.post(f"{w}/servers", json=THIS).json()["id"]
    operator = login_headers(client, "operator@example.com", USER_PASSWORD)
    snapshots = f"{w}/servers/{server_id}/snapshots"
    assert client.get(snapshots, headers=operator).status_code == 200

    r = api.patch(f"/api/admin/accounts/{user_id(db, 'boss@example.com')}", json={"role": "member"})
    assert r.status_code == 200, r.text
    wait_for(lambda: api.get(f"{w}/servers/{server_id}/watch").json(), lambda v: v["state"] == "needs_admin_owner")
    assert client.get(snapshots, headers=operator).status_code == 404
    r = client.post(f"{w}/servers/{server_id}/test", headers=operator)
    assert r.status_code == 403 and r.json()["detail"] == "This machine needs an admin owner"
    assert api.get(snapshots).status_code == 200


def test_container_hints_name_missing_mounts(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    (tmp_path / ".dockerenv").touch()
    (tmp_path / "proc/1").mkdir(parents=True)
    (tmp_path / "proc/1/comm").write_text("vservx\n")
    hints = container_hints(tmp_path)
    assert set(hints) >= {"docker", "systemd", "pid"} and "/run/dbus/system_bus_socket" in hints["systemd"]
