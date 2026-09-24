"""Search results can name people. Generic headings and usernames cannot."""

from datetime import date

from app.person.candidate_generation import cluster_people, extract_names, recall_queries, source_tier
from app.research.search import SearchHit


def _hit(title: str, snippet: str, url: str) -> SearchHit:
    return SearchHit(url=url, title=title, snippet=snippet)


def test_name_from_title_and_snippet() -> None:
    title_hit = _hit("Ada Lovelace on Stripe latency", "A platform talk at Stripe.", "https://news.example/ada")
    snippet_hit = _hit("Engineering note", "Ada Lovelace described serving at Stripe.", "https://blog.example/note")
    from_title, _, _, _ = extract_names([title_hit], "Stripe", "stripe.com")
    from_snippet, _, _, _ = extract_names([snippet_hit], "Stripe", "stripe.com")
    assert from_title[0].name == "Ada Lovelace"
    assert from_snippet[0].name == "Ada Lovelace"


def test_byline_and_speaker() -> None:
    byline = _hit("Blog", "By Ada Lovelace. Stripe platform notes.", "https://stripe.com/blog/latency")
    speaker = _hit("Agenda", "Speaker: Grace Hopper. Stripe infrastructure.", "https://conf.example/speakers/grace")
    authors, _, _, _ = extract_names([byline], "Stripe", "stripe.com")
    speakers, _, _, _ = extract_names([speaker], "Stripe", "stripe.com")
    assert authors[0].name == "Ada Lovelace"
    assert authors[0].tier == "tier_2"
    assert speakers[0].name == "Grace Hopper"
    assert speakers[0].tier == "tier_3"


def test_generic_heading_title_and_github_username_are_rejected() -> None:
    heading = _hit("Full Stack", "Full Stack Software Engineer interviews at Stripe.", "https://github.com/x/stripe-interview")
    title_only = _hit("Platform Engineer", "Platform Engineer at Stripe.", "https://stripe.com/jobs/platform")
    username = _hit("Commit", "octocat discussed Stripe infrastructure.", "https://github.com/stripe/runtime")
    named = _hit("Commit", "By Grace Hopper. Stripe infrastructure.", "https://github.com/stripe/runtime/blob/readme")
    kept, raw, rejected, _duplicates = extract_names([heading, title_only, username, named], "Stripe", "stripe.com")
    assert [item.name for item in kept] == ["Grace Hopper"]
    assert raw >= 1
    assert rejected >= 1
    assert source_tier(title_only.url, "stripe.com") == "tier_1"


def test_duplicate_person_and_repost_cluster() -> None:
    from app.person.candidate_generation import ExtractedName

    one = ExtractedName("Ada Lovelace", "Staff Engineer", "https://news.example/posts/latency", "a", "tier_6")
    same = ExtractedName("Ada Lovelace", "Staff Engineer", "https://other.example/ada-2", "a", "tier_6")
    repost = ExtractedName("Grace Hopper", "", "https://mirror.example/posts/latency", "a", "tier_6")
    kept, duplicates = cluster_people([one, same, repost])
    assert [item.name for item in kept] == ["Ada Lovelace"]
    assert duplicates == 2


def test_recall_queries_cover_each_function_and_stop_without_one() -> None:
    queries = recall_queries("Stripe", "stripe.com", ["platform", "infrastructure"])
    assert len(queries) == 20
    assert any("platform engineer" in query for query in queries)
    assert any("site:stripe.com" in query for query in queries)
    assert recall_queries("Stripe", "stripe.com", []) == []


def test_discovery_budget_keeps_deep_research_capped() -> None:
    from app.person.enrichment import CandidateView, prioritize

    people = [
        CandidateView(
            name=f"Ada {index}",
            title="Staff Engineer",
            company="Stripe",
            url=f"https://stripe.com/blog/{index}",
            excerpt=f"Ada {index}, Staff Engineer, owns platform serving at Stripe.",
            published_at=date(2026, 8, 1),
        )
        for index in range(12)
    ]
    ranked = prioritize(people, functions=["platform"], observed_on=date(2026, 9, 24))
    assert len(ranked[:5]) == 5
    assert len(ranked) == 12
