"""Qualify a name with GLiNER, then a small spaCy EntityRuler.

A PERSON candidate needs a person label and company context.
A relation is a candidate claim. It is not ownership.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_LABELS = ["person", "organization", "company", "product", "team", "job title", "document"]
_CANON = {
    "person": "PERSON",
    "organization": "ORG",
    "company": "COMPANY",
    "product": "PRODUCT",
    "team": "TEAM",
    "job title": "JOB_TITLE",
    "document": "DOCUMENT",
}
_RULES: dict[str, tuple[str, ...]] = {
    "DOCUMENT": ("An Elegant Puzzle", "Magic Quadrant"),
    "JOB_TITLE": ("Full Stack", "Engineering"),
    "TEAM": ("Platform Engineering", "Search Team"),
    "COMPANY": ("Datadog", "Shopify", "Stripe", "Acme AI", "Northwind"),
    "PRODUCT": ("Bits AI", "Magic Transit", "Application Monitoring", "Prioritization Engine"),
}
_AT = re.compile(r"\bat ([A-Z][A-Za-z0-9]+(?: [A-Z][A-Za-z0-9]+)?)")


@dataclass(frozen=True)
class EntityRelation:
    subject: str
    relation: str
    object: str
    confidence: float


@dataclass(frozen=True)
class QualifiedPerson:
    name: str
    context: str
    source_url: str
    source_type: str
    entity_type: str
    entity_confidence: float
    relations: tuple[EntityRelation, ...]


def qualify_person(
    name: str,
    context: str,
    company: str,
    *,
    source_url: str = "",
    source_type: str = "untrusted_web",
) -> QualifiedPerson | None:
    """Return a person only when the entity is a person in this company's context."""
    if not name or not context:
        return None
    ruled = _ruler_label(name)
    if ruled is not None and ruled != "PERSON":
        return None
    label, score = _gliner_label(name, context)
    if label != "PERSON":
        return None
    if not _company_context(context, company):
        return None
    window = _window(context, name)
    return QualifiedPerson(
        name=name,
        context=window,
        source_url=source_url,
        source_type=source_type,
        entity_type="PERSON",
        entity_confidence=score,
        relations=tuple(_relations(name, window, company, score)),
    )


def company_in_text(text: str) -> str:
    match = _AT.search(text)
    return match.group(1).strip() if match else ""


def same_identity(left_name: str, left_text: str, right_name: str, right_text: str) -> bool:
    """Same spelling is not enough. Company and role context have to agree."""
    if left_name.strip().lower() != right_name.strip().lower():
        return False
    left_co = company_in_text(left_text).lower()
    right_co = company_in_text(right_text).lower()
    if left_co and right_co and left_co != right_co:
        return False
    left_role = _role_hint(left_text)
    right_role = _role_hint(right_text)
    if left_role and right_role and left_role != right_role and left_co != right_co:
        return False
    return True


def _company_context(context: str, company: str) -> bool:
    account = company.strip().lower()
    if not account:
        return False
    if account in context.lower():
        return True
    stated = company_in_text(context).lower()
    return bool(stated) and (account in stated or stated in account)


def _window(context: str, name: str) -> str:
    idx = context.find(name)
    if idx < 0:
        return " ".join(context.split())[:400]
    start = max(0, idx - 80)
    return " ".join(context[start : idx + len(name) + 220].split())[:400]


def _role_hint(text: str) -> str:
    match = re.search(
        r"\b((?:Head|Director|VP|Staff|Principal|Senior)(?: of)? [^,.]{0,48})",
        text,
        re.I,
    )
    return " ".join(match.group(1).lower().split()) if match else ""


def _relations(name: str, context: str, company: str, score: float) -> list[EntityRelation]:
    found: list[EntityRelation] = []
    stated = company_in_text(context) or company
    if stated and stated.lower() in context.lower():
        found.append(EntityRelation(name, "works_at", stated, score))
    role = _role_hint(context)
    if role:
        found.append(EntityRelation(name, "has_role", role, score))
    for label, text, confidence in _spans(context):
        if label == "DOCUMENT" and text.lower() != name.lower():
            found.append(EntityRelation(name, "authored", text, confidence))
        elif label == "TEAM":
            found.append(EntityRelation(name, "works_on", text, confidence))
    return found


def _ruler_label(name: str) -> str | None:
    doc = _ruler()(name)
    if not doc.ents:
        return None
    return str(doc.ents[0].label_)


def _gliner_label(name: str, context: str) -> tuple[str, float]:
    spans = _spans(context)
    covering = [item for item in spans if name.lower() in item[1].lower() or item[1].lower() in name.lower()]
    if not covering:
        return "UNKNOWN", 0.0
    label, _text, score = max(covering, key=lambda item: item[2])
    return label, score


def _spans(context: str) -> list[tuple[str, str, float]]:
    raw = _gliner().predict_entities(context, _LABELS, threshold=0.45)
    found: list[tuple[str, str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = _CANON.get(str(item.get("label", "")).lower(), "UNKNOWN")
        text = str(item.get("text", ""))
        score = float(item.get("score", 0.0))
        if text:
            found.append((label, text, score))
    return found


@lru_cache(maxsize=1)
def _gliner() -> Any:
    from gliner import GLiNER

    return GLiNER.from_pretrained("urchade/gliner_small-v2.1")


@lru_cache(maxsize=1)
def _ruler() -> Any:
    import spacy
    from spacy.pipeline import EntityRuler

    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    if not isinstance(ruler, EntityRuler):
        raise TypeError("spaCy entity ruler was not created")
    ruler.add_patterns(
        [{"label": label, "pattern": phrase} for label, phrases in _RULES.items() for phrase in phrases]
    )
    return nlp
