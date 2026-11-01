import asyncio
import shutil
import socket
import textwrap
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.password import hash_password
from api.config import get_settings
from api.db import migrate
from api.db.base import utcnow
from api.db.engine import create_engine, create_sessionmaker
from api.enums import WorkspaceRole
from api.main import create_app
from api.models import User, WorkspaceMember
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
def extra_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Stack a throwaway migration 9000 on the real ones: extra_migration("<upgrade() body>")."""

    def add(body: str) -> None:
        location = tmp_path / "migrations"
        head = ScriptDirectory(migrate.SCRIPT_LOCATION).get_current_head()
        shutil.copytree(migrate.SCRIPT_LOCATION, location, ignore=shutil.ignore_patterns("__pycache__"))
        (location / "versions" / "9000_test.py").write_text(
            '"""Add a test column"""\n\nimport sqlalchemy as sa\nfrom alembic import op\n\n'
            f'revision = "9000"\ndown_revision = "{head}"\n\n\ndef upgrade() -> None:\n'
            + textwrap.indent(body, "    ") + "\n"
        )
        monkeypatch.setattr(migrate, "SCRIPT_LOCATION", str(location))

    return add


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
        fields.setdefault("approved_at", utcnow())

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
def workspace(api: TestClient) -> int:
    """A workspace called "Work", owned by the admin."""
    response = api.post("/api/workspaces", json={"name": "Work"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def w(workspace: int) -> str:
    """The workspace's API path, for routes inside it."""
    return f"/api/workspaces/{workspace}"


@pytest.fixture
def member_headers(
    client: TestClient, db: Db, workspace: int, add_user: Callable[..., None]
) -> Callable[[WorkspaceRole], dict[str, str]]:
    """Add <role>@example.com to the workspace with that role and return auth headers for them."""

    def headers(role: WorkspaceRole) -> dict[str, str]:
        email = f"{role.value}@example.com"
        add_user(email)

        async def join(session: AsyncSession) -> None:
            user_id = await session.scalar(select(User.id).where(User.email == email))
            session.add(WorkspaceMember(workspace_id=workspace, user_id=user_id, role=role))

        db(join)
        return login_headers(client, email, USER_PASSWORD)

    return headers


@pytest.fixture
def outsider_headers(client: TestClient, add_user: Callable[..., None]) -> dict[str, str]:
    """An account that belongs to no workspace."""
    add_user("outsider@example.com")
    return login_headers(client, "outsider@example.com", USER_PASSWORD)
