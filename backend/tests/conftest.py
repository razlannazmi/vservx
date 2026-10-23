import asyncio
import socket
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.password import hash_password
from api.config import get_settings
from api.db.engine import create_engine, create_sessionmaker
from api.enums import UserRole
from api.main import create_app
from api.models import User
from tests.helpers import ADMIN, USER_PASSWORD, Db, login_headers
from tests.sshd import BackgroundLoop, FakeSSHD


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point every test at its own data dir so no test touches ~/.config/vservx."""
    monkeypatch.setenv("VSERVX_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Seed the admin with a known password so tests can sign in as them.
    monkeypatch.setenv("VSERVX_ADMIN_PASSWORD", ADMIN["password"])
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def db(data_dir: Path) -> Db:
    """Run fn(session) against the test database, commit, and return its result."""

    def run(fn: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        async def main() -> Any:
            engine = create_engine(data_dir / "vservx.db")
            try:
                async with create_sessionmaker(engine)() as session:
                    result = await fn(session)
                    await session.commit()
                    return result
            finally:
                await engine.dispose()

        return asyncio.run(main())

    return run


@pytest.fixture
def add_user(client: TestClient, db: Db) -> Callable[..., None]:
    """Insert a user directly; there is no user API yet."""

    def add(email: str, password: str = USER_PASSWORD, **fields: Any) -> None:
        fields.setdefault("password_hash", hash_password(password))

        async def insert(session: AsyncSession) -> None:
            session.add(User(name="Test User", email=email, **fields))

        db(insert)

    return add


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, ADMIN["email"], ADMIN["password"])


@pytest.fixture
def api(client: TestClient, admin_headers: dict[str, str]) -> TestClient:
    """The test client, signed in as the admin."""
    client.headers.update(admin_headers)
    return client


@pytest.fixture(scope="session")
def ssh_loop() -> Iterator[BackgroundLoop]:
    loop = BackgroundLoop()
    yield loop
    loop.stop()


@pytest.fixture
def sshd(ssh_loop: BackgroundLoop) -> Iterator[Callable[..., FakeSSHD]]:
    """Start in-process SSH servers: sshd(password=..., client_key=..., hostname=...)."""
    servers: list[FakeSSHD] = []

    def start(**kwargs: Any) -> FakeSSHD:
        server = FakeSSHD(ssh_loop, **kwargs)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


@pytest.fixture
def closed_port() -> int:
    """A local port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def silent_port() -> Iterator[int]:
    """A local port that accepts TCP connections and never says anything."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        yield sock.getsockname()[1]


@pytest.fixture
def role_headers(client: TestClient, add_user: Callable[..., None]) -> Callable[[UserRole], dict[str, str]]:
    """Add a user with the given role and return auth headers for them."""

    def headers(role: UserRole) -> dict[str, str]:
        email = f"{role.value}@example.com"
        add_user(email, role=role)
        return login_headers(client, email, USER_PASSWORD)

    return headers
