import uuid

from fastapi import FastAPI, HTTPException

from .config import settings
from .models import Lead, LeadCreate
from .redis_client import get_client

app = FastAPI(title=settings.app_name, version="0.1.0")

LEAD_INDEX = "leads:index"  # sorted set: lead id -> score


def _lead_key(lead_id: str) -> str:
    return f"lead:{lead_id}"


@app.get("/health")
def health() -> dict:
    """Liveness + Redis connectivity check."""
    try:
        pong = get_client().ping()
    except Exception as exc:  # pragma: no cover - exercised via integration
        raise HTTPException(status_code=503, detail=f"redis unavailable: {exc}")
    return {"status": "ok", "redis": bool(pong)}


@app.post("/leads", response_model=Lead, status_code=201)
def create_lead(payload: LeadCreate) -> Lead:
    client = get_client()
    lead_id = uuid.uuid4().hex[:12]
    lead = Lead(id=lead_id, score=0, **payload.model_dump())
    client.hset(_lead_key(lead_id), mapping=lead.model_dump())
    client.zadd(LEAD_INDEX, {lead_id: 0})
    return lead


@app.get("/leads", response_model=list[Lead])
def list_leads() -> list[Lead]:
    client = get_client()
    # Highest score first.
    ids = client.zrevrange(LEAD_INDEX, 0, -1)
    leads: list[Lead] = []
    for lead_id in ids:
        data = client.hgetall(_lead_key(lead_id))
        if data:
            data["score"] = int(data.get("score", 0))
            leads.append(Lead(**data))
    return leads


@app.get("/leads/{lead_id}", response_model=Lead)
def get_lead(lead_id: str) -> Lead:
    data = get_client().hgetall(_lead_key(lead_id))
    if not data:
        raise HTTPException(status_code=404, detail="lead not found")
    data["score"] = int(data.get("score", 0))
    return Lead(**data)


@app.post("/leads/{lead_id}/score", response_model=Lead)
def bump_score(lead_id: str, points: int = 1) -> Lead:
    """Atomically adjust a lead's engagement score (demonstrates Redis atomics)."""
    client = get_client()
    key = _lead_key(lead_id)
    if not client.exists(key):
        raise HTTPException(status_code=404, detail="lead not found")
    new_score = client.hincrby(key, "score", points)
    client.zadd(LEAD_INDEX, {lead_id: new_score})
    data = client.hgetall(key)
    data["score"] = int(data.get("score", 0))
    return Lead(**data)
