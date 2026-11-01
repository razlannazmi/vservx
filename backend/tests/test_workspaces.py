from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import LaunchType, WorkspaceRole
from api.models import Instance, SavedKey, Server
from tests.helpers import Db, create_saved_key


def _server(port: int, name: str = "gpu-1") -> dict:
    # A closed local port, so connection tests fail fast.
    return {"name": name, "host": "127.0.0.1", "port": port, "username": "ubuntu",
            "auth_type": "password", "password": "hunter2"}


async def _add_instance(session: AsyncSession, server_id: int) -> None:
    session.add(Instance(server_id=server_id, launch_type=LaunchType.DOCKER, ref="vllm-1"))


async def _count_servers_keys_instances(session: AsyncSession) -> tuple[int, int, int]:
    return tuple([await session.scalar(select(func.count()).select_from(model))
                  for model in (Server, SavedKey, Instance)])


def test_workspace_list_shows_only_mine(
    client: TestClient, api: TestClient, w: str, outsider_headers: dict[str, str]
) -> None:
    assert client.get("/api/workspaces", headers=outsider_headers).json() == []
    [mine] = api.get("/api/workspaces").json()
    assert (mine["name"], mine["role"], mine["member_count"]) == ("Work", "owner", 1)


def test_workspace_names_are_unique(
    client: TestClient, api: TestClient, w: str, outsider_headers: dict[str, str]
) -> None:
    # Across vservx and ignoring case: the outsider can't see "Work" but can't take its name either.
    assert client.post("/api/workspaces", json={"name": "work"}, headers=outsider_headers).status_code == 409
    home = api.post("/api/workspaces", json={"name": "Home"}).json()["id"]
    assert api.patch(f"/api/workspaces/{home}", json={"name": "WORK"}).status_code == 409
    # Changing only the case of its own name is fine.
    assert api.patch(w, json={"name": "WORK"}).json()["name"] == "WORK"


def test_non_members_get_404(
    client: TestClient, api: TestClient, w: str, outsider_headers: dict[str, str], closed_port: int
) -> None:
    server_id = api.post(f"{w}/servers", json=_server(closed_port)).json()["id"]
    key_id, _ = create_saved_key(api, w)
    for method, path, body in [("GET", w, None), ("GET", f"{w}/servers", None),
                               ("GET", f"{w}/servers/{server_id}", None),
                               ("POST", f"{w}/servers/{server_id}/test", None),
                               ("PATCH", f"{w}/servers/{server_id}", {"host": "x"}),
                               ("GET", f"{w}/ssh-keys/{key_id}", None)]:
        response = client.request(method, path, json=body, headers=outsider_headers)
        assert response.status_code == 404 and response.json()["detail"] == "Workspace not found", path


def test_viewer_reads_and_tests_only(
    client: TestClient, api: TestClient, w: str,
    member_headers: Callable[[WorkspaceRole], dict[str, str]], closed_port: int,
) -> None:
    server_id = api.post(f"{w}/servers", json=_server(closed_port)).json()["id"]
    viewer = member_headers(WorkspaceRole.VIEWER)
    assert client.get(f"{w}/servers", headers=viewer).status_code == 200
    assert client.post(f"{w}/servers/{server_id}/test", headers=viewer).status_code == 200
    for method, path, body in [("POST", f"{w}/servers", _server(closed_port, "x")),
                               ("PATCH", f"{w}/servers/{server_id}", {"host": "x"}),
                               ("DELETE", f"{w}/servers/{server_id}", None),
                               ("POST", f"{w}/servers/test", _server(closed_port, "y")),
                               ("POST", f"{w}/servers/{server_id}/host-key/accept", {"fingerprint": "x"}),
                               ("POST", f"{w}/ssh-keys", {"name": "k", "private_key": "x"})]:
        assert client.request(method, path, json=body, headers=viewer).status_code == 403, path


def test_operator_changes_servers(
    client: TestClient, w: str, member_headers: Callable[[WorkspaceRole], dict[str, str]], closed_port: int
) -> None:
    operator = member_headers(WorkspaceRole.OPERATOR)
    response = client.post(f"{w}/servers", json=_server(closed_port), headers=operator)
    assert response.status_code == 201
    assert client.delete(f"{w}/servers/{response.json()['id']}", headers=operator).status_code == 204


def test_links_stay_inside_workspace(api: TestClient, w: str, closed_port: int) -> None:  # Review Focus 1
    home = f"/api/workspaces/{api.post('/api/workspaces', json={'name': 'Home'}).json()['id']}"
    home_key, _ = create_saved_key(api, home)
    home_server = api.post(f"{home}/servers", json=_server(closed_port)).json()["id"]  # same name as below: allowed
    assert api.post(f"{w}/servers", json=_server(closed_port) | {"jump_server_id": home_server}).status_code == 422
    key_body = _server(closed_port, "k") | {"auth_type": "key", "ssh_key_id": home_key, "password": None}
    assert api.post(f"{w}/servers", json=key_body).status_code == 422
    assert api.post(f"{w}/servers", json=_server(closed_port)).status_code == 201
    assert api.post(f"{w}/servers", json=_server(closed_port)).status_code == 409  # name taken in this workspace


def test_owner_manages_members(api: TestClient, w: str, add_user: Callable[..., None]) -> None:
    add_user("ada@example.com")
    [ada] = api.get("/api/accounts", params={"q": "ADA"}).json()
    assert api.post(f"{w}/members", json={"user_id": ada["id"], "role": "viewer"}).status_code == 201
    assert api.patch(f"{w}/members/{ada['id']}", json={"role": "operator"}).json()["role"] == "operator"
    assert [m["role"] for m in api.get(f"{w}/members").json()] == ["owner", "operator"]
    assert api.delete(f"{w}/members/{ada['id']}").status_code == 204


def test_only_owner_manages_the_workspace(
    client: TestClient, w: str, member_headers: Callable[[WorkspaceRole], dict[str, str]]
) -> None:
    operator = member_headers(WorkspaceRole.OPERATOR)
    assert client.post(f"{w}/members", json={"user_id": 1, "role": "viewer"}, headers=operator).status_code == 403
    assert client.patch(w, json={"name": "x"}, headers=operator).status_code == 403
    assert client.delete(w, headers=operator).status_code == 403


def test_workspace_keeps_exactly_one_owner(  # Review Focus 3
    client: TestClient, api: TestClient, w: str,
    member_headers: Callable[[WorkspaceRole], dict[str, str]], outsider_headers: dict[str, str],
) -> None:
    me = api.get("/api/auth/me").json()["id"]
    viewer = member_headers(WorkspaceRole.VIEWER)
    viewer_id = client.get("/api/auth/me", headers=viewer).json()["id"]
    outsider_id = client.get("/api/auth/me", headers=outsider_headers).json()["id"]
    assert api.delete(f"{w}/members/{me}").status_code == 409
    assert api.patch(f"{w}/members/{me}", json={"role": "viewer"}).status_code == 409
    assert api.post(f"{w}/members", json={"user_id": outsider_id, "role": "owner"}).status_code == 422
    assert api.post(f"{w}/owner", json={"user_id": outsider_id}).status_code == 422
    assert api.post(f"{w}/owner", json={"user_id": viewer_id}).json()["role"] == "operator"
    assert client.get(w, headers=viewer).json()["role"] == "owner"


def test_member_can_leave(client: TestClient, w: str, member_headers: Callable[[WorkspaceRole], dict[str, str]]) -> None:
    viewer = member_headers(WorkspaceRole.VIEWER)
    viewer_id = client.get("/api/auth/me", headers=viewer).json()["id"]
    assert client.delete(f"{w}/members/{viewer_id}", headers=viewer).status_code == 204
    assert client.get(w, headers=viewer).status_code == 404


def test_owner_deletes_workspace_with_everything_in_it(  # Review Focus 2
    api: TestClient, w: str, db: Db, closed_port: int
) -> None:
    key_id, _ = create_saved_key(api, w)
    bastion = api.post(f"{w}/servers", json=_server(closed_port, "bastion")).json()["id"]
    key_server = _server(closed_port, "gpu") | {"auth_type": "key", "ssh_key_id": key_id,
                                                "password": None, "jump_server_id": bastion}
    gpu = api.post(f"{w}/servers", json=key_server).json()["id"]
    db(lambda s: _add_instance(s, gpu))
    assert api.delete(w).status_code == 204
    assert api.get(w).status_code == 404
    assert db(_count_servers_keys_instances) == (0, 0, 0)


def test_admin_changes_owner(
    client: TestClient, api: TestClient, w: str, add_user: Callable[..., None], outsider_headers: dict[str, str]
) -> None:
    add_user("ada@example.com")
    ada_id = api.get("/api/accounts", params={"q": "ada"}).json()[0]["id"]
    [row] = api.get("/api/admin/workspaces").json()
    assert (row["name"], row["owner"]["email"], row["member_count"]) == ("Work", "admin@example.com", 1)
    workspace_id = row["id"]
    assert api.post(f"/api/admin/workspaces/{workspace_id}/owner", json={"user_id": ada_id}).json()["owner"]["id"] == ada_id
    assert api.get(w).json()["role"] == "operator"
    assert client.get("/api/admin/workspaces", headers=outsider_headers).status_code == 403
