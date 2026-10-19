from collections.abc import Callable

import jwt
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.password import needs_rehash, verify_password
from api.config import get_settings
from api.models import User
from tests.helpers import ADMIN, USER_PASSWORD, Db


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_token_identifies_user(client: TestClient) -> None:
    response = _login(client, ADMIN["email"], ADMIN["password"])
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["role"] == "admin"


def test_login_email_ignores_case_and_whitespace(client: TestClient) -> None:
    assert _login(client, "  Admin@Example.COM ", ADMIN["password"]).status_code == 200


def test_login_failures_are_indistinguishable(client: TestClient, add_user: Callable[..., None]) -> None:
    add_user("off@example.com", is_active=False)

    responses = [
        _login(client, ADMIN["email"], "wrong-password"),
        _login(client, "nobody@example.com", ADMIN["password"]),
        _login(client, "off@example.com", USER_PASSWORD),
    ]

    assert [r.status_code for r in responses] == [401, 401, 401]
    # Same body every time, so a caller can't learn which emails have accounts.
    assert len({r.text for r in responses}) == 1


def test_login_records_last_login(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.get("/api/auth/me", headers=admin_headers).json()["last_login_at"] is not None


def test_login_token_lifetime_follows_settings(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSERVX_ACCESS_TOKEN_MINUTES", "5")
    get_settings.cache_clear()

    body = _login(client, ADMIN["email"], ADMIN["password"]).json()

    assert body["expires_in"] == 300
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 300


def test_login_upgrades_weak_password_hash(client: TestClient, add_user: Callable[..., None], db: Db) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8 * 1024).hash(USER_PASSWORD)
    add_user("old@example.com", password_hash=weak)

    assert _login(client, "old@example.com", USER_PASSWORD).status_code == 200

    async def stored_hash(session: AsyncSession) -> str:
        return await session.scalar(select(User.password_hash).where(User.email == "old@example.com"))

    upgraded = db(stored_hash)
    assert upgraded != weak
    assert not needs_rehash(upgraded)
    assert verify_password(upgraded, USER_PASSWORD)


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
