"""Snippet names are candidates. Verification needs an independent public page."""

from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.laya.adapter import default_kernel
from app.person.snippets import candidates_from_hits
from app.pipeline import PLAYBOOK_PATH, execute_run
from app.playbook.selection import load_playbook
from app.research.fetch import FixtureFetcher
from app.research.search import DocumentRecord, MockSearchProvider, SearchHit
from app.sheets.provider import MockSheetsProvider


def test_snippet_with_name_company_and_role_is_a_candidate() -> None:
    hits = [
        SearchHit(
            url="https://talks.example/agenda",
            title="Northwind at the search summit",
            snippet="Alex Rivera, Staff Engineer at Northwind, discussed retrieval.",
        )
    ]
    found = candidates_from_hits(hits, "Northwind", "Northwind speaker")
    assert found[0].name == "Alex Rivera"
    assert "Staff" in found[0].title


def test_snippet_without_company_is_not_a_candidate() -> None:
    hits = [SearchHit(url="https://talks.example/x", title="Talk", snippet="Alex Rivera, Staff Engineer, spoke.")]
    assert candidates_from_hits(hits, "Northwind", "q") == []


def _run(tmp_path: Path, name: str, docs: list[DocumentRecord], account: str = "Northwind"):
    settings = Settings(database_url=f"sqlite:///{tmp_path / name}.db", max_pages_per_run=8)
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(make_session_factory(engine)) as session:
        return execute_run(
            settings=settings,
            account_name=account,
            domain="contoso.example",
            search=MockSearchProvider(docs),
            fetcher=FixtureFetcher(docs),
            sheets=MockSheetsProvider(),
            kernel=default_kernel("shadow"),
            playbook=load_playbook(PLAYBOOK_PATH),
            session=session,
            observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        )


def test_snippet_candidate_is_rejected_without_an_independent_page(tmp_path: Path) -> None:
    docs = [
        DocumentRecord(
            url="https://news.example/agenda",
            title="Search summit",
            source_type="conference",
            published_at="2026-08-01",
            text=(
                "Contoso launched Contoso Search with retrieval and low latency. "
                "Alex Rivera, Staff Engineer at Contoso, is listed on the agenda."
            ),
        )
    ]
    run = _run(tmp_path, "one", docs, account="Contoso")
    assert any(lead.name == "Alex Rivera" for lead in run.snippet_leads)
    assert all(person.selection_status != "verified_person" for person in run.people)
    assert any("independent" in trace.reason or "responsibility" in trace.reason for trace in run.person_traces)


def test_two_public_sources_can_verify_a_third_party_person(tmp_path: Path) -> None:
    docs = [
        DocumentRecord(
            url="https://contoso.example/blog/search",
            title="Contoso launches search",
            source_type="blog",
            published_at="2026-08-01",
            text=(
                "Contoso launched Contoso Search. "
                "Alex Rivera, Head of Platform Engineering, said the search serving path has to stay low latency. "
                "The platform engineering organization owns the search serving path."
            ),
        ),
        DocumentRecord(
            url="https://talks.example/alex",
            title="Alex Rivera at SearchConf",
            source_type="conference",
            published_at="2026-08-20",
            text=(
                "By Alex Rivera, Head of Platform Engineering at Contoso. "
                "Low-latency distributed systems matter for interactive search."
            ),
        ),
        DocumentRecord(
            url="https://contoso.example/engineering/retrieval",
            title="Retrieval",
            source_type="engineering_blog",
            published_at="2026-07-01",
            text=(
                "Contoso uses a retrieval-augmented generation pipeline. "
                "Platform engineering is responsible for retrieval."
            ),
        ),
    ]
    run = _run(tmp_path, "two", docs, account="Contoso")
    person = next(item for item in run.people if item.name == "Alex Rivera")
    assert len(person.source_urls) >= 2
    assert "contoso.example" in person.source_urls[0] or any("talks.example" in url for url in person.source_urls)
    assert person.footprint_topics
    assert person.selection_status == "verified_person"
    assert run.person_opportunities
    opportunity = next(row for row in run.person_opportunities if row.person_name == "Alex Rivera")
    assert opportunity.why_now_credible is True
    assert opportunity.decision == "contact_now"
