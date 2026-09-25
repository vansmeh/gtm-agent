from datetime import UTC, datetime
from pathlib import Path

from app.brief import render_brief
from app.config import Settings
from app.db.models import PersonRow
from app.db.session import init_db, make_engine, make_session_factory, schema_ddl, session_scope
from app.domain.models import PersonFit
from app.pipeline import run_acme_demo

ROOTS = [
    "app/person",
    "app/graph",
    "app/opportunity",
    "app/signals",
    "app/laya",
    "app/playbook",
    "app/research",
]
FORBIDDEN = ("Jane Smith", "John Doe", "Pat Injected")


def test_ranker_does_not_hardcode_fixture_people() -> None:
    for folder in ROOTS:
        for path in Path(folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in FORBIDDEN:
                assert name not in text, f"{name} hardcoded in {path}"


def test_fit_dimensions_are_explicit() -> None:
    assert "score" not in PersonFit.model_fields


def test_acme_pipeline_selects_from_evidence(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'acme.db'}",
        laya_mode="shadow",
        sheets_provider="mock",
    )
    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        run, sheets = run_acme_demo(session, settings)
        people = session.query(PersonRow).filter(PersonRow.run_id == run.run_id).all()
    rec = run.recommendation
    assert rec is not None
    assert rec.person == "Jane Smith"
    assert "Platform" in rec.role
    assert rec.runner_up == "John Doe"
    assert rec.sent is False
    assert rec.status == "pending_human_review"
    assert rec.contact_inferred_automatically is False
    assert rec.template_id == "platform_rag_latency_v1"
    assert rec.channel == "email"
    assert rec.draft is not None and "Jane Smith" in rec.draft
    assert rec.supporting_evidence
    assert rec.unknown
    assert rec.fit is not None
    jane = next(person for person in run.people if person.name == "Jane Smith")
    john = next(person for person in run.people if person.name == "John Doe")
    assert jane.fit is not None and john.fit is not None
    assert jane.fit.problem_ownership > john.fit.problem_ownership
    assert jane.fit.technical_relevance > john.fit.technical_relevance
    assert john.fit.seniority > jane.fit.seniority
    assert all(person.name != "Pat Injected" for person in run.people)
    assert any(obs.poisoned for obs in run.observations)
    primary = next(item for item in run.opportunities if item.is_primary)
    assert primary.relevance == "plausible"
    assert primary.use_case_id == "low_latency_cache"
    vector = next(item for item in run.opportunities if item.use_case_id == "vector_search")
    assert vector.relevance == "competing_solution_likely"
    assert vector.contradicting_evidence_ids
    assert vector.falsifier
    assert all(item.relevance != "strongly_supported" for item in run.opportunities)
    assert run.laya is not None
    assert run.laya.mode == "shadow"
    assert run.laya.checkpoint_trained_for_redis_gtm is False
    assert run.laya.sent is False
    assert run.laya.next_step != "contact_now"
    assert run.cycle <= 3
    for tab in ("ACCOUNTS", "PEOPLE", "OPPORTUNITIES", "ACTIONS", "RESEARCH LOG", "OUTCOMES"):
        assert sheets.read(tab)
    assert "redis://" not in schema_ddl(engine)
    assert len(people) >= 2
    brief = render_brief(run)
    assert "PERSON: Jane Smith" in brief
    assert "SENT: false" in brief
    assert datetime(2026, 9, 24, tzinfo=UTC)
