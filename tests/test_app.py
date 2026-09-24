import os
import uuid

import pytest
from fastapi.testclient import TestClient

# Use a dedicated DB index for tests so we never touch real data.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.main import app  # noqa: E402
from app.redis_client import get_client  # noqa: E402


@pytest.fixture(autouse=True)
def clean_redis():
    client = get_client()
    client.flushdb()
    yield
    client.flushdb()


@pytest.fixture
def api():
    return TestClient(app)


def test_health(api):
    resp = api.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "redis": True}


def test_create_get_and_list_lead(api):
    payload = {"name": "Ada Lovelace", "email": "ada@analytical.io", "company": "AE"}
    created = api.post("/leads", json=payload)
    assert created.status_code == 201
    lead = created.json()
    assert lead["id"]
    assert lead["score"] == 0

    fetched = api.get(f"/leads/{lead['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Ada Lovelace"

    listing = api.get("/leads")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_score_ranking(api):
    a = api.post("/leads", json={"name": "A", "email": "a@x.io"}).json()
    b = api.post("/leads", json={"name": "B", "email": "b@x.io"}).json()

    api.post(f"/leads/{b['id']}/score", params={"points": 5})
    api.post(f"/leads/{a['id']}/score", params={"points": 2})

    ranked = api.get("/leads").json()
    assert [lead["name"] for lead in ranked] == ["B", "A"]
    assert ranked[0]["score"] == 5


def test_missing_lead_returns_404(api):
    resp = api.get(f"/leads/{uuid.uuid4().hex}")
    assert resp.status_code == 404
