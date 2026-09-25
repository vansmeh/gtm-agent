"""Outreach eligibility is separate from ownership confidence."""

from app.domain.models import PersonOpportunity, PersonRecord
from app.opportunity.person_opportunity import (
    decide_contact,
    exploratory_message,
    opportunity_tier,
    ownership_claim,
)
from app.person.candidate_generation import extract_names
from app.person.entity import classify_entity
from app.research.search import SearchHit


def _person(**kwargs: object) -> PersonRecord:
    payload: dict[str, object] = {
        "id": "p",
        "name": "Ada Lovelace",
        "title": "Director, Platform Engineering",
        "identity_confidence": 0.8,
        "source_urls": ["https://northwind.example/news/ada"],
        "seniority": 0.6,
        "function_guess": "platform",
        "responsibilities": [],
        "activity": [],
        "footprint_topics": ["low_latency"],
        "authored_urls": [],
        "persona_id": None,
        "validity": "current",
        "role_state": "current",
        "function_level": "strong",
        "ownership_level": "probable",
        "selection_status": "verified_person",
        "responsibility_status": "confirmed",
    }
    payload.update(kwargs)
    return PersonRecord(**payload)  # type: ignore[arg-type]


def _row(**kwargs: object) -> PersonOpportunity:
    payload: dict[str, object] = {
        "id": "po",
        "account_id": "a",
        "person_id": "p",
        "technical_problem": "low-latency serving",
        "person_kind": "problem_owner",
        "why_now_credible": True,
        "redis_credible": True,
    }
    payload.update(kwargs)
    return PersonOpportunity(**payload)  # type: ignore[arg-type]


def test_tier_a_verified_owner_is_contact_now() -> None:
    person = _person(ownership_level="strong")
    row = _row()
    assert opportunity_tier(row, person) == "TIER_A_VERIFIED_OWNER"
    assert decide_contact(row, person) == "contact_now"
    assert row.tier_evidence


def test_tier_b_probable_owner_is_human_review() -> None:
    person = _person(ownership_level="probable")
    row = _row(person_kind="access_path")
    assert opportunity_tier(row, person) == "TIER_B_PROBABLE_OWNER"
    assert decide_contact(row, person) == "human_review"
    message = exploratory_message(
        name=person.name,
        role=person.title,
        account="Northwind",
        problem=row.technical_problem,
    )
    assert "OWNERSHIP = PROBABLE, NOT VERIFIED" in message
    assert not ownership_claim(message)


def test_tier_c_relevant_person_is_research_more() -> None:
    person = _person(function_level="unknown", footprint_topics=[], ownership_level="unknown", role_state="current")
    row = _row(why_now_credible=False, redis_credible=False, person_kind="access_path")
    assert opportunity_tier(row, person) == "TIER_C_RELEVANT_PERSON"
    assert decide_contact(row, person) == "research_more"


def test_tier_d_insufficient() -> None:
    row = _row(technical_problem="", person_kind="access_path")
    assert opportunity_tier(row, None) == "TIER_D_INSUFFICIENT"
    assert decide_contact(row, None) == "ignore"


def test_unsupported_ownership_claim_is_rejected() -> None:
    assert ownership_claim("you own the serving path")
    assert ownership_claim("your team owns latency")
    assert ownership_claim("you are responsible for the cache")
    assert not ownership_claim("Curious whether this is something your platform team is evaluating.")


def _hit(title: str, snippet: str) -> SearchHit:
    return SearchHit(url="https://news.example/post", title=title, snippet=snippet, engine="test")


def test_book_title_is_not_a_person() -> None:
    assert classify_entity("An Elegant Puzzle", "Will Larson wrote An Elegant Puzzle.") == "DOCUMENT"
    kept, _raw, rejected, _dupes = extract_names(
        [_hit("An Elegant Puzzle", "An Elegant Puzzle, Staff Engineer at Stripe.")],
        "Stripe",
        "stripe.com",
    )
    assert rejected >= 1
    assert all(item.name != "An Elegant Puzzle" for item in kept)


def test_company_product_and_team_are_not_people() -> None:
    assert classify_entity("Northwind Labs", "Northwind Labs announced a product.") == "ORG"
    assert classify_entity("Magic Transit", "Magic Transit is the product.") == "PRODUCT"
    assert classify_entity("Platform Team", "The Platform Team is hiring.") == "ORG"


def test_ambiguous_name_without_a_person_marker_is_rejected() -> None:
    assert classify_entity("Blue Harbor", "Blue Harbor appears in the headline.") == "UNKNOWN"
    kept, _raw, rejected, _dupes = extract_names(
        [_hit("Blue Harbor", "Blue Harbor appears in the Stripe headline.")],
        "Stripe",
        "stripe.com",
    )
    assert rejected >= 1 or not kept
    assert all(item.name != "Blue Harbor" for item in kept)
