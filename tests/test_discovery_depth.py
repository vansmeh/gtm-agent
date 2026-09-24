"""Discovery depth. The contact gate is unchanged."""

from datetime import UTC, date, datetime
from pathlib import Path

from app.config import Settings
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.domain.models import Evidence, PersonHypothesis, TechnicalSignal, WhyNowEvent
from app.laya.adapter import default_kernel
from app.opportunity.person_opportunity import (
    apply_why_now,
    c_suite_without_specialist_role,
    hypotheses_for,
    research_gap,
)
from app.pipeline import PLAYBOOK_PATH, execute_run
from app.playbook.selection import load_playbook
from app.research.bounds import person_discovery_queries, source_rank
from app.research.fetch import FixtureFetcher
from app.research.search import DocumentRecord, MockSearchProvider
from app.sheets.provider import MockSheetsProvider


def test_signal_maps_to_several_functions() -> None:
    rag = TechnicalSignal(
        id="s1", signal_type="rag_architecture", label="Retrieval-augmented generation", confidence=0.8, evidence_ids=[]
    )
    latency = TechnicalSignal(
        id="s2", signal_type="low_latency_serving", label="Low-latency serving", confidence=0.7, evidence_ids=[]
    )
    rag_h, latency_h = hypotheses_for([rag, latency])
    assert 3 <= len(rag_h.likely_functions) <= 5
    assert {"AI/ML", "Search", "Platform Engineering"} <= set(rag_h.likely_functions)
    assert {"Platform", "Infrastructure", "Backend", "Architecture"} <= set(latency_h.likely_functions)
    assert rag_h.rationale
    for hypothesis in (rag_h, latency_h):
        assert isinstance(hypothesis, PersonHypothesis)
        for role in ("Head", "Director", "VP", "Principal", "Staff", "Architect", "Engineering Manager"):
            assert role in hypothesis.candidate_role_families


def test_footprint_and_trigger_queries_cover_public_topics() -> None:
    from app.opportunity.person_opportunity import footprint_queries, trigger_queries

    footprint = footprint_queries("Alex Rivera", "Contoso", "search")
    triggers = trigger_queries("Alex Rivera", "Contoso")
    for topic in ("RAG", "search", "vector", "infrastructure", "platform", "latency", "distributed systems"):
        assert any(topic in query and "Alex Rivera" in query and "Contoso" in query for query in footprint)
    for trigger in ("promotion", "new role", "technical talk", "article", "hiring", "architecture"):
        assert any(trigger in query and "Alex Rivera" in query for query in triggers)


def test_discovery_queries_prefer_technical_sources() -> None:
    queries = person_discovery_queries("Redis", "redis.io", "Search", "vector search")
    assert any("conference" in query for query in queries)
    assert any("speaker" in query for query in queries)
    assert any("github.com" in query for query in queries)
    assert any("architect" in query for query in queries)
    assert not queries[0].startswith("site:redis.io team")
    assert source_rank("https://redis.io/blog/vector-search/", "redis.io") < source_rank(
        "https://redis.io/company/team/someone/", "redis.io"
    )


def test_c_suite_is_not_a_specialist_role() -> None:
    assert c_suite_without_specialist_role("Chief Executive Officer")
    assert not c_suite_without_specialist_role("Head of Platform Engineering")
    assert not c_suite_without_specialist_role("VP Engineering")
    assert not c_suite_without_specialist_role("Staff Engineer")


def test_account_trigger_is_not_copied_onto_a_person() -> None:
    from app.domain.models import PersonOpportunity

    event = WhyNowEvent(
        id="e1",
        event_type="product_launch",
        summary="account launch",
        event_date=date(2026, 8, 1),
        strength=0.5,
        evidence_ids=["ev-account"],
    )
    other = Evidence(
        id="ev-account",
        observation_id="o",
        excerpt="Northwind launched search.",
        source_url="https://northwind.example/blog",
        source_title="launch",
        source_type="blog",
        published_at=date(2026, 8, 1),
        observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        confidence=0.7,
        lineage=[],
        topics=["ai_search"],
        supports_problem=True,
        contradicts_redis=False,
        is_explicit_gap=False,
    )
    row = PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        person_name="Ada Lovelace",
        person_kind="problem_owner",
    )
    apply_why_now([row], [event], [other])
    assert row.why_now == "unknown"
    assert row.why_now_credible is False


def test_next_question_names_the_missing_owner() -> None:
    missing, question = research_gap(
        account_name="Redis",
        problem="vector search",
        has_owner=False,
        has_trigger=False,
        has_hypothesis=True,
    )
    assert "Current Platform owner" in missing
    assert "current trigger linked to a current owner" in missing
    assert question == "Find current Redis Platform leadership and verify ownership of vector search."


def _run(tmp_path: Path, docs: list[DocumentRecord]):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'disc.db'}", max_pages_per_run=8)
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(make_session_factory(engine)) as session:
        return execute_run(
            settings=settings,
            account_name="Northwind",
            domain="northwind.example",
            search=MockSearchProvider(docs),
            fetcher=FixtureFetcher(docs),
            sheets=MockSheetsProvider(),
            kernel=default_kernel("shadow"),
            playbook=load_playbook(PLAYBOOK_PATH),
            session=session,
            observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        )


def test_c_suite_candidate_is_rejected_with_a_reason(tmp_path: Path) -> None:
    docs = [
        DocumentRecord(
            url="https://northwind.example/blog/search",
            title="Launch",
            source_type="blog",
            published_at="2026-08-01",
            text="Northwind launched Northwind Search with retrieval and low latency.",
        ),
        DocumentRecord(
            url="https://northwind.example/company/team/rowan",
            title="CEO",
            source_type="biography",
            published_at="2026-08-01",
            text="Rowan Trollope\nChief Executive Officer\nRowan leads Northwind.",
        ),
    ]
    run = _run(tmp_path, docs)
    rejected = [
        trace
        for trace in run.person_traces
        if trace.candidate == "Rowan Trollope" and trace.decision == "reject"
    ]
    assert rejected
    assert "C-suite" in rejected[0].reason or "responsibility" in rejected[0].reason
    assert all(person.selection_status != "verified_person" for person in run.people)
    assert run.next_research_question.startswith("Find current Northwind")
