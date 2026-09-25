"""Company association is not current employment and not ownership."""

from app.person.qualify import qualify_person

DOMAIN = "shopify.com"
URL = "https://shopify.com/blog/engineering/serving"


def test_company_domain_author_links_without_repeating_the_company() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith explains how the serving path stays fast.",
        "Shopify",
        source_url=URL,
        source_type="blog",
        domain=DOMAIN,
    )
    assert found is not None
    assert found.link_path == "page_context"
    assert found.relationship == "author"
    assert found.relationship != "current_employee"


def test_json_ld_works_for_is_evidence() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith worksFor Shopify.",
        "Shopify",
        source_url=URL,
        domain=DOMAIN,
        evidence_kind="json_ld",
    )
    assert found is not None
    assert found.link_path == "structured_metadata"
    assert any(item.relation == "works_at" for item in found.relations)


def test_speaker_card_and_separate_blocks_link() -> None:
    card = "Jane Smith\nDirector of Platform\nShopify"
    found = qualify_person(
        "Jane Smith",
        card,
        "Shopify",
        source_url="https://conf.example/speakers",
        source_type="conference",
        domain=DOMAIN,
    )
    assert found is not None
    assert found.link_path == "speaker_card"
    assert found.relationship == "speaker"


def test_explicit_works_at_and_same_sentence_role() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith, Director of Platform Engineering at Shopify, leads the serving platform.",
        "Shopify",
        source_url=URL,
        domain=DOMAIN,
    )
    assert found is not None
    assert found.link_path == "explicit_text"
    assert found.link_strength == "strong"
    assert found.relationship != "current_employee"


def test_search_snippet_is_probable() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith | Shopify",
        "Shopify",
        source_url="https://example.com/result",
        source_type="search_snippet",
        domain=DOMAIN,
    )
    assert found is not None
    assert found.link_path == "search_snippet"
    assert found.link_strength == "probable"


def test_github_org_contributor_is_probable_not_current() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith contributed the billing retry client.",
        "Stripe",
        source_url="https://github.com/stripe/ai",
        source_type="public_code",
        domain="stripe.com",
    )
    assert found is not None
    assert found.link_path == "github"
    assert found.link_strength == "probable"
    assert found.relationship != "current_employee"


def test_external_conference_speaker_is_not_an_employee() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith spoke about caching.",
        "Shopify",
        source_url="https://conf.example/speakers/jane",
        source_type="conference",
        domain=DOMAIN,
    )
    assert found is None


def test_historical_employee_stays_a_candidate() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith, formerly Director at Shopify, discussed the migration.",
        "Shopify",
        source_url="https://logz.io/blog/shopify-platform",
        domain=DOMAIN,
    )
    assert found is not None
    assert found.relationship == "historical_employee"


def test_mentioned_person_without_employment_is_rejected() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith said the industry is changing. Shopify launched a product.",
        "Shopify",
        source_url="https://news.example/story",
        domain=DOMAIN,
    )
    assert found is None


def test_document_title_is_not_a_person() -> None:
    found = qualify_person(
        "An Elegant Puzzle",
        "An Elegant Puzzle is a book about engineering at Shopify.",
        "Shopify",
        source_url=URL,
        domain=DOMAIN,
    )
    assert found is None
