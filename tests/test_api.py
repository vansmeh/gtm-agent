from pathlib import Path

from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_health_and_demo(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'api.db'}",
            laya_mode="shadow",
            sheets_provider="mock",
        )
    )
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["database"] == "sqlite"
    assert body["redis_role"] == "gtm_product_under_research"
    demo = client.post("/demo/acme-ai")
    assert demo.status_code == 200
    payload = demo.json()
    assert "Jane Smith" in payload["brief"]
    assert payload["recommendation"]["sent"] is False
    run_id = payload["run_id"]
    fetched = client.get(f"/runs/{run_id}")
    assert fetched.status_code == 200
    missing = client.get("/runs/missing")
    assert missing.status_code == 404
