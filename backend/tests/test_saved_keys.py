from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import UserRole
from api.models import SavedKey
from tests.helpers import Db, create_saved_key, make_key

ROUTE = "/api/ssh-keys"


def _stored(db: Db, key_id: int) -> SavedKey | None:
    async def get(session: AsyncSession) -> SavedKey | None:
        return await session.get(SavedKey, key_id)

    return db(get)


def test_create_key_returns_metadata_only(api: TestClient) -> None:
    key_text, key = make_key()

    response = api.post(ROUTE, json={"name": "lab-key", "private_key": key_text})

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["key_type"], body["fingerprint"]) == ("lab-key", "ssh-ed25519", key.get_fingerprint())
    assert (body["has_passphrase"], body["server_count"]) == (False, 0)
    assert "PRIVATE KEY" not in response.text


def test_key_and_passphrase_encrypted_at_rest(api: TestClient, db: Db) -> None:
    key_text, _ = make_key(passphrase="key-passphrase")

    body = {"name": "k", "private_key": key_text, "passphrase": "key-passphrase"}
    key_id = api.post(ROUTE, json=body).json()["id"]

    async def raw(session: AsyncSession):
        return (await session.execute(text("SELECT private_key, passphrase FROM ssh_keys"))).one()

    row = db(raw)
    assert key_text not in row.private_key
    assert "key-passphrase" not in row.passphrase
    stored = _stored(db, key_id)
    assert (stored.private_key, stored.passphrase) == (key_text, "key-passphrase")


def test_create_rejects_unusable_keys(api: TestClient) -> None:
    encrypted, _ = make_key(passphrase="pw")

    for body in ({"private_key": "hello"},
                 {"private_key": encrypted},
                 {"private_key": encrypted, "passphrase": "wrong"},
                 {"private_key": "A" * 20_000}):
        assert api.post(ROUTE, json={"name": "k"} | body).status_code == 422

    assert api.get(ROUTE).json() == []


@pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.OPERATOR])
def test_only_admins_change_keys(
    client: TestClient,
    admin_headers: dict[str, str],
    role_headers: Callable[[UserRole], dict[str, str]],
    role: UserRole,
) -> None:
    client.headers.update(admin_headers)
    key_id, _ = create_saved_key(client)
    client.headers.pop("Authorization")
    headers = role_headers(role)
    key_text, _ = make_key()

    assert client.get(ROUTE, headers=headers).status_code == 200
    assert client.get(f"{ROUTE}/{key_id}", headers=headers).status_code == 200
    assert client.post(ROUTE, json={"name": "x", "private_key": key_text}, headers=headers).status_code == 403
    assert client.patch(f"{ROUTE}/{key_id}", json={"name": "x"}, headers=headers).status_code == 403
    assert client.delete(f"{ROUTE}/{key_id}", headers=headers).status_code == 403
