from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import SavedKey
from tests.helpers import Db, make_key


def _stored(db: Db, key_id: int) -> SavedKey | None:
    async def get(session: AsyncSession) -> SavedKey | None:
        return await session.get(SavedKey, key_id)

    return db(get)


def test_create_key_returns_metadata_only(api: TestClient, w: str) -> None:
    key_text, key = make_key()

    response = api.post(f"{w}/ssh-keys", json={"name": "lab-key", "private_key": key_text})

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["key_type"], body["fingerprint"]) == ("lab-key", "ssh-ed25519", key.get_fingerprint())
    assert (body["has_passphrase"], body["server_count"]) == (False, 0)
    assert "PRIVATE KEY" not in response.text


def test_key_and_passphrase_encrypted_at_rest(api: TestClient, w: str, db: Db) -> None:
    key_text, _ = make_key(passphrase="key-passphrase")

    body = {"name": "k", "private_key": key_text, "passphrase": "key-passphrase"}
    key_id = api.post(f"{w}/ssh-keys", json=body).json()["id"]

    async def raw(session: AsyncSession):
        return (await session.execute(text("SELECT private_key, passphrase FROM ssh_keys"))).one()

    row = db(raw)
    assert key_text not in row.private_key
    assert "key-passphrase" not in row.passphrase
    stored = _stored(db, key_id)
    assert (stored.private_key, stored.passphrase) == (key_text, "key-passphrase")


def test_create_rejects_unusable_keys(api: TestClient, w: str) -> None:
    encrypted, _ = make_key(passphrase="pw")

    for body in ({"private_key": "hello"},
                 {"private_key": encrypted},
                 {"private_key": encrypted, "passphrase": "wrong"},
                 {"private_key": "A" * 20_000}):
        assert api.post(f"{w}/ssh-keys", json={"name": "k"} | body).status_code == 422

    assert api.get(f"{w}/ssh-keys").json() == []
