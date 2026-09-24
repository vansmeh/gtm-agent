"""Ownership language tied to a person or to a function. Absence stays absence."""

import re

from app.domain.models import Evidence

_VERB = re.compile(r"\b(owns|owned|leads|lead|responsible|heads|runs)\b", re.I)


def extract_responsibilities(name: str, evidence: list[Evidence]) -> list[str]:
    found: list[str] = []
    for item in evidence:
        if name in item.excerpt and _VERB.search(item.excerpt):
            found.append(item.excerpt)
    return found


def function_ownership_excerpts(evidence: list[Evidence]) -> list[Evidence]:
    return [
        item
        for item in evidence
        if "ownership_platform" in item.topics or "reports_platform" in item.topics
    ]
