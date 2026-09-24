"""Current ownership is not the same thing as old technical expertise."""

from datetime import UTC, date, datetime
from pathlib import Path

from app.config import Settings
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.domain.models import Evidence, PersonOpportunity, PersonRecord, WhyNowEvent
from app.laya.adapter import default_kernel
from app.opportunity.person_opportunity import apply_why_now, current_role_queries, decide_contact
from app.person.discovery import Mention
from app.person.freshness import resolve_freshness
from app.pipeline import PLAYBOOK_PATH, execute_run
from app.playbook.selection import load_playbook
from app.research.fetch import FixtureFetcher
from app.research.search import DocumentRecord, MockSearchProvider
from app.sheets.provider import MockSheetsProvider

OBSERVED = date(2026, 9, 24)


def _evidence(excerpt: str, published: date, url: str, topics: list[str]) -> Evidence:
    return Evidence(
        id=url,
        observation_id="o",
        excerpt=excerpt,
        source_url=url,
        source_title="page",
        source_type="blog",
        published_at=published,
        observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        confidence=0.7,
        lineage=[],
        topics=topics,
        supports_problem=True,
        contradicts_redis=False,
        is_explicit_gap=False,
    )


def test_current_queries_ask_for_a_current_role() -> None:
    queries = current_role_queries("Ada Lovelace", "Northwind", "northwind.example", "VP Platform")
    assert any("current role" in query for query in queries)
    assert any("2026" in query for query in queries)
    assert any("site:northwind.example" in query and "Ada Lovelace" in query for query in queries)
    assert any("promoted" in query for query in queries)
    assert any("joined" in query for query in queries)


def test_stale_interview_plus_current_team_page() -> None:
    mentions = [
        Mention(
            "Ada Lovelace",
            "Head of Platform Engineering",
            "https://northwind.example/interview",
            "Ada Lovelace, Head of Platform Engineering, discussed latency.",
            date(2024, 5, 21),
        ),
        Mention(
            "Ada Lovelace",
            "Head of Platform Engineering",
            "https://northwind.example/company/team",
            "Ada Lovelace, Head of Platform Engineering, owns the platform.",
            date(2026, 8, 1),
        ),
    ]
    evidence = [
        _evidence(
            "Ada Lovelace, Head of Platform Engineering, discussed low-latency distributed systems.",
            date(2024, 5, 21),
            "https://northwind.example/interview",
            ["low_latency", "distributed_systems"],
        ),
        _evidence(
            "Ada Lovelace, Head of Platform Engineering, owns the platform search path.",
            date(2026, 8, 1),
            "https://northwind.example/company/team",
            ["low_latency"],
        ),
    ]
    fresh = resolve_freshness("Ada Lovelace", mentions, evidence, observed_on=OBSERVED)
    assert fresh.validity == "current"
    assert "CURRENT_ROLE" in fresh.evidence_classes
    assert "HISTORICAL_EXPERTISE" in fresh.evidence_classes
    assert fresh.current_ownership
    assert fresh.historical_expertise


def test_old_expertise_does_not_establish_current_ownership() -> None:
    mentions = [
        Mention(
            "Ada Lovelace",
            "Head of Platform Engineering",
            "https://northwind.example/interview",
            "Ada Lovelace, Head of Platform Engineering, owns the search path.",
            date(2024, 5, 21),
        )
    ]
    evidence = [
        _evidence(
            "Ada Lovelace, Head of Platform Engineering, owns the low-latency search path.",
            date(2024, 5, 21),
            "https://northwind.example/interview",
            ["low_latency"],
        )
    ]
    fresh = resolve_freshness("Ada Lovelace", mentions, evidence, observed_on=OBSERVED)
    assert fresh.validity == "stale"
    assert fresh.current_ownership == ""
    assert fresh.historical_expertise
    assert "HISTORICAL_EXPERTISE" in fresh.evidence_classes


def test_account_trigger_without_an_owner_is_not_copied() -> None:
    event = WhyNowEvent(
        id="e1",
        event_type="technical_initiative",
        summary="new low-latency workload",
        event_date=date(2026, 8, 1),
        strength=0.6,
        evidence_ids=["launch"],
    )
    launch = _evidence(
        "Northwind launched a low-latency workload.",
        date(2026, 8, 1),
        "https://n.example/l",
        ["low_latency"],
    )
    row = PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        person_name="Ada Lovelace",
        person_kind="problem_owner",
    )
    apply_why_now([row], [event], [launch], people=[])
    assert row.why_now_credible is False
    assert row.trigger_strength == "unknown"


def test_current_owner_links_to_a_current_account_trigger() -> None:
    event = WhyNowEvent(
        id="e1",
        event_type="technical_initiative",
        summary="new low-latency workload",
        event_date=date(2026, 8, 1),
        strength=0.6,
        evidence_ids=["launch"],
    )
    launch = _evidence(
        "Northwind launched a low-latency workload.",
        date(2026, 8, 1),
        "https://n.example/l",
        ["low_latency"],
    )
    person = PersonRecord(
        id="p",
        name="Ada Lovelace",
        title="VP Platform",
        company="Northwind",
        identity_excerpt="Ada Lovelace, VP Platform, owns platform infrastructure.",
        identity_confidence=0.8,
        responsibility_status="confirmed",
        validity="current",
        role_freshness="current",
        current_ownership="Ada Lovelace, VP Platform, owns platform infrastructure.",
        source_urls=["https://northwind.example/team"],
        seniority=0.7,
        function_guess="Platform",
        responsibilities=["owns platform infrastructure"],
        activity=[],
        footprint_topics=["low_latency"],
        authored_urls=[],
        persona_id=None,
    )
    row = PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        person_name="Ada Lovelace",
        person_title="VP Platform",
        person_kind="problem_owner",
        technical_problem="Low-latency serving",
        redis_credible=True,
        redis_hypothesis="low_latency_cache=plausible",
    )
    apply_why_now([row], [event], [launch], people=[person])
    assert row.trigger_strength == "account-linked"
    assert row.why_now == "Current account event affects a function this person currently owns."
    assert "ACCOUNT TRIGGER" in row.trigger_link
    assert decide_contact(row, person) == "contact_now"


def test_person_named_on_the_trigger_is_strong() -> None:
    event = WhyNowEvent(
        id="e1",
        event_type="public_interview",
        summary="talk",
        event_date=date(2026, 8, 1),
        strength=0.7,
        evidence_ids=["talk"],
    )
    talk = _evidence(
        "Ada Lovelace, VP Platform, gave a technical talk on latency.",
        date(2026, 8, 1),
        "https://talks.example/ada",
        ["public_interview", "low_latency"],
    )
    talk.id = "talk"
    row = PersonOpportunity(id="po", account_id="a", person_id="p", person_name="Ada Lovelace")
    apply_why_now([row], [event], [talk])
    assert row.trigger_strength == "strong"
    assert row.why_now_credible is True


def test_account_linked_owner_can_reach_contact_now(tmp_path: Path) -> None:
    docs = [
        DocumentRecord(
            url="https://northwind.example/blog/launch",
            title="Launch",
            source_type="blog",
            published_at="2026-08-01",
            text="Northwind launched Northwind Search. The serving path has to stay low latency.",
        ),
        DocumentRecord(
            url="https://northwind.example/company/team/ada",
            title="Team",
            source_type="biography",
            published_at="2026-08-02",
            text=(
                "Ada Lovelace, Head of Platform Engineering, owns the platform retrieval path. "
                "Northwind platform engineering is responsible for retrieval."
            ),
        ),
        DocumentRecord(
            url="https://talks.example/ada-2024",
            title="Old talk",
            source_type="conference",
            published_at="2024-05-21",
            text=(
                "By Ada Lovelace, Head of Platform Engineering at Northwind. "
                "Low-latency distributed systems matter for interactive search."
            ),
        ),
    ]
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'fresh.db'}", max_pages_per_run=8)
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(make_session_factory(engine)) as session:
        run = execute_run(
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
    person = next(item for item in run.people if item.name == "Ada Lovelace")
    assert person.validity == "current"
    assert person.historical_expertise
    assert person.current_ownership
    opportunity = next(row for row in run.person_opportunities if row.person_name == "Ada Lovelace")
    assert opportunity.trigger_strength == "account-linked"
    assert opportunity.decision == "contact_now"
