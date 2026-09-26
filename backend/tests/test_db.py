import asyncio
from collections.abc import AsyncIterator
from datetime import UTC
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.crypto import init_crypto
from api.db.engine import create_engine, create_schema, create_sessionmaker
from api.enums import AuthType, LaunchType, SnapshotTrigger, UserRole
from api.models import ActionHistory, Instance, Server, Snapshot, User


async def _open_session(data_dir: Path) -> AsyncIterator[AsyncSession]:
    init_crypto(data_dir / "secret.key")
    engine = create_engine(data_dir / "vservx.db")
    await create_schema(engine)
    async with create_sessionmaker(engine)() as session:
        yield session
    await engine.dispose()


def run(data_dir: Path, test) -> None:
    async def main() -> None:
        async for session in _open_session(data_dir):
            await test(session)

    asyncio.run(main())


def _server(**overrides) -> Server:
    fields = dict(name="gpu-1", host="10.0.0.1", username="ubuntu", auth_type=AuthType.PASSWORD)
    return Server(**(fields | overrides))


def test_secrets_are_encrypted_at_rest(data_dir: Path) -> None:
    async def test(session: AsyncSession) -> None:
        session.add(_server(password="hunter2", key_passphrase="s3cret"))
        await session.commit()

        raw = (await session.execute(text("SELECT password, key_passphrase FROM servers"))).one()
        assert "hunter2" not in raw.password
        assert "s3cret" not in raw.key_passphrase

        session.expunge_all()
        server = (await session.execute(select(Server))).scalar_one()
        assert server.password == "hunter2"
        assert server.key_passphrase == "s3cret"

    run(data_dir, test)


def test_key_file_is_reused(data_dir: Path) -> None:
    key_path = data_dir / "secret.key"
    init_crypto(key_path)
    first = key_path.read_bytes()
    init_crypto(key_path)
    assert key_path.read_bytes() == first


def test_timestamps_are_utc_aware(data_dir: Path) -> None:
    async def test(session: AsyncSession) -> None:
        session.add(_server())
        await session.commit()
        session.expunge_all()

        server = (await session.execute(select(Server))).scalar_one()
        assert server.created_at.tzinfo is UTC

    run(data_dir, test)


def test_enums_stored_as_values(data_dir: Path) -> None:
    async def test(session: AsyncSession) -> None:
        server = _server()
        session.add(server)
        await session.flush()
        session.add(Snapshot(server_id=server.id, trigger=SnapshotTrigger.PRE_STOP,
                             launch_type=LaunchType.BARE))
        await session.commit()

        raw = (await session.execute(text("SELECT trigger FROM snapshots"))).scalar_one()
        assert raw == "pre-stop"

    run(data_dir, test)


def _user(**overrides) -> User:
    fields = dict(name="Ada", email="ada@example.com", password_hash="$argon2id$...")
    return User(**(fields | overrides))


def test_user_defaults_and_email_normalized(data_dir: Path) -> None:
    async def test(session: AsyncSession) -> None:
        session.add(_user(email="  Ada@Example.COM "))
        await session.commit()
        session.expunge_all()

        user = (await session.execute(select(User))).scalar_one()
        assert user.email == "ada@example.com"
        assert user.role is UserRole.VIEWER
        assert user.is_active is True
        assert user.token_version == 0
        assert user.last_login_at is None

    run(data_dir, test)


def test_user_email_unique_ignoring_case(data_dir: Path) -> None:
    async def test(session: AsyncSession) -> None:
        session.add(_user())
        await session.commit()

        session.add(_user(email="ADA@example.com"))
        with pytest.raises(IntegrityError):
            await session.commit()

    run(data_dir, test)


def test_foreign_key_actions(data_dir: Path) -> None:
    async def test(session: AsyncSession) -> None:
        server = _server()
        user = _user()
        session.add_all([server, user])
        await session.flush()
        instance = Instance(server_id=server.id, launch_type=LaunchType.DOCKER, ref="abc123")
        session.add(instance)
        await session.flush()
        session.add_all([
            Snapshot(instance_id=instance.id, server_id=server.id,
                     trigger=SnapshotTrigger.DISCOVERY, launch_type=LaunchType.DOCKER),
            ActionHistory(user_id=user.id, server_id=server.id, instance_id=instance.id,
                          action="stop", result="ok"),
        ])
        await session.commit()

        # Instance removed by a rescan: snapshot survives, detached from it.
        await session.execute(text("DELETE FROM instances"))
        assert (await session.execute(text("SELECT instance_id FROM snapshots"))).scalar_one() is None

        # Server removed: its snapshots go, the audit log stays.
        await session.execute(text("DELETE FROM servers"))
        await session.commit()
        assert (await session.execute(text("SELECT count(*) FROM snapshots"))).scalar_one() == 0
        history = (await session.execute(text("SELECT server_id FROM action_history"))).one()
        assert history.server_id is None

        # User removed: the audit log stays, detached from them.
        await session.execute(text("DELETE FROM users"))
        await session.commit()
        history = (await session.execute(text("SELECT user_id FROM action_history"))).one()
        assert history.user_id is None

    run(data_dir, test)


def test_encrypted_column_requires_init(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.db import crypto

    monkeypatch.setattr(crypto, "_fernet", None)
    with pytest.raises(RuntimeError):
        crypto.EncryptedString().process_bind_param("x", None)  # type: ignore[arg-type]
