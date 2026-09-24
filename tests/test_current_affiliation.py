"""Affiliation, role, function, and ownership are separate claims."""

from datetime import UTC, date, datetime

from app.domain.models import Evidence, PersonOpportunity, PersonRecord
from app.opportunity.person_opportunity import decide_contact
from app.person.current_affiliation import current_role_search_queries, resolve_affiliation

OBSERVED = date(2026, 9, 24)


def _item(excerpt: str, url: str, published: date | None, **kwargs: object) -> Evidence:
    topics = kwargs.get("topics", [])
    source_type = str(kwargs.get("source_type", "engineering_blog"))
    return Evidence(
        id=url,
        observation_id="o",
        excerpt=excerpt,
        source_url=url,
        source_title="page",
        source_type=source_type,
        published_at=published,
        observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        confidence=0.7,
        lineage=[],
        topics=list(topics) if isinstance(topics, list) else [],
        supports_problem=True,
        contradicts_redis=False,
        is_explicit_gap=False,
    )


def _person(level: str) -> PersonRecord:
    return PersonRecord(
        id="p",
        name="Ada Lovelace",
        title="Staff Engineer",
        company="Northwind",
        identity_excerpt="Ada Lovelace, Staff Engineer at Northwind.",
        identity_confidence=0.8,
        source_urls=["https://northwind.example/blog/ada"],
        seniority=0.4,
        function_guess="platform",
        responsibilities=[],
        activity=[],
        footprint_topics=["low_latency"],
        authored_urls=[],
        persona_id=None,
        ownership_level=level,  # type: ignore[arg-type]
        validity="current",
        responsibility_status="confirmed",
        selection_status="verified_person",
    )


def test_recent_company_article_is_affiliation_not_ownership() -> None:
    evidence = [
        _item(
            "By Ada Lovelace. Northwind serving notes.",
            "https://northwind.example/blog/serving",
            date(2026, 6, 1),
            topics=["low_latency"],
        )
    ]
    result = resolve_affiliation(
        "Ada Lovelace",
        "Staff Engineer",
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert result.affiliation == "current"
    assert result.technical_activity == "strong"
    assert result.ownership_level != "strong"
    assert result.candidate_state == "probable_current_person"


def test_old_role_plus_recent_company_activity_is_probable_current() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Staff Engineer, joined Northwind.",
            "https://northwind.example/blog/old",
            date(2022, 1, 1),
        ),
        _item(
            "By Ada Lovelace. Northwind platform serving path.",
            "https://northwind.example/blog/new",
            date(2026, 5, 1),
            topics=["low_latency"],
        ),
    ]
    result = resolve_affiliation(
        "Ada Lovelace",
        "Staff Engineer",
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert result.role_state == "probable_current"
    assert result.affiliation == "current"
    queries = current_role_search_queries("Ada Lovelace", "Northwind", "northwind.example")
    assert any("2026" in query for query in queries)


def test_role_and_artifact_are_strong_function_and_can_be_strong_ownership() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Distributed Systems Engineer, is on the Northwind engineering page.",
            "https://northwind.example/engineering/ada",
            date(2026, 8, 1),
        ),
        _item(
            "Ada Lovelace spoke about low-latency serving.",
            "https://conf.example/ada",
            date(2026, 7, 1),
            topics=["low_latency"],
            source_type="conference",
        ),
        _item(
            "The platform team owns serving. Reports to the platform lead.",
            "https://northwind.example/jobs/platform",
            date(2026, 8, 2),
            source_type="job_posting",
        ),
    ]
    result = resolve_affiliation(
        "Ada Lovelace",
        "Distributed Systems Engineer",
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform", "distributed systems"],
        observed_on=OBSERVED,
    )
    assert result.function_level == "strong"
    assert result.ownership_level == "strong"
    assert len(result.ownership_evidence_ids) >= 2
    assert result.candidate_state == "verified_current_owner"


def test_title_only_is_weak_and_old_artifact_is_historical() -> None:
    title_only = resolve_affiliation(
        "Ada Lovelace",
        "Engineering Manager",
        [
            _item(
                "Ada Lovelace, Engineering Manager, is listed.",
                "https://northwind.example/people/ada",
                date(2026, 8, 1),
            )
        ],
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    historical = resolve_affiliation(
        "Ada Lovelace",
        "Staff Engineer",
        [
            _item(
                "By Ada Lovelace. Northwind latency notes.",
                "https://northwind.example/blog/old",
                date(2020, 1, 1),
                topics=["low_latency"],
            )
        ],
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert title_only.function_level == "weak"
    assert title_only.ownership_level == "weak"
    assert historical.affiliation == "historical"
    assert historical.technical_activity == "historical"
    assert historical.ownership_level == "unknown"
    assert historical.candidate_state == "historical_person"


def test_affiliation_without_ownership_is_research_more() -> None:
    person = _person("probable")
    row = PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        technical_problem="low-latency serving",
        person_kind="problem_owner",
        why_now_credible=True,
        redis_credible=True,
    )
    assert decide_contact(row, person) == "research_more"


def test_trigger_without_the_person_does_not_contact() -> None:
    person = _person("unknown")
    row = PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        technical_problem="low-latency serving",
        person_kind="access_path",
        why_now_credible=True,
        redis_credible=True,
        trigger_link="",
    )
    assert decide_contact(row, person) != "contact_now"


def test_full_contact_gate_still_requires_strong_ownership() -> None:
    person = _person("strong")
    row = PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        technical_problem="low-latency serving",
        person_kind="problem_owner",
        why_now_credible=True,
        redis_credible=True,
    )
    assert decide_contact(row, person) == "contact_now"
    row.why_now_credible = False
    assert decide_contact(row, person) != "contact_now"
