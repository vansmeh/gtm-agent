"""Public search is live. Authorship comes from the document, not the URL."""

from datetime import UTC, datetime

from app.db.models import ResearchLogRow
from app.db.session import init_db, make_engine, make_session_factory, session_scope
from app.domain.models import Evidence, RunModel, SearchTrace
from app.persistence.store import Store
from app.person.attribution import (
    attributions_in,
    build_artifacts,
    resolve_identities,
    strengthens_expertise,
)
from app.research.search import (
    DirectWebSearchProvider,
    MockSearchProvider,
    SearXNGSearchProvider,
    parse_duckduckgo_html,
    provider_mode,
)


def test_real_provider_is_live_and_mock_is_not() -> None:
    assert provider_mode(DirectWebSearchProvider()) == "LIVE"
    assert DirectWebSearchProvider.endpoint.startswith("https://html.duckduckgo.com")
    assert provider_mode(MockSearchProvider([])) == "MOCK"
    assert provider_mode(MockSearchProvider([], mode="DEMO")) == "DEMO"
    local = SearXNGSearchProvider("http://127.0.0.1:8080")
    assert provider_mode(local) != "LIVE"


def test_article_author_speaker_and_github_contributor() -> None:
    author = attributions_in("By Ada Lovelace. Northwind serving notes.", "https://northwind.example/blog/a")
    speaker = attributions_in("Speaker: Ada Lovelace. Northwind conference.", "https://conf.example/ada")
    github = attributions_in(
        "Contributor: Ada Lovelace. Northwind latency tool.",
        "https://github.com/northwind/latency",
    )
    assert ("Ada Lovelace", "author") in author
    assert ("Ada Lovelace", "speaker") in speaker
    assert ("Ada Lovelace", "contributor") in github
    assert strengthens_expertise("author")
    assert strengthens_expertise("speaker")
    assert strengthens_expertise("contributor")


def test_slug_and_mention_do_not_count_as_authorship() -> None:
    slug = attributions_in("Northwind latency notes.", "https://github.com/northwind/ada-lovelace")
    assert slug == []
    mentioned = attributions_in("Northwind thanked Ada Lovelace in the post.", "https://northwind.example/blog/thanks")
    assert ("Ada Lovelace", "mentioned_person") in mentioned
    assert not strengthens_expertise("mentioned_person")


def test_same_person_merges_and_same_name_stays_split() -> None:
    merged = resolve_identities(
        [
            ("Ada Lovelace", "Northwind", "https://northwind.example/blog/a", "engineering_blog"),
            ("Ada Lovelace", "Northwind", "https://northwind.example/blog/b", "engineering_blog"),
        ]
    )
    split = resolve_identities(
        [
            ("Ada Lovelace", "Northwind", "https://northwind.example/blog/a", "engineering_blog"),
            ("Ada Lovelace", "Otherco", "https://other.example/blog/a", "blog"),
        ]
    )
    assert len(merged) == 1
    assert merged[0].identity_confidence > 0.45
    assert len(split) == 2


def test_artifact_links_the_author() -> None:
    evidence = [
        Evidence(
            id="e1",
            observation_id="o",
            excerpt="By Ada Lovelace. Northwind serving architecture.",
            source_url="https://northwind.example/blog/serving",
            source_title="Serving",
            source_type="engineering_blog",
            published_at=None,
            observed_at=datetime(2026, 9, 24, tzinfo=UTC),
            confidence=0.7,
            lineage=[],
            topics=["serving"],
            supports_problem=True,
            contradicts_redis=False,
            is_explicit_gap=False,
        )
    ]
    artifacts, links = build_artifacts(evidence, account_name="Northwind", domain="northwind.example")
    assert artifacts[0].author == "Ada Lovelace"
    assert artifacts[0].kind == "engineering_blog"
    assert links[0].relationship == "author"
    assert links[0].artifact_id == artifacts[0].id


def test_search_trace_is_persisted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = make_engine(f"sqlite:///{tmp_path / 'trace.db'}")
    init_db(engine)
    factory = make_session_factory(engine)
    moment = datetime(2026, 9, 24, tzinfo=UTC)
    run = RunModel(
        run_id="run-1",
        account_id="acct-1",
        account_name="Northwind",
        domain="northwind.example",
        observed_at=moment,
        search_mode="LIVE",
        search_traces=[
            SearchTrace(
                provider="direct-web",
                provider_mode="LIVE",
                query="Northwind serving",
                timestamp=moment,
                result_count=1,
                result_url="https://northwind.example/blog/serving",
                result_title="Serving",
                result_snippet="By Ada Lovelace",
                result_source="northwind.example",
                search_latency_ms=12,
            )
        ],
    )
    with session_scope(factory) as session:
        store = Store(session)
        store.create_account("acct-1", "Northwind", "northwind.example", moment)
        store.save_run(run, search_provider="direct", laya_mode="shadow", created_at=moment)
        rows = session.query(ResearchLogRow).filter(ResearchLogRow.node == "search").all()
    assert rows
    assert "https://northwind.example/blog/serving" in rows[0].message
    assert "LIVE" in rows[0].message


def test_live_provider_parses_a_public_result_page() -> None:
    html = """
    <div class="result">
      <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fnorthwind.example%2Fblog%2Fserving">
        Serving
      </a>
      <a class="result__snippet">By Ada Lovelace. Northwind serving.</a>
    </div>
    <div class="result">
      <a class="result__a" href="https://www.linkedin.com/in/ada">Skip</a>
    </div>
    """
    hits = parse_duckduckgo_html(html, limit=5)
    assert [hit.url for hit in hits] == ["https://northwind.example/blog/serving"]
    assert hits[0].provider == "direct-web"


def test_live_provider_smoke() -> None:
    hits = DirectWebSearchProvider(timeout=20, budget=2).search("Datadog engineering blog", limit=2)
    assert hits
    assert all(hit.provider == "direct-web" for hit in hits)
    assert all("linkedin.com" not in hit.url for hit in hits)
    assert hits[0].latency_ms > 0
