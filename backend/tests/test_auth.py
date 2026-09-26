import asyncio
import logging
import re
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from api.auth import CurrentUserDep
from api.auth.password import hash_password, needs_rehash, verify_password
from api.auth.tokens import (
    InvalidToken,
    create_access_token,
    decode_access_token,
    init_tokens,
)
from api.config import get_settings
from api.db.engine import create_engine, create_schema, create_sessionmaker
from api.enums import UserRole
from api.main import create_app
from api.models import User
from api.schemas import UserCreate, UserUpdate
from api.service.users import apply_user_update, user_from_create

HOUR = timedelta(hours=1)


def test_password_round_trip() -> None:
    hashed = hash_password("correct-horse")
    assert "correct-horse" not in hashed
    assert verify_password(hashed, "correct-horse")
    assert not verify_password(hashed, "wrong-horse")
    assert not needs_rehash(hashed)


def test_password_hashes_are_salted() -> None:
    assert hash_password("correct-horse") != hash_password("correct-horse")


def test_verify_password_rejects_malformed_hash() -> None:
    assert not verify_password("not-a-hash", "correct-horse")


def test_token_round_trip(data_dir: Path) -> None:
    init_tokens(data_dir / "jwt.key")
    claims = decode_access_token(create_access_token(7, 3, HOUR))
    assert (claims.user_id, claims.token_version) == (7, 3)


@pytest.mark.parametrize(
    "token",
    [
        lambda: create_access_token(1, 0, timedelta(seconds=-1)),  # expired
        lambda: jwt.encode({"sub": "1", "ver": 0, "iat": 0, "exp": 2**40}, b"a-different-32-byte-signing-key!"),
        lambda: jwt.encode({"sub": "1", "ver": 0, "iat": 0, "exp": 2**40}, None, algorithm="none"),
        lambda: create_access_token(1, 0, HOUR)[:-2] + "xx",  # tampered signature
        lambda: "garbage",
    ],
)
def test_decode_rejects_bad_tokens(data_dir: Path, token) -> None:
    init_tokens(data_dir / "jwt.key")
    with pytest.raises(InvalidToken):
        decode_access_token(token())


def test_jwt_key_is_reused(data_dir: Path) -> None:
    init_tokens(data_dir / "jwt.key")
    token = create_access_token(1, 0, HOUR)
    init_tokens(data_dir / "jwt.key")
    assert decode_access_token(token).user_id == 1


def _user(**overrides) -> User:
    data = UserCreate(name="Ada", email="ada@example.com", password="correct-horse")
    user = user_from_create(data)
    # Column defaults only apply on insert; set it so unsaved users can be revoked.
    for name, value in ({"token_version": 0} | overrides).items():
        setattr(user, name, value)
    return user


def test_user_from_create_hashes_password() -> None:
    user = _user()
    assert verify_password(user.password_hash, "correct-horse")


@pytest.mark.parametrize(
    ("update", "revoked"),
    [
        (UserUpdate(password="new-password"), True),
        (UserUpdate(is_active=False), True),
        (UserUpdate(is_active=True), False),
        (UserUpdate(role="admin", name="Ada L."), False),
    ],
)
def test_apply_user_update_revokes_on_access_change(update: UserUpdate, revoked: bool) -> None:
    user = _user()
    apply_user_update(user, update)
    assert user.token_version == (1 if revoked else 0)


def test_apply_user_update_rehashes_password() -> None:
    user = _user()
    apply_user_update(user, UserUpdate(password="new-password"))
    assert verify_password(user.password_hash, "new-password")
    assert not verify_password(user.password_hash, "correct-horse")


async def _db(data_dir: Path, fn) -> int | None:
    engine = create_engine(data_dir / "vservx.db")
    await create_schema(engine)
    async with create_sessionmaker(engine)() as session:
        result = await fn(session)
        await session.commit()
    await engine.dispose()
    return result


def _add_user(data_dir: Path) -> int:
    async def add(session) -> int:
        user = _user()
        session.add(user)
        await session.flush()
        return user.id

    return asyncio.run(_db(data_dir, add))  # type: ignore[return-value]


def _change_user(data_dir: Path, update: UserUpdate) -> None:
    async def change(session) -> None:
        user = (await session.execute(
            select(User).where(User.email == "ada@example.com")
        )).scalar_one()
        apply_user_update(user, update)

    asyncio.run(_db(data_dir, change))


@pytest.fixture
def auth_client(data_dir: Path) -> Iterator[TestClient]:
    app = create_app()

    @app.get("/me")
    async def me(user: CurrentUserDep) -> dict[str, str]:
        return {"email": user.email}

    with TestClient(app) as client:
        yield client


def _get_me(client: TestClient, token: str):
    return client.get("/me", headers={"Authorization": f"Bearer {token}"})


def test_valid_token_authenticates(auth_client: TestClient, data_dir: Path) -> None:
    token = create_access_token(_add_user(data_dir), 0, HOUR)
    response = _get_me(auth_client, token)
    assert response.status_code == 200
    assert response.json() == {"email": "ada@example.com"}


def test_missing_token_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.get("/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_unknown_user_is_rejected(auth_client: TestClient) -> None:
    assert _get_me(auth_client, create_access_token(999, 0, HOUR)).status_code == 401


@pytest.mark.parametrize(
    "update", [UserUpdate(password="new-password"), UserUpdate(is_active=False)]
)
def test_access_change_revokes_existing_tokens(
    auth_client: TestClient, data_dir: Path, update: UserUpdate
) -> None:
    user_id = _add_user(data_dir)
    old_token = create_access_token(user_id, 0, HOUR)
    assert _get_me(auth_client, old_token).status_code == 200

    _change_user(data_dir, update)

    assert _get_me(auth_client, old_token).status_code == 401


def test_reactivation_does_not_revive_old_tokens(auth_client: TestClient, data_dir: Path) -> None:
    user_id = _add_user(data_dir)
    old_token = create_access_token(user_id, 0, HOUR)
    _change_user(data_dir, UserUpdate(is_active=False))
    _change_user(data_dir, UserUpdate(is_active=True))

    assert _get_me(auth_client, old_token).status_code == 401
    assert _get_me(auth_client, create_access_token(user_id, 1, HOUR)).status_code == 200


async def _all_users(data_dir: Path) -> list[User]:
    engine = create_engine(data_dir / "vservx.db")
    async with create_sessionmaker(engine)() as session:
        users = list((await session.execute(select(User))).scalars())
    await engine.dispose()
    return users


def test_startup_seeds_admin_with_generated_password(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING), TestClient(create_app()):
        pass

    [admin] = asyncio.run(_all_users(data_dir))
    assert admin.email == "admin@example.com"
    assert admin.role is UserRole.ADMIN
    password = re.search(r"generated password: (\S+)", caplog.text).group(1)  # type: ignore[union-attr]
    assert verify_password(admin.password_hash, password)


def test_startup_seeds_only_once(data_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    with TestClient(create_app()):
        pass
    caplog.clear()
    with caplog.at_level(logging.INFO), TestClient(create_app()):
        pass

    assert len(asyncio.run(_all_users(data_dir))) == 1
    assert "Created admin" not in caplog.text


def test_seed_admin_uses_configured_credentials(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("VSERVX_ADMIN_EMAIL", "Ops@Example.com")
    monkeypatch.setenv("VSERVX_ADMIN_PASSWORD", "configured-pass")
    get_settings.cache_clear()

    with caplog.at_level(logging.INFO), TestClient(create_app()):
        pass

    [admin] = asyncio.run(_all_users(data_dir))
    assert admin.email == "ops@example.com"
    assert verify_password(admin.password_hash, "configured-pass")
    assert "configured-pass" not in caplog.text


def test_seed_admin_rejects_invalid_config(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSERVX_ADMIN_PASSWORD", "short")
    get_settings.cache_clear()

    with pytest.raises(ValidationError), TestClient(create_app()):
        pass
