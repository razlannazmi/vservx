"""Shared test constants and helpers. Fixtures live in conftest.py."""

from collections.abc import Awaitable, Callable
from typing import Any

import asyncssh
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


def make_key(passphrase: str | None = None, algorithm: str = "ssh-ed25519") -> tuple[str, asyncssh.SSHKey]:
    """A fresh key: the private key text a user would paste, and the key itself."""
    key = asyncssh.generate_private_key(algorithm)
    return key.export_private_key("openssh", passphrase).decode(), key


def public_line(key: asyncssh.SSHKey) -> str:
    return key.export_public_key().decode().strip()


def create_saved_key(
    client: TestClient, name: str = "lab-key", passphrase: str | None = None
) -> tuple[int, asyncssh.SSHKey]:
    """Save a fresh key through the API. The client must carry admin headers."""
    text, key = make_key(passphrase)
    body = {"name": name, "private_key": text, "passphrase": passphrase}
    response = client.post("/api/ssh-keys", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"], key
