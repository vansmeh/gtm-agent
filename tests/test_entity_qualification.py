"""GLiNER plus a small EntityRuler qualifies people and drops phrases."""

from datetime import date

from app.person.discovery import Mention
from app.person.identity import identities_from_mentions
from app.person.qualify import qualify_person, same_identity

OBSERVED = date(2026, 9, 24)


def test_document_team_title_company_and_product_are_rejected() -> None:
    rejected = [
        ("An Elegant Puzzle", "An Elegant Puzzle is a book about engineering management.", "Northwind"),
        ("Full Stack", "Full Stack engineering at Northwind.", "Northwind"),
        ("Platform Engineering", "Platform Engineering owns the developer platform at Northwind.", "Northwind"),
        ("Magic Quadrant", "Magic Quadrant for Observability Platforms at Datadog.", "Datadog"),
        ("Datadog", "Datadog announced a new product.", "Datadog"),
        ("Bits AI", "Bits AI is a Datadog product for incident response.", "Datadog"),
        ("Search Team", "The Search Team at Shopify owns discovery.", "Shopify"),
        (
            "Flow Autotagging Based",
            "Flow Autotagging Based on product description in the Shopify community.",
            "Shopify",
        ),
        ("Accelerate Its Investment", "Datadog acquires Adaptive ML to Accelerate Its Investment in AI.", "Datadog"),
    ]
    for name, context, company in rejected:
        assert qualify_person(name, context, company) is None, name


def test_actual_person_is_kept_with_context() -> None:
    found = qualify_person(
        "Jane Smith",
        "Jane Smith, Director of Platform Engineering at Shopify, leads the serving platform.",
        "Shopify",
        source_url="https://shopify.example/jane",
        source_type="blog",
    )
    assert found is not None
    assert found.entity_type == "PERSON"
    assert found.entity_confidence > 0.5
    assert "Jane Smith" in found.context
    assert found.source_url == "https://shopify.example/jane"
    assert any(item.relation == "works_at" for item in found.relations)
    assert any(item.relation == "has_role" for item in found.relations)


def test_person_without_company_context_is_rejected() -> None:
    assert qualify_person("Jane Smith", "Jane Smith spoke at the conference.", "Shopify") is None


def test_common_name_stays_a_person_inside_company_context() -> None:
    found = qualify_person(
        "John Smith",
        "John Smith, Staff Engineer at Shopify, works on search.",
        "Shopify",
    )
    assert found is not None
    assert found.entity_type == "PERSON"


def test_same_name_at_two_companies_stays_separate() -> None:
    assert not same_identity(
        "John Smith",
        "John Smith, Staff Engineer at Shopify, works on search.",
        "John Smith",
        "John Smith, Engineering Manager at Stripe, works on billing.",
    )
    mentions = [
        Mention(
            name="John Smith",
            title="Staff Engineer",
            url="https://shopify.example/john",
            excerpt="John Smith, Staff Engineer at Shopify, works on search.",
            published_at=OBSERVED,
        ),
        Mention(
            name="John Smith",
            title="Engineering Manager",
            url="https://stripe.example/john",
            excerpt="John Smith, Engineering Manager at Stripe, works on billing.",
            published_at=OBSERVED,
        ),
    ]
    identities = identities_from_mentions(mentions, "Shopify", observed_on=OBSERVED)
    companies = {item.company for item in identities}
    assert len(identities) == 2
    assert "Shopify" in companies
    assert "Stripe" in companies
