from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["scheduler_running"] is True
