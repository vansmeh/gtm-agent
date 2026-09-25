"""Discovery stays cheap. Deep research is reserved for the strongest candidates."""

from datetime import date

from app.person.enrichment import (
    CandidateView,
    cheap_reject,
    deep_research_queries,
    next_owner_query,
    prioritize,
    profile_queries,
)

OBSERVED = date(2026, 9, 24)


def _view(
    name: str,
    title: str,
    excerpt: str,
    published: date | None,
    url: str = "https://n.example/p",
) -> CandidateView:
    return CandidateView(name=name, title=title, company="Northwind", url=url, excerpt=excerpt, published_at=published)


def test_profile_queries_include_public_indexed_profiles() -> None:
    queries = profile_queries("Ada Lovelace", "Northwind", ["platform"])
    assert any("current role" in query for query in queries)
    assert any("site:linkedin.com/in" in query for query in queries)
    assert any("2026" in query for query in queries)


def test_stale_role_is_rejected_before_deep_research() -> None:
    reason = cheap_reject(
        _view("Ada Lovelace", "Staff Engineer", "Ada Lovelace, Staff Engineer at Northwind.", date(2020, 1, 1)),
        account_name="Northwind",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert reason == "stale employment"


def test_wrong_company_and_irrelevant_executive_are_rejected() -> None:
    wrong = cheap_reject(
        CandidateView(
            name="Ada Lovelace",
            title="Staff Engineer",
            company="Contoso",
            url="https://contoso.example/a",
            excerpt="Ada Lovelace, Staff Engineer at Contoso.",
            published_at=date(2026, 8, 1),
        ),
        account_name="Northwind",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    executive = cheap_reject(
        _view(
            "Olivier Example",
            "Chief Financial Officer",
            "Olivier Example, Chief Financial Officer, leads the company at Northwind.",
            date(2026, 8, 1),
        ),
        account_name="Northwind",
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert wrong == "wrong company"
    assert executive == "irrelevant function"


def test_prioritization_prefers_function_evidence_over_seniority() -> None:
    owner = _view(
        "Ada Lovelace",
        "Staff Engineer",
        "Ada Lovelace, Staff Engineer, owns the Northwind platform serving path.",
        date(2026, 8, 1),
        url="https://northwind.example/blog/ada",
    )
    executive = _view(
        "John Senior",
        "Chief Executive Officer",
        "John Senior, Chief Executive Officer, leads Northwind.",
        date(2026, 8, 1),
    )
    ranked = prioritize([executive, owner], functions=["platform"], observed_on=OBSERVED)
    assert ranked[0].name == "Ada Lovelace"
    assert "ownership" in ranked[0].priority_reason
    assert "seniority" not in ranked[0].priority_reason


def test_top_candidates_are_the_ones_deep_researched() -> None:
    people = [
        _view(
            f"Person {index}",
            "Engineer",
            f"Person {index} works at Northwind.",
            date(2026, 8, 1),
        )
        for index in range(8)
    ]
    owner = _view(
        "Ada Lovelace",
        "Head of Platform",
        "Ada Lovelace, Head of Platform, owns platform serving at Northwind.",
        date(2026, 8, 1),
        url="https://northwind.example/blog/ada",
    )
    ranked = prioritize([*people, owner], functions=["platform"], observed_on=OBSERVED)
    deep = ranked[:5]
    assert deep[0].name == "Ada Lovelace"
    assert len(deep) == 5
    queries = deep_research_queries("Ada Lovelace", "Northwind", "serving")
    assert any("current role" in query for query in queries)
    assert any("architecture" in query for query in queries)


def test_next_query_names_the_close_candidate() -> None:
    question = next_owner_query("Datadog", "platform", "Jane Smith", "low-latency serving")
    assert "Jane Smith" in question
    assert "platform" in question
    assert question.startswith("Find current Datadog")


def test_title_only_reason_does_not_claim_ownership() -> None:
    ranked = prioritize(
        [
            _view(
                "Ada Lovelace",
                "Staff Engineer",
                "Ada Lovelace, Staff Engineer, is listed at Northwind.",
                date(2026, 8, 1),
            )
        ],
        functions=["platform"],
        observed_on=OBSERVED,
    )
    assert "likely problem ownership" not in ranked[0].priority_reason
