import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from api.auth.password import hash_password
from api.db import migrate
from api.enums import UserRole
from api.main import create_app
from tests.helpers import USER_PASSWORD, login_headers

NEW = {"name": "Ada", "email": "ada@example.com", "password": "ada-password"}


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_sign_up_waits_for_approval(client: TestClient, api: TestClient) -> None:
    assert client.post("/api/auth/signup", json=NEW).status_code == 202
    blocked = _login(client, NEW["email"], NEW["password"])
    assert (blocked.status_code, blocked.json()["code"]) == (403, "account_pending")
    wrong = _login(client, NEW["email"], "nope-nope")
    assert wrong.status_code == 401
    pending = api.get("/api/admin/accounts").json()[0]
    assert (pending["email"], pending["approved_at"]) == (NEW["email"], None)
    assert api.post(f"/api/admin/accounts/{pending['id']}/approve").status_code == 200
    assert _login(client, NEW["email"], NEW["password"]).status_code == 200
    assert client.post("/api/auth/signup", json=NEW).status_code == 409


def test_rejected_sign_up_is_deleted(client: TestClient, api: TestClient) -> None:
    client.post("/api/auth/signup", json=NEW)
    account_id = api.get("/api/admin/accounts").json()[0]["id"]
    assert api.delete(f"/api/admin/accounts/{account_id}").status_code == 204
    assert _login(client, NEW["email"], NEW["password"]).status_code == 401
    assert api.delete("/api/admin/accounts/1").status_code == 409


def test_sign_up_switch(client: TestClient, api: TestClient) -> None:
    assert client.get("/api/health").json()["signup_open"] is True
    assert api.patch("/api/admin/settings", json={"signup_open": False}).json() == {"signup_open": False}
    assert client.get("/api/health").json()["signup_open"] is False
    assert client.post("/api/auth/signup", json=NEW).status_code == 403


def test_disabled_account_is_told(client: TestClient, api: TestClient, add_user: Callable[..., None]) -> None:
    add_user("off@example.com")
    account_id = next(a["id"] for a in api.get("/api/admin/accounts").json() if a["email"] == "off@example.com")
    api.patch(f"/api/admin/accounts/{account_id}", json={"is_active": False})
    response = _login(client, "off@example.com", USER_PASSWORD)
    assert (response.status_code, response.json()["code"]) == (403, "account_disabled")


def test_last_admin_cannot_be_removed(api: TestClient, add_user: Callable[..., None]) -> None:
    assert api.patch("/api/admin/accounts/1", json={"role": "member"}).status_code == 409
    assert api.patch("/api/admin/accounts/1", json={"is_active": False}).status_code == 409
    add_user("second@example.com", role=UserRole.ADMIN)
    assert api.patch("/api/admin/accounts/1", json={"role": "member"}).status_code == 200


def test_change_own_name_and_password(client: TestClient, add_user: Callable[..., None]) -> None:
    add_user("ada@example.com")
    old = login_headers(client, "ada@example.com", USER_PASSWORD)
    assert client.patch("/api/auth/me", json={"name": "Ada L"}, headers=old).json()["name"] == "Ada L"
    body = {"current_password": "wrong-one", "new_password": "fresh-password"}
    assert client.post("/api/auth/me/password", json=body, headers=old).status_code == 400
    body["current_password"] = USER_PASSWORD
    new_token = client.post("/api/auth/me/password", json=body, headers=old).json()["access_token"]
    assert client.get("/api/auth/me", headers=old).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_only_admins_sign_in_while_upgrade_waits(  # Review Focus 5
    data_dir: Path, extra_migration: Callable[[str], None]
) -> None:
    db_path = data_dir / "vservx.db"
    migrate.create_database(db_path)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        for email, role in [("admin@example.com", "admin"), ("member@example.com", "member")]:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role, is_active, token_version, approved_at,"
                " created_at, updated_at) VALUES ('User', ?, ?, ?, 1, 0, '2026-01-01 00:00:00',"
                " '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
                (email, hash_password(USER_PASSWORD), role),
            )
    extra_migration('op.create_table("extra", sa.Column("id", sa.Integer, primary_key=True))')
    with TestClient(create_app()) as fresh:
        admin = _login(fresh, "admin@example.com", USER_PASSWORD)
        assert admin.status_code == 200
        me = fresh.get("/api/auth/me", headers={"Authorization": f"Bearer {admin.json()['access_token']}"})
        assert me.json()["role"] == "admin"
        other = _login(fresh, "member@example.com", USER_PASSWORD)
        assert (other.status_code, other.json()["code"]) == (503, "database_upgrade_required")
