"""HTTP API. It records recommendations. It does not send outreach."""

from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import __version__
from app.brief import render_brief
from app.config import Settings, get_settings
from app.db.models import ActionRow, RecommendationRow
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.domain.models import RunModel
from app.persistence.store import Store
from app.pipeline import PLAYBOOK_PATH, build_kernel, execute_run, run_acme_demo
from app.playbook.selection import load_playbook
from app.sheets.provider import build_sheets_provider


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = ""


class OutcomeIn(BaseModel):
    result: str = Field(min_length=1, max_length=80)
    notes: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    engine = make_engine(cfg.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    app = FastAPI(title=cfg.app_name, version=__version__)
    playbook = load_playbook(PLAYBOOK_PATH)

    @app.get("/health")
    def health() -> dict[str, str]:
        with session_scope(factory) as session:
            session.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {
            "status": "ok",
            "database": "sqlite",
            "laya_mode": cfg.laya_mode,
            "sheets": cfg.sheets_provider,
            "redis_role": "gtm_product_under_research",
        }

    @app.post("/accounts")
    def create_account(payload: AccountIn) -> dict[str, str]:
        with session_scope(factory) as session:
            run = _run_named(session, cfg, playbook, payload.name, payload.domain)
        return {"run_id": run.run_id, "account_id": run.account_id}

    @app.post("/demo/acme-ai")
    def demo_acme() -> dict[str, object]:
        with session_scope(factory) as session:
            run, _sheets = run_acme_demo(session, cfg)
        rec = run.recommendation
        return {
            "run_id": run.run_id,
            "brief": render_brief(run),
            "recommendation": None if rec is None else rec.model_dump(mode="json"),
        }

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, object]:
        with session_scope(factory) as session:
            row = session.query(RecommendationRow).filter(RecommendationRow.run_id == run_id).one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="run not found")
            return {"run_id": run_id, "brief_json": row.brief_json, "sent": row.sent, "status": row.status}

    @app.post("/actions/{action_id}/outcomes")
    def record_outcome(action_id: str, payload: OutcomeIn) -> dict[str, object]:
        with session_scope(factory) as session:
            action = session.get(ActionRow, action_id)
            if action is None:
                raise HTTPException(status_code=404, detail="action not found")
            outcome = Store(session).record_outcome(
                action_id,
                payload.result,
                payload.notes,
                datetime.now(UTC),
            )
            return {
                "outcome_id": outcome.id,
                "ranking_updated": outcome.ranking_updated,
                "note": "Outcome stored. Person ranking was not changed.",
            }

    return app


def _run_named(session: Session, cfg: Settings, playbook: object, name: str, domain: str) -> RunModel:
    from app.pipeline import default_providers
    from app.playbook.selection import Playbook

    if not isinstance(playbook, Playbook):
        raise TypeError("playbook")
    search, fetcher = default_providers(cfg)
    sheets = build_sheets_provider(
        provider=cfg.sheets_provider,
        spreadsheet_id=cfg.google_sheets_spreadsheet_id,
        credentials_file=cfg.google_credentials_file,
    )
    return execute_run(
        settings=cfg,
        account_name=name,
        domain=domain,
        search=search,
        fetcher=fetcher,
        sheets=sheets,
        kernel=build_kernel(cfg),
        playbook=playbook,
        session=session,
    )


app = create_app()
