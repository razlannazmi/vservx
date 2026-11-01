from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

from api.auth.tokens import create_access_token
from api.config import get_settings
from api.enums import UserRole
from api.main import create_app
from tests.helpers import ADMIN, USER_PASSWORD, login_headers

ME = "/api/auth/me"
NEW = {"name": "Ada", "email": "ada@example.com", "password": "ada-password"}


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# --- Signing in


def test_login_failures_are_indistinguishable(client: TestClient) -> None:
    responses = [
        _login(client, ADMIN["email"], "wrong-password"),
        _login(client, "nobody@example.com", ADMIN["password"]),
    ]

    assert [r.status_code for r in responses] == [401, 401]
    # Same body every time, so a caller can't learn which emails have accounts.
    assert len({r.text for r in responses}) == 1


def test_browser_session_cookie(client: TestClient) -> None:
    response = _login(client, ADMIN["email"], ADMIN["password"])
    cookie = response.headers["set-cookie"].lower()
    assert "vservx_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "secure" not in cookie  # plain http test server
    assert client.get(ME).status_code == 200  # cookie only, no Authorization header
    assert client.post("/api/workspaces", json={"name": "W"}).status_code == 403
    assert client.post("/api/workspaces", json={"name": "W"}, headers={"X-Vservx": "1"}).status_code == 201
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get(ME).status_code == 401


def test_no_cross_origin_access_by_default(client: TestClient) -> None:
    # Ports don't count for SameSite, so a page on another localhost port gets the cookie sent;
    # CORS must not also let it add X-Vservx and read the reply.
    preflight = client.options("/api/workspaces", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-vservx",
    })
    assert "access-control-allow-origin" not in preflight.headers


# Each names the seeded admin (user 1), so only the token itself is wrong.
@pytest.mark.parametrize(
    "token",
    [
        lambda: create_access_token(1, 0, timedelta(seconds=-1)),  # expired
        lambda: jwt.encode({"sub": "1", "ver": 0, "iat": 0, "exp": 2**40}, b"a-different-32-byte-signing-key!"),
        lambda: jwt.encode({"sub": "1", "ver": 0, "iat": 0, "exp": 2**40}, None, algorithm="none"),
        lambda: "garbage",
    ],
)
def test_bad_tokens_are_rejected(client: TestClient, token: Callable[[], str]) -> None:
    assert client.get(ME, headers={"Authorization": f"Bearer {token()}"}).status_code == 401


def test_app_files_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>vservx</title>")
    (ui / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("VSERVX_UI_DIR", str(ui))
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert "<title>vservx</title>" in client.get("/").text
        # A link into the app works on refresh.
        assert "<title>vservx</title>" in client.get("/workspaces/homelab/servers/2").text
        assert client.get("/assets/app.js").text == "console.log(1)"
        missing = client.get("/api/nope")
        assert missing.status_code == 404 and missing.headers["content-type"].startswith("application/json")


# --- Sign-up and accounts


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


def test_admin_changes_sign_the_account_out(
    client: TestClient, api: TestClient, add_user: Callable[..., None]
) -> None:
    add_user("ada@example.com")
    ada = next(a["id"] for a in api.get("/api/admin/accounts").json() if a["email"] == "ada@example.com")
    old = login_headers(client, "ada@example.com", USER_PASSWORD)
    api.patch(f"/api/admin/accounts/{ada}", json={"password": "new-password"})
    assert client.get(ME, headers=old).status_code == 401
    new = login_headers(client, "ada@example.com", "new-password")
    api.patch(f"/api/admin/accounts/{ada}", json={"is_active": False})
    assert client.get(ME, headers=new).status_code == 401
    response = _login(client, "ada@example.com", "new-password")
    assert (response.status_code, response.json()["code"]) == (403, "account_disabled")


def test_last_admin_cannot_be_removed(api: TestClient, add_user: Callable[..., None]) -> None:
    assert api.patch("/api/admin/accounts/1", json={"role": "member"}).status_code == 409
    assert api.patch("/api/admin/accounts/1", json={"is_active": False}).status_code == 409
    add_user("second@example.com", role=UserRole.ADMIN)
    assert api.patch("/api/admin/accounts/1", json={"role": "member"}).status_code == 200


def test_change_own_name_and_password(client: TestClient, add_user: Callable[..., None]) -> None:
    add_user("ada@example.com")
    old = login_headers(client, "ada@example.com", USER_PASSWORD)
    assert client.patch(ME, json={"name": "Ada L"}, headers=old).json()["name"] == "Ada L"
    body = {"current_password": "wrong-one", "new_password": "fresh-password"}
    assert client.post(f"{ME}/password", json=body, headers=old).status_code == 400
    body["current_password"] = USER_PASSWORD
    new_token = client.post(f"{ME}/password", json=body, headers=old).json()["access_token"]
    assert client.get(ME, headers=old).status_code == 401
    assert client.get(ME, headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
