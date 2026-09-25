"""Current role can come from public signals. A snippet is not ownership."""

from datetime import UTC, date, datetime

from app.domain.models import Evidence, PersonOpportunity, PersonRecord
from app.opportunity.person_opportunity import decide_contact
from app.person.current_affiliation import evidence_graph, resolve_affiliation
from app.person.timeline import build_timeline, indexed_profile_queries, team_responsibilities

OBSERVED = date(2026, 9, 24)


def _item(excerpt: str, url: str, published: date | None, **kwargs: object) -> Evidence:
    topics = kwargs.get("topics", [])
    return Evidence(
        id=url,
        observation_id="o",
        excerpt=excerpt,
        source_url=url,
        source_title="page",
        source_type=str(kwargs.get("source_type", "blog")),
        published_at=published,
        observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        confidence=0.7,
        lineage=[],
        topics=list(topics) if isinstance(topics, list) else [],
        supports_problem=True,
        contradicts_redis=False,
        is_explicit_gap=False,
    )


def _resolve(evidence: list[Evidence], title: str = "Director, Production Engineering") -> object:
    return resolve_affiliation(
        "Ada Lovelace",
        title,
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform", "production engineering"],
        observed_on=OBSERVED,
    )


def test_indexed_snippet_sets_probable_role_not_ownership() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director, Production Engineering at Northwind.",
            "https://www.linkedin.com/in/ada",
            None,
            source_type="search_snippet",
        )
    ]
    result = _resolve(evidence)
    assert result.role_state == "probable_current"
    assert result.ownership_level != "strong"
    assert any("linkedin.com/in" in query for query in indexed_profile_queries("Northwind", ["platform"]))


def test_speaker_bio_can_be_a_current_role() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director, Production Engineering at Northwind, spoke about serving.",
            "https://conf.example/speakers/ada",
            date(2026, 6, 1),
            source_type="conference",
            topics=["low_latency"],
        )
    ]
    result = _resolve(evidence)
    assert result.role_state == "current"


def test_newer_role_overrides_an_older_one() -> None:
    evidence = [
        _item("Ada Lovelace, Staff Engineer at Northwind.", "https://old.example/ada", date(2019, 1, 1)),
        _item(
            "Ada Lovelace, Director, Production Engineering at Northwind.",
            "https://northwind.example/news/ada",
            date(2026, 4, 1),
            source_type="company_news",
        ),
    ]
    timeline = build_timeline("Ada Lovelace", "Director, Production Engineering", evidence, observed_on=OBSERVED)
    assert timeline.current is not None
    assert timeline.current.state == "current"
    assert timeline.historical
    result = _resolve(evidence)
    assert result.role_state == "current"


def test_role_and_team_evidence_make_a_strong_function() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director, Production Engineering at Northwind.",
            "https://northwind.example/news/ada",
            date(2026, 4, 1),
            source_type="company_news",
        ),
        _item(
            "Production Engineering owns application serving. The team is hiring.",
            "https://northwind.example/jobs/production",
            date(2026, 8, 1),
            source_type="job_posting",
        ),
    ]
    result = _resolve(evidence)
    assert result.function_level == "strong"
    assert result.ownership_level != "strong"
    mapped = team_responsibilities(evidence, ["production engineering"])
    assert mapped
    assert "Ada Lovelace" not in mapped[0][0] or "owns" in mapped[0][0].lower()


def test_role_artifact_and_team_are_strong_ownership() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director, Production Engineering at Northwind.",
            "https://northwind.example/news/ada",
            date(2026, 4, 1),
            source_type="company_news",
        ),
        _item(
            "Ada Lovelace discussed serving infrastructure at Northwind.",
            "https://northwind.example/blog/serving",
            date(2026, 5, 1),
            topics=["low_latency"],
            source_type="engineering_blog",
        ),
        _item(
            "Production Engineering owns serving infrastructure. The team is hiring.",
            "https://jobs.example/northwind-production",
            date(2026, 8, 1),
            source_type="job_posting",
        ),
    ]
    result = _resolve(evidence)
    assert result.ownership_level == "strong"
    assert len(result.ownership_evidence_ids) == 3


def test_syndicated_copy_does_not_count_twice() -> None:
    text = "Ada Lovelace, Director, Production Engineering at Northwind, discussed serving infrastructure."
    evidence = [
        _item(text, "https://news.example/posts/ada-serving", date(2026, 5, 1), source_type="company_news"),
        _item(text, "https://mirror.example/posts/ada-serving", date(2026, 5, 1), source_type="blog"),
        _item(
            "Production Engineering owns serving. The team is hiring.",
            "https://jobs.example/northwind",
            date(2026, 8, 1),
            source_type="job_posting",
        ),
    ]
    timeline = build_timeline("Ada Lovelace", "Director, Production Engineering", evidence, observed_on=OBSERVED)
    assert timeline.current is not None
    assert len(timeline.historical) == 0
    result = _resolve(evidence)
    assert result.ownership_level != "strong"


def test_article_without_a_current_role_is_not_ownership() -> None:
    evidence = [
        _item(
            "By Ada Lovelace. Northwind latency notes from a past project.",
            "https://northwind.example/blog/old",
            date(2020, 1, 1),
            topics=["low_latency"],
        )
    ]
    result = _resolve(evidence, title="Staff Engineer")
    assert result.technical_activity == "historical"
    assert result.ownership_level != "strong"


def test_contact_gate_still_needs_strong_ownership() -> None:
    person = PersonRecord(
        id="p",
        name="Ada Lovelace",
        title="Director, Production Engineering",
        identity_confidence=0.8,
        source_urls=["https://northwind.example/news/ada"],
        seniority=0.5,
        function_guess="platform",
        responsibilities=[],
        activity=[],
        footprint_topics=[],
        authored_urls=[],
        persona_id=None,
        ownership_level="probable",
        selection_status="verified_person",
        responsibility_status="confirmed",
        validity="current",
    )
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
    person.ownership_level = "strong"
    assert decide_contact(row, person) == "contact_now"


def test_current_role_without_function_evidence_stays_weak() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director, Production Engineering at Northwind.",
            "https://northwind.example/news/ada",
            date(2026, 4, 1),
            source_type="company_news",
        )
    ]
    result = _resolve(evidence)
    assert result.role_state == "current"
    assert result.function_level in {"probable", "weak", "unknown"}
    assert result.ownership_level != "strong"


def test_account_trigger_links_to_function_not_the_person() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director, Production Engineering at Northwind.",
            "https://northwind.example/news/ada",
            date(2026, 4, 1),
            source_type="company_news",
        ),
        _item(
            "Ada Lovelace discussed serving infrastructure at Northwind.",
            "https://northwind.example/blog/serving",
            date(2026, 5, 1),
            topics=["low_latency"],
            source_type="engineering_blog",
        ),
        _item(
            "Production Engineering owns serving infrastructure. The team is hiring.",
            "https://jobs.example/northwind-production",
            date(2026, 8, 1),
            source_type="job_posting",
        ),
    ]
    result = _resolve(evidence)
    edges = evidence_graph(
        "Ada Lovelace",
        result,
        responsibility="serving infrastructure",
        trigger="low-latency serving",
        trigger_evidence_ids=["trigger-1"],
        observed_on=OBSERVED,
    )
    relations = [edge.relation for edge in edges]
    assert relations == [
        "current_affiliation",
        "current_role",
        "current_function",
        "technical_responsibility",
        "account_trigger",
        "technical_expertise",
        "ownership",
    ]
    trigger = next(edge for edge in edges if edge.relation == "account_trigger")
    assert trigger.target == "low-latency serving"
    assert trigger.evidence_ids == ["trigger-1"]
    assert "Ada Lovelace" not in trigger.target
    person = PersonRecord(
        id="p",
        name="Ada Lovelace",
        title="Director, Production Engineering",
        identity_confidence=0.8,
        source_urls=["https://northwind.example/news/ada"],
        seniority=0.5,
        function_guess="platform",
        responsibilities=[],
        activity=[],
        footprint_topics=[],
        authored_urls=[],
        persona_id=None,
        ownership_level="strong",
        selection_status="verified_person",
        responsibility_status="confirmed",
        validity="current",
    )
    row = PersonOpportunity(
        id="po",
        account_id="a",
        person_id="p",
        technical_problem="low-latency serving",
        person_kind="access_path",
        why_now_credible=True,
        redis_credible=True,
    )
    assert decide_contact(row, person) != "contact_now"
