"""Current-role bridge. A role is not ownership."""

from datetime import UTC, date, datetime

from app.domain.models import Evidence
from app.person.current_affiliation import resolve_affiliation
from app.person.current_role_bridge import (
    function_from_role,
    resolve_role_bridge,
    role_queries,
    same_person,
    source_rank,
)

OBSERVED = date(2026, 9, 24)


def _item(
    excerpt: str,
    url: str,
    published: date | None,
    *,
    source_type: str = "company_news",
    evidence_type: str = "body",
) -> Evidence:
    return Evidence(
        id=url,
        observation_id="obs",
        excerpt=excerpt,
        source_url=url,
        source_title=excerpt[:40],
        source_type=source_type,
        published_at=published,
        observed_at=datetime(2026, 9, 24, tzinfo=UTC),
        confidence=0.6,
        lineage=[],
        topics=[],
        supports_problem=False,
        contradicts_redis=False,
        is_explicit_gap=False,
        evidence_type=evidence_type,
    )


def test_role_queries_include_snippet_sources_and_stop_at_ten() -> None:
    queries = role_queries("Ada Lovelace", "Northwind", "northwind.example")
    assert len(queries) == 10
    assert any(query.startswith("site:northwind.example") for query in queries)
    assert any("GitHub" in query for query in queries)


def test_current_role_from_search_snippet() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://news.example/ada",
            None,
            source_type="search_snippet",
            evidence_type="search_snippet",
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "probable_current"
    assert result.employer == "Northwind"
    assert "Platform" in result.title


def test_current_role_from_company_page() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://northwind.example/team/ada",
            date(2026, 6, 1),
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "current"
    assert result.confidence >= 0.7


def test_current_role_from_speaker_bio() -> None:
    evidence = [
        _item(
            "Speaker: Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://conf.example/speakers/ada",
            date(2026, 5, 1),
            source_type="conference",
            evidence_type="speaker_metadata",
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "current"
    assert result.history


def test_role_timeline_keeps_older_titles() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Staff Engineer at Northwind.",
            "https://northwind.example/news/2019",
            date(2019, 1, 1),
        ),
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://northwind.example/news/2026",
            date(2026, 4, 1),
        ),
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert [item.title for item in result.history][0].startswith("Staff")
    assert result.role_state == "current"
    assert "Director" in result.title


def test_stale_role_is_refreshed_by_a_newer_source() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Staff Engineer at Northwind.",
            "https://northwind.example/old",
            date(2023, 1, 1),
        ),
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://news.example/new",
            date(2026, 8, 1),
            source_type="search_snippet",
            evidence_type="search_snippet",
        ),
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert "Director" in result.title
    assert result.role_state == "probable_current"
    assert len(result.history) == 2


def test_wrong_company_is_not_the_current_role() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Otherco.",
            "https://otherco.example/team",
            date(2026, 6, 1),
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "unknown"


def test_ambiguous_same_name_stays_split() -> None:
    assert not same_person(
        "Ada Lovelace",
        "Ada Lovelace",
        left_company="Northwind",
        right_company="Otherco",
        left_topics=["serving"],
        right_topics=["billing"],
    )
    assert same_person(
        "Ada Lovelace",
        "Ada Lovelace",
        left_company="Northwind",
        right_company="Northwind",
        left_topics=["serving"],
        right_topics=[],
    )


def test_current_employer_change_retires_the_old_role() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://northwind.example/old",
            date(2024, 1, 1),
        ),
        _item(
            "Ada Lovelace joined Initech in 2026. Formerly at Northwind.",
            "https://news.example/move",
            date(2026, 8, 1),
            source_type="company_news",
        ),
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.employer == "Initech"
    assert result.role_state == "historical"


def test_role_bridge_sets_function_from_a_specific_title() -> None:
    function, level, source = function_from_role("Director of Platform Engineering")
    assert function == "platform"
    assert level == "strong"
    assert source == "role"
    assert function_from_role("Staff Engineer")[1] == "unknown"


def test_role_bridge_feeds_ownership_without_replacing_it() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://northwind.example/news/ada",
            date(2026, 4, 1),
        ),
        _item(
            "Ada Lovelace led the Northwind platform serving infrastructure.",
            "https://blog.example/serving",
            date(2026, 5, 1),
            source_type="engineering_blog",
        ),
        _item(
            "Platform Engineering owns serving infrastructure. The team is hiring.",
            "https://jobs.example/northwind",
            date(2026, 8, 1),
            source_type="job_posting",
        ),
    ]
    role = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    ownership = resolve_affiliation(
        "Ada Lovelace",
        role.title,
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert role.role_state == "current"
    assert role.function_level == "strong"
    assert ownership.ownership_level == "strong"


def test_search_result_is_ranked_for_fetch_not_treated_as_the_role() -> None:
    assert source_rank("https://northwind.example/team/ada", "northwind.example") < source_rank(
        "https://news.example/ada", "northwind.example"
    )
    assert source_rank("https://www.linkedin.com/in/ada", "northwind.example") == 100


def test_fetched_conference_bio_is_a_current_role() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://conf.example/speakers/ada",
            date(2026, 5, 1),
            source_type="conference",
            evidence_type="speaker_metadata",
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "current"
    assert "Director" in result.title


def test_company_article_bio_states_the_role() -> None:
    evidence = [
        _item(
            "Author: Ada Lovelace, Staff Platform Engineer at Northwind.",
            "https://northwind.example/blog/serving",
            date(2026, 7, 1),
            source_type="engineering_blog",
            evidence_type="author_metadata",
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "current"
    assert result.function_level == "unknown"


def test_github_attribution_can_state_the_role() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Infrastructure at Northwind.",
            "https://github.com/ada",
            date(2026, 8, 1),
            source_type="public_code",
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "current"
    assert result.function == "infrastructure"


def test_cross_source_agreement_raises_role_confidence() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://northwind.example/blog/ada",
            date(2026, 3, 1),
            source_type="engineering_blog",
        ),
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://conf.example/speakers/ada",
            date(2026, 6, 1),
            source_type="conference",
            evidence_type="speaker_metadata",
        ),
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "current"
    assert result.confidence >= 0.85


def test_same_name_collision_does_not_merge() -> None:
    assert not same_person(
        "Ada Lovelace",
        "Ada Lovelace",
        left_company="Northwind",
        right_company="Otherco",
        left_topics=["serving"],
        right_topics=["billing"],
    )


def test_contradictory_page_titles_do_not_become_current() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://northwind.example/team",
            date(2026, 6, 1),
        ),
        _item(
            "Ada Lovelace, Director of Infrastructure at Northwind.",
            "https://conf.example/speakers/ada",
            date(2026, 7, 1),
            source_type="conference",
            evidence_type="speaker_metadata",
        ),
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "unknown"


def test_snippet_only_stays_probable() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://news.example/ada",
            None,
            source_type="search_snippet",
            evidence_type="search_snippet",
        )
    ]
    result = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    assert result.role_state == "probable_current"
    assert result.confidence <= 0.45


def test_resolved_role_without_workload_is_not_strong_ownership() -> None:
    evidence = [
        _item(
            "Ada Lovelace, Director of Platform Engineering at Northwind.",
            "https://northwind.example/team/ada",
            date(2026, 6, 1),
        )
    ]
    role = resolve_role_bridge("Ada Lovelace", evidence, account_name="Northwind", observed_on=OBSERVED)
    ownership = resolve_affiliation(
        "Ada Lovelace",
        role.title,
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert role.role_state == "current"
    assert ownership.ownership_level != "strong"
