from fastapi.testclient import TestClient

from api.version import __version__


def test_root_points_to_docs(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "vservx",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/health",
    }


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
