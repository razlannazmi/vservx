from collections.abc import Callable
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.tokens import create_access_token
from api.models import User
from api.schemas import UserUpdate
from api.service.users import apply_user_update
from tests.helpers import ADMIN, USER_PASSWORD, Db, login_headers

ME = "/api/auth/me"


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_token_identifies_user(client: TestClient) -> None:
    response = _login(client, ADMIN["email"], ADMIN["password"])
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"

    me = client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["role"] == "admin"


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


@pytest.mark.parametrize("update", [UserUpdate(password="new-password"), UserUpdate(is_active=False)])
def test_access_change_revokes_existing_tokens(
    client: TestClient, add_user: Callable[..., None], db: Db, update: UserUpdate
) -> None:
    add_user("ada@example.com")
    headers = login_headers(client, "ada@example.com", USER_PASSWORD)
    assert client.get(ME, headers=headers).status_code == 200

    async def change(session: AsyncSession) -> None:
        user = (await session.execute(select(User).where(User.email == "ada@example.com"))).scalar_one()
        apply_user_update(user, update)

    db(change)

    assert client.get(ME, headers=headers).status_code == 401
