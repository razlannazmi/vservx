from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.main import create_app


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point every test at its own data dir so no test touches ~/.config/vservx."""
    monkeypatch.setenv("VSERVX_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(data_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app()) as client:
        yield client
