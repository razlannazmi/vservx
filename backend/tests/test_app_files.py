from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.main import create_app


def test_app_files_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>vservx</title>")
    (ui / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("VSERVX_UI_DIR", str(ui))
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert "<title>vservx</title>" in client.get("/").text
        # A link into the app works on refresh.
        assert "<title>vservx</title>" in client.get("/workspaces/homelab/servers/2").text
        assert client.get("/assets/app.js").text == "console.log(1)"
        missing = client.get("/api/nope")
        assert missing.status_code == 404 and missing.headers["content-type"].startswith("application/json")
