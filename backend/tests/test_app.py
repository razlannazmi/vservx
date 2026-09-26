import asyncio
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.config import Settings
from api.db.crypto import init_crypto
from api.db.engine import create_engine, create_schema, create_sessionmaker
from api.enums import AuthType
from api.main import create_app
from api.models import Server


async def _add_server(data_dir: Path, **fields) -> None:
    engine = create_engine(data_dir / "vservx.db")
    await create_schema(engine)
    async with create_sessionmaker(engine)() as session:
        session.add(Server(name="gpu-1", host="10.0.0.1", username="ubuntu",
                           auth_type=AuthType.PASSWORD, **fields))
        await session.commit()
    await engine.dispose()


async def _read_password(data_dir: Path) -> str | None:
    engine = create_engine(data_dir / "vservx.db")
    async with create_sessionmaker(engine)() as session:
        password = (await session.execute(select(Server.password))).scalar_one()
    await engine.dispose()
    return password


def test_data_dir_expands_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSERVX_DATA_DIR", "~/vservx-test")
    assert Settings().data_dir == Path.home() / "vservx-test"


def test_init_crypto_reports_new_key(data_dir: Path) -> None:
    assert init_crypto(data_dir / "secret.key") is True
    assert init_crypto(data_dir / "secret.key") is False


def test_undecryptable_secret_reads_as_none(data_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    init_crypto(data_dir / "secret.key")
    asyncio.run(_add_server(data_dir, password="hunter2"))

    (data_dir / "secret.key").unlink()
    init_crypto(data_dir / "secret.key")

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(_read_password(data_dir)) is None
    assert "could not be decrypted" in caplog.text


def test_startup_warns_when_key_replaced(data_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    init_crypto(data_dir / "secret.key")
    asyncio.run(_add_server(data_dir, password="hunter2"))
    (data_dir / "secret.key").unlink()

    with caplog.at_level(logging.WARNING), TestClient(create_app()):
        pass
    assert "1 server(s) have stored secrets" in caplog.text


def test_startup_quiet_on_first_run(data_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING), TestClient(create_app()):
        pass
    assert "stored secrets" not in caplog.text


def test_integrity_error_returns_409(data_dir: Path) -> None:
    app = create_app()

    @app.post("/boom")
    async def boom() -> None:
        raise IntegrityError("INSERT ...", {}, Exception("UNIQUE constraint failed: servers.name"))

    with TestClient(app) as client:
        response = client.post("/boom")

    assert response.status_code == 409
    assert response.json() == {"detail": "UNIQUE constraint failed: servers.name"}
