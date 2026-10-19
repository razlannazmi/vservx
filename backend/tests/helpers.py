"""Shared test constants and helpers. Fixtures live in conftest.py."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

ADMIN = {"email": "admin@example.com", "password": "admin-password"}
USER_PASSWORD = "user-password"

# Type of the `db` fixture: runs fn(session) against the test database and returns its result.
Db = Callable[[Callable[[AsyncSession], Awaitable[Any]]], Any]


def login_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
