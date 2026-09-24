"""Current ownership is explicit or strong. A title or an old interview is not enough."""

from datetime import UTC, date, datetime

from app.domain.models import Evidence, PersonOpportunity, PersonRecord, WhyNowEvent
from app.opportunity.person_opportunity import decide_contact, research_gap
from app.person.ownership import (
    affected_functions,
    classify_ownership,
    function_owner_queries,
    job_function_evidence,
)
from app.person.snippets import candidates_from_hits
from app.research.search import SearchHit

OBSERVED = date(2026, 9, 24)


def _item(
    excerpt: str,
    url: str,
    published: date | None,
    *,
    topics: list[str] | None = None,
    source_type: str = "blog",
) -> Evidence:
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
        topics=topics or [],
        supports_problem=True,
        contradicts_redis=False,
        is_explicit_gap=False,
    )


def test_signal_maps_to_owning_functions() -> None:
    functions = affected_functions("Low-latency serving concern")
    assert functions[:3] == ["platform", "infrastructure", "distributed systems"]
    queries = function_owner_queries("Datadog", "datadoghq.com", functions)
    assert any("platform leadership" in query for query in queries)
    assert any("Head of Platform" in query for query in queries)
    assert any("site:linkedin.com/in" in query for query in queries)
    assert not queries[0].lower().startswith("datadog ceo")


def test_explicit_current_owner() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Head of Platform Engineering, owns the low-latency platform path.",
            "https://northwind.example/company/team",
            date(2026, 8, 1),
            topics=["low_latency"],
            source_type="biography",
        )
    ]
    level, ids = classify_ownership(
        "Ada Lovelace", "Head of Platform Engineering", evidence, observed_on=OBSERVED, functions=["platform"]
    )
    assert level == "explicit"
    assert ids


def test_strong_two_source_owner() -> None:
    evidence = [
        _item(
            "Jane Smith, VP Platform, is on the company leadership page.",
            "https://northwind.example/company/team",
            date(2026, 8, 1),
            source_type="biography",
        ),
        _item(
            "Jane Smith discussed platform scalability for interactive search.",
            "https://talks.example/jane",
            date(2026, 7, 1),
            topics=["low_latency"],
            source_type="conference",
        ),
    ]
    level, ids = classify_ownership(
        "Jane Smith", "VP Platform", evidence, observed_on=OBSERVED, functions=["platform"]
    )
    assert level == "strong"
    assert len(ids) == 2


def test_probable_owner_does_not_contact() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Head of Platform Engineering, is listed on the leadership page.",
            "https://northwind.example/about/leadership",
            date(2026, 8, 1),
            source_type="biography",
        ),
        _item(
            "The platform team owns serving. This posting does not name a person.",
            "https://northwind.example/jobs/platform",
            date(2026, 8, 2),
            topics=["low_latency"],
            source_type="job_posting",
        ),
    ]
    level, _ids = classify_ownership(
        "Ada Lovelace",
        "Head of Platform Engineering",
        evidence,
        observed_on=OBSERVED,
        functions=["platform"],
    )
    assert level == "probable"
    person = _person(level)
    row = _row()
    assert decide_contact(row, person) == "human_review"
    assert row.opportunity_tier == "TIER_B_PROBABLE_OWNER"


def test_weak_title_only_never_qualifies() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Staff Engineer, is listed.",
            "https://northwind.example/company/team",
            date(2026, 8, 1),
            source_type="biography",
        )
    ]
    level, _ids = classify_ownership(
        "Ada Lovelace", "Staff Engineer", evidence, observed_on=OBSERVED, functions=["platform"]
    )
    assert level == "weak"


def test_historical_owner_is_not_current() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Head of Platform Engineering, owns the platform path.",
            "https://northwind.example/blog/old",
            date(2024, 5, 21),
            topics=["low_latency"],
            source_type="blog",
        )
    ]
    level, _ids = classify_ownership(
        "Ada Lovelace", "Head of Platform Engineering", evidence, observed_on=OBSERVED, functions=["platform"]
    )
    assert level == "unknown"


def test_syndicated_copy_is_not_an_independent_source() -> None:
    evidence = [
        _item(
            "Jane Smith, VP Platform, discussed platform scalability for interactive search.",
            "https://northwind.example/blog/jane-platform",
            date(2026, 8, 1),
            topics=["low_latency"],
        ),
        _item(
            "Jane Smith, VP Platform, discussed platform scalability for interactive search.",
            "https://copies.example/jane-platform",
            date(2026, 8, 1),
            topics=["low_latency"],
        ),
    ]
    level, _ids = classify_ownership(
        "Jane Smith", "VP Platform", evidence, observed_on=OBSERVED, functions=["platform"]
    )
    assert level != "strong"


def test_job_posting_establishes_function_not_a_person() -> None:
    posting = _item(
        "Platform engineering reports to the Head of Platform and owns low-latency serving.",
        "https://northwind.example/jobs/platform",
        date(2026, 8, 1),
        topics=["hiring_platform", "low_latency"],
        source_type="job_posting",
    )
    found = job_function_evidence([posting])
    assert found == [posting]
    assert "Ada" not in posting.excerpt


def test_linkedin_snippet_discovers_but_is_not_identity() -> None:
    hits = [
        SearchHit(
            url="https://www.linkedin.com/in/ada",
            title="Ada Lovelace - Northwind",
            snippet="Ada Lovelace, Head of Platform Engineering at Northwind.",
        )
    ]
    found = candidates_from_hits(hits, "Northwind", "site:linkedin.com/in Northwind")
    assert found[0].name == "Ada Lovelace"
    from app.research.search import is_allowed_public_url

    assert not is_allowed_public_url(found[0].url)


def test_explicit_owner_and_current_trigger_can_contact() -> None:
    person = _person("explicit")
    row = _row()
    row.why_now_credible = True
    row.redis_credible = True
    row.technical_problem = "Low-latency serving"
    row.person_kind = "problem_owner"
    assert decide_contact(row, person) == "contact_now"


def test_missing_owner_names_the_function() -> None:
    missing, question = research_gap(
        account_name="Datadog",
        problem="Low-latency serving concern",
        has_owner=False,
        has_trigger=False,
        has_hypothesis=True,
        functions=["platform", "infrastructure"],
    )
    assert "Current Platform owner" in missing
    assert "Platform leadership" in question
    assert "Datadog" in question


def _person(level: str) -> PersonRecord:
    return PersonRecord(
        id="p",
        name="Ada Lovelace",
        title="Head of Platform Engineering",
        company="Northwind",
        identity_excerpt="Ada Lovelace, Head of Platform Engineering.",
        identity_confidence=0.8,
        responsibility_status="confirmed",
        validity="current",
        ownership_level=level,  # type: ignore[arg-type]
        source_urls=["https://northwind.example/company/team"],
        seniority=0.7,
        function_guess="Platform",
        responsibilities=[],
        activity=[],
        footprint_topics=["low_latency"],
        authored_urls=[],
        persona_id=None,
    )


def _row() -> PersonOpportunity:
    event = WhyNowEvent(
        id="e",
        event_type="technical_initiative",
        summary="latency",
        event_date=date(2026, 8, 1),
        strength=0.5,
        evidence_ids=["x"],
    )
    del event
    return PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        person_name="Ada Lovelace",
        person_kind="access_path",
        technical_problem="Low-latency serving",
        why_now_credible=True,
        redis_credible=True,
    )
