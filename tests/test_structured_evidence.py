"""Structured metadata and snippets are evidence. They are not ownership."""

from datetime import UTC, date, datetime

from app.domain.models import Evidence
from app.person.attribution import attributions_in, strengthens_expertise
from app.person.current_affiliation import resolve_affiliation
from app.research.structured import (
    dedupe_facts,
    extract_structured,
    mark_contradictions,
    snippet_role_facts,
)

OBSERVED = datetime(2026, 9, 24, tzinfo=UTC)


def test_meta_author_and_json_ld_and_speaker() -> None:
    html = """
    <html><head>
      <meta name="author" content="Ada Lovelace">
      <meta name="speaker" content="Grace Hopper">
      <script type="application/ld+json">
        {"@type":"Article","author":{"@type":"Person","name":"Ada Lovelace",
        "jobTitle":"Director of Platform Engineering",
        "worksFor":{"@type":"Organization","name":"Northwind"}}}
      </script>
    </head><body><p>Northwind serving notes.</p></body></html>
    """
    facts = extract_structured(html, "https://northwind.example/blog/serving")
    fields = {fact.field for fact in facts}
    assert "author" in fields
    assert "speaker" in fields
    assert any("Ada Lovelace" in fact.sentence for fact in facts)


def test_company_team_structured_data() -> None:
    html = """
    <html><body>
      <div class="team-member">Ada Lovelace, Director of Platform Engineering</div>
    </body></html>
    """
    facts = extract_structured(html, "https://northwind.example/team")
    assert any(fact.field == "team_member" and fact.value == "Ada Lovelace" for fact in facts)


def test_search_snippet_is_probable_role_not_ownership() -> None:
    facts = snippet_role_facts(
        title="Ada Lovelace | Director of Platform Engineering | Northwind",
        snippet="Public profile",
        url="https://news.example/ada",
        account_name="Northwind",
        observed_at=OBSERVED,
    )
    assert facts
    assert facts[0].evidence_type == "search_snippet"
    result = resolve_affiliation(
        "Ada Lovelace",
        "Director of Platform Engineering",
        facts,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=date(2026, 9, 24),
    )
    assert result.role_state == "probable_current"
    assert result.ownership_level != "strong"


def test_interviewee_is_not_current_ownership() -> None:
    evidence = [
        Evidence(
            id="e",
            observation_id="o",
            excerpt="I had the pleasure of hosting Ada Lovelace, Director of Platform Engineering at Northwind.",
            source_url="https://logz.io/talk",
            source_title="talk",
            source_type="interview",
            published_at=date(2026, 6, 1),
            observed_at=OBSERVED,
            confidence=0.6,
            lineage=[],
            topics=["low_latency"],
            supports_problem=True,
            contradicts_redis=False,
            is_explicit_gap=False,
            evidence_type="interviewee",
        )
    ]
    result = resolve_affiliation(
        "Ada Lovelace",
        "Director of Platform Engineering",
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=date(2026, 9, 24),
    )
    assert result.ownership_level != "strong"
    assert result.technical_activity != "strong"
    hosted = attributions_in(evidence[0].excerpt, evidence[0].source_url)
    assert ("Ada Lovelace", "interviewee") in hosted
    assert not strengthens_expertise("interviewee")


def test_led_is_technical_attribution() -> None:
    found = attributions_in("Ada Lovelace led the Northwind serving path.", "https://northwind.example/blog/a")
    assert ("Ada Lovelace", "author") in found
    assert strengthens_expertise("author")


def test_contradiction_and_syndication() -> None:
    html = """
    <html><head>
      <meta name="author" content="Ada Lovelace">
      <meta name="author" content="Grace Hopper">
    </head></html>
    """
    facts = extract_structured(html, "https://northwind.example/blog/a")
    authors = [fact for fact in facts if fact.field == "author"]
    assert len(authors) == 2
    assert all(fact.confidence < 0.75 for fact in authors)
    copied = mark_contradictions(dedupe_facts(facts + facts))
    assert len([fact for fact in copied if fact.field == "author"]) == 2


def test_book_title_metadata_is_not_a_person() -> None:
    html = '<html><head><meta name="author" content="An Elegant Puzzle"></head></html>'
    facts = extract_structured(html, "https://press.stripe.com/an-elegant-puzzle")
    assert all(fact.value != "An Elegant Puzzle" for fact in facts)


def test_role_artifact_and_function_still_converge() -> None:
    evidence = [
        Evidence(
            id="role",
            observation_id="o",
            excerpt="Ada Lovelace, Director of Platform Engineering at Northwind.",
            source_url="https://northwind.example/news/ada",
            source_title="news",
            source_type="company_news",
            published_at=date(2026, 4, 1),
            observed_at=OBSERVED,
            confidence=0.8,
            lineage=["field:author"],
            topics=[],
            supports_problem=False,
            contradicts_redis=False,
            is_explicit_gap=False,
            evidence_type="json_ld",
            field="author",
            value="Ada Lovelace",
        ),
        Evidence(
            id="art",
            observation_id="o",
            excerpt="Ada Lovelace led the Northwind serving infrastructure.",
            source_url="https://northwind.example/blog/serving",
            source_title="blog",
            source_type="engineering_blog",
            published_at=date(2026, 5, 1),
            observed_at=OBSERVED,
            confidence=0.7,
            lineage=[],
            topics=["low_latency"],
            supports_problem=True,
            contradicts_redis=False,
            is_explicit_gap=False,
        ),
        Evidence(
            id="job",
            observation_id="o",
            excerpt="Platform Engineering owns serving infrastructure. The team is hiring.",
            source_url="https://jobs.example/northwind",
            source_title="job",
            source_type="job_posting",
            published_at=date(2026, 8, 1),
            observed_at=OBSERVED,
            confidence=0.7,
            lineage=[],
            topics=[],
            supports_problem=False,
            contradicts_redis=False,
            is_explicit_gap=False,
        ),
    ]
    result = resolve_affiliation(
        "Ada Lovelace",
        "Director of Platform Engineering",
        evidence,
        account_name="Northwind",
        domain="northwind.example",
        functions=["platform"],
        observed_on=date(2026, 9, 24),
    )
    assert result.ownership_level == "strong"
    assert result.function_level == "strong"
