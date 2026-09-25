"""Technical artifacts name candidates. They do not prove current ownership by themselves."""

from datetime import date

from app.domain.models import Evidence
from app.person.artifact_discovery import (
    artifact_queries,
    artifacts_from_evidence,
    candidate_class,
    converge_ownership,
    currentness_for,
    teams_in_text,
)

OBSERVED = date(2026, 9, 24)


def _item(excerpt: str, url: str, published: date | None, **kwargs: object) -> Evidence:
    from datetime import UTC, datetime

    topics = kwargs.get("topics", [])
    source_type = kwargs.get("source_type", "blog")
    return Evidence(
        id=url,
        observation_id="o",
        excerpt=excerpt,
        source_url=url,
        source_title="page",
        source_type=str(source_type),
        published_at=published,
        observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        confidence=0.7,
        lineage=[],
        topics=list(topics) if isinstance(topics, list) else [],
        supports_problem=True,
        contradicts_redis=False,
        is_explicit_gap=False,
    )


def test_artifact_queries_follow_the_signal_not_the_ceo() -> None:
    queries = artifact_queries("Datadog", "datadoghq.com", "Low-latency serving concern")
    assert any("low latency" in query for query in queries)
    assert any("engineering blog" in query for query in queries)
    assert any("github.com" in query for query in queries)
    assert not any(query.lower().startswith("datadog ceo") for query in queries)


def test_blog_author_is_a_candidate() -> None:
    evidence = [
        _item(
            "By Ada Lovelace, Staff Engineer. Northwind low-latency serving path.",
            "https://northwind.example/blog/latency",
            date(2026, 8, 1),
            topics=["low_latency"],
            source_type="engineering_blog",
        )
    ]
    found = artifacts_from_evidence(evidence, "Northwind")
    assert found[0].author == "Ada Lovelace"
    assert found[0].kind == "article"


def test_speaker_and_github_need_a_real_name() -> None:
    talk = _item(
        "By Grace Hopper. Northwind conference talk on distributed systems.",
        "https://conf.example/speakers/grace",
        date(2026, 6, 1),
        topics=["distributed_systems"],
        source_type="conference",
    )
    hidden = _item(
        "octocat pushed a commit. Northwind infrastructure.",
        "https://github.com/northwind/runtime/commit/1",
        date(2026, 6, 1),
    )
    named = _item(
        "By Grace Hopper. Northwind infrastructure commit notes.",
        "https://github.com/northwind/runtime",
        date(2026, 6, 1),
    )
    authors = {item.author for item in artifacts_from_evidence([talk, hidden, named], "Northwind")}
    assert authors == {"Grace Hopper"}
    assert any(item.kind == "talk" for item in artifacts_from_evidence([talk], "Northwind"))
    assert any(item.kind == "github" for item in artifacts_from_evidence([named], "Northwind"))


def test_wrong_company_is_not_a_candidate() -> None:
    evidence = [_item("By Ada Lovelace, Staff Engineer at Contoso.", "https://contoso.example/blog", date(2026, 8, 1))]
    assert artifacts_from_evidence(evidence, "Northwind") == []


def test_historical_artifact_plus_current_role() -> None:
    state = currentness_for(
        artifact_date=date(2024, 5, 21),
        role_date=date(2026, 8, 1),
        text="Ada Lovelace, Staff Engineer, owns the platform path.",
        observed_on=OBSERVED,
    )
    assert state == "current"


def test_person_who_changed_companies_is_not_current_at_the_old_one() -> None:
    state = currentness_for(
        artifact_date=date(2024, 1, 1),
        role_date=date(2026, 3, 1),
        text="Ada Lovelace joined Contoso, formerly at Northwind.",
        observed_on=OBSERVED,
    )
    assert state == "recently_changed"


def test_stale_artifact_without_a_current_role_is_historical() -> None:
    state = currentness_for(
        artifact_date=date(2020, 1, 1),
        role_date=None,
        text="By Ada Lovelace. Northwind latency notes.",
        observed_on=OBSERVED,
    )
    assert state == "historical"


def test_role_artifact_and_team_evidence_can_be_strong() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Staff Engineer, is on the Northwind engineering page.",
            "https://northwind.example/engineering/ada",
            date(2026, 8, 1),
        ),
        _item(
            "Ada Lovelace, Staff Engineer, spoke about low-latency serving.",
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
    level, ids = converge_ownership(
        "Ada Lovelace", "Staff Engineer", evidence, observed_on=OBSERVED, functions=["platform"]
    )
    assert level == "strong"
    assert len(ids) >= 2


def test_title_only_stays_weak() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Staff Engineer, is listed.",
            "https://northwind.example/people/ada",
            date(2026, 8, 1),
        )
    ]
    level, _ids = converge_ownership(
        "Ada Lovelace", "Staff Engineer", evidence, observed_on=OBSERVED, functions=["platform"]
    )
    assert level == "weak"


def test_executive_without_the_workload_is_not_a_technical_owner() -> None:
    assert candidate_class("Chief Executive Officer", workload_connected=False) == "executive"
    assert candidate_class("Staff Engineer", workload_connected=True) == "technical_owner"
    evidence = [
        _item(
            "Olivier Example, Chief Executive Officer, leads the company.",
            "https://northwind.example/about",
            date(2026, 8, 1),
        )
    ]
    level, _ids = converge_ownership(
        "Olivier Example",
        "Chief Executive Officer",
        evidence,
        observed_on=OBSERVED,
        functions=["platform"],
    )
    assert level == "weak"


def test_ambiguous_name_without_a_current_role_stays_unknown() -> None:
    evidence = [
        _item("By Alex Smith. Northwind architecture notes.", "https://northwind.example/blog/a", date(2026, 8, 1)),
        _item("By Alex Smith. Northwind platform notes.", "https://other.example/notes", date(2026, 7, 1)),
    ]
    level, ids = converge_ownership("Alex Smith", "", evidence, observed_on=OBSERVED, functions=["platform"])
    assert level == "unknown"
    assert ids == []


def test_technical_title_without_ownership_is_an_influencer() -> None:
    assert candidate_class("Principal Engineer", workload_connected=False) == "technical_influencer"
    assert candidate_class("Chief Financial Officer", workload_connected=False) == "executive"
    assert candidate_class("Head of Platform", workload_connected=True) == "technical_owner"


def test_team_named_in_an_artifact_is_the_next_search_target() -> None:
    teams = teams_in_text("The Platform Infrastructure team owns the serving path at Northwind.")
    assert any("Platform Infrastructure team" in team for team in teams)
