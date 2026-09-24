"""PersonOpportunity is the unit of action. Seniority does not pick the contact."""

from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.db.models import PersonOpportunityRow
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.laya.adapter import default_kernel
from app.pipeline import PLAYBOOK_PATH, execute_run
from app.playbook.selection import load_playbook
from app.research.fetch import FixtureFetcher
from app.research.search import DocumentRecord, MockSearchProvider
from app.sheets.provider import MockSheetsProvider


def _doc(url: str, title: str, source_type: str, published: str | None, text: str) -> DocumentRecord:
    return DocumentRecord(url=url, title=title, source_type=source_type, published_at=published, text=text)


def _run(tmp_path: Path, name: str, docs: list[DocumentRecord], account: str = "Northwind"):
    settings = Settings(database_url=f"sqlite:///{tmp_path / name}.db", max_pages_per_run=8)
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(make_session_factory(engine)) as session:
        run = execute_run(
            settings=settings,
            account_name=account,
            domain="northwind.example",
            search=MockSearchProvider(docs),
            fetcher=FixtureFetcher(docs),
            sheets=MockSheetsProvider(),
            kernel=default_kernel("shadow"),
            playbook=load_playbook(PLAYBOOK_PATH),
            session=session,
            observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        )
        stored = session.query(PersonOpportunityRow).filter(PersonOpportunityRow.run_id == run.run_id).all()
    return run, stored


OWNER = [
    _doc(
        "https://northwind.example/blog/search",
        "Northwind launches search",
        "blog",
        "2026-08-01",
        "Northwind launched Northwind Search. "
        "Ada Lovelace, Head of Platform Engineering, said the search serving path has to stay low latency. "
        "The platform engineering organization owns the search serving path.",
    ),
    _doc(
        "https://northwind.example/engineering/retrieval",
        "Retrieval notes",
        "engineering_blog",
        "2026-07-01",
        "Northwind uses a retrieval-augmented generation pipeline. "
        "Platform engineering is responsible for the retrieval service.",
    ),
    _doc(
        "https://ada.example/writing/latency",
        "Latency notes",
        "personal_technical_writing",
        "2026-06-01",
        "By Ada Lovelace, Head of Platform Engineering at Northwind. "
        "Low-latency distributed systems matter for interactive search.",
    ),
]

MULTI = OWNER + [
    _doc(
        "https://github.com/northwind/platform",
        "Platform notes",
        "public_code",
        "2026-08-15",
        "Riley Chen, Director of Platform Engineering, is listed on the Northwind platform page.",
    ),
    _doc(
        "https://northwind.example/news/leadership",
        "Leadership",
        "company_news",
        "2026-08-20",
        "John Doe, VP Engineering, leads the engineering organization at Northwind. "
        "This page does not connect him to search or retrieval.",
    ),
]

TITLE_ONLY = [
    _doc(
        "https://northwind.example/blog/search",
        "Launch",
        "blog",
        "2026-08-01",
        "Northwind launched Northwind Search. Grace Hopper, VP Engineering, welcomed the company update.",
    ),
    _doc(
        "https://northwind.example/engineering/retrieval",
        "Retrieval",
        "engineering_blog",
        "2026-07-01",
        "Northwind uses retrieval in an interactive search prototype.",
    ),
]

OLD = [
    _doc(
        "https://northwind.example/engineering/old",
        "Old notes",
        "engineering_blog",
        "2020-01-01",
        "Northwind described retrieval and low latency. "
        "Ada Lovelace, Head of Platform Engineering, said the search serving path has to stay low latency. "
        "The platform engineering organization owns the search serving path.",
    ),
]

CONFLICT = [
    _doc(
        "https://northwind.example/blog/search",
        "Launch",
        "blog",
        "2026-08-01",
        "Northwind launched Northwind Search. "
        "Ada Lovelace, Head of Platform Engineering, said the search serving path has to stay low latency. "
        "The platform engineering organization owns the search serving path.",
    ),
    _doc(
        "https://northwind.example/news/sales",
        "Sales",
        "company_news",
        "2026-08-15",
        "Ada Lovelace, VP Sales, welcomed customers at Northwind.",
    ),
]


def test_person_opportunity_is_created(tmp_path: Path) -> None:
    run, stored = _run(tmp_path, "create", OWNER)
    assert run.person_opportunities
    assert stored
    row = stored[0]
    assert row.account_id == run.account_id
    assert row.person_id
    assert row.technical_problem
    assert row.status == "pending_human_review"


def test_problem_owner_is_selected_over_executive(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "owner", MULTI)
    primary = next(row for row in run.person_opportunities if row.thread_role == "primary_contact")
    executive = next(row for row in run.person_opportunities if row.person_kind == "executive")
    owner = next(person for person in run.people if person.name == "Ada Lovelace")
    sponsor = next(person for person in run.people if person.name == "John Doe")
    assert primary.person_name == "Ada Lovelace"
    assert primary.person_kind == "problem_owner"
    assert executive.person_name == "John Doe"
    assert owner.fit is not None and sponsor.fit is not None
    assert sponsor.fit.seniority > owner.fit.seniority
    assert primary.decision == "contact_now"
    assert executive.decision != "contact_now"
    assert primary.angle != executive.angle


def test_access_path_is_not_the_owner(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "access", MULTI)
    access = next(row for row in run.person_opportunities if row.person_name == "Riley Chen")
    assert access.person_kind == "access_path"
    assert access.thread_role == "secondary_contact"
    assert access.decision != "contact_now"
    assert access.recommended_channel == "linkedin"
    primary = next(row for row in run.person_opportunities if row.thread_role == "primary_contact")
    assert primary.recommended_channel == "email"
    assert primary.recommended_channel != access.recommended_channel


def test_contactability_does_not_invent_email(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "contact", OWNER)
    row = next(item for item in run.person_opportunities if item.person_name == "Ada Lovelace")
    assert row.contactability.public_email is False
    assert row.contactability.known_role is True
    assert row.contactability.level in {"medium", "low"}
    assert row.contactability.public_technical_presence is True


def test_contact_now_requires_problem_owner_trigger_and_hypothesis(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "bar", OWNER)
    row = run.person_opportunities[0]
    assert row.decision == "contact_now"
    assert row.why_now_credible is True
    assert row.redis_credible is True
    assert row.template_id == "platform_rag_latency_v1"
    assert run.laya is not None
    assert run.laya.contact_decision == "research_more"
    assert run.laya.next_step != "contact_now"


def test_missing_why_now_does_not_contact(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "old", OLD)
    assert run.person_opportunities
    assert all(row.decision != "contact_now" for row in run.person_opportunities)
    assert all(row.why_now == "unknown" for row in run.person_opportunities)


def test_missing_ownership_does_not_contact(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "title", TITLE_ONLY)
    assert all(row.person_kind != "problem_owner" for row in run.person_opportunities)
    assert all(row.decision != "contact_now" for row in run.person_opportunities)


def test_contradictory_person_is_not_contacted(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "conflict", CONFLICT)
    row = next(item for item in run.person_opportunities if item.person_name == "Ada Lovelace")
    assert row.decision == "ignore"


def test_template_follows_the_person_opportunity(tmp_path: Path) -> None:
    run, _stored = _run(tmp_path, "template", MULTI)
    primary = next(row for row in run.person_opportunities if row.thread_role == "primary_contact")
    others = [row for row in run.person_opportunities if row.id != primary.id]
    assert primary.template_id == "platform_rag_latency_v1"
    assert all(row.template_id != primary.template_id for row in others)
