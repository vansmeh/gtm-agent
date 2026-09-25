"""Classify a candidate string before it can become a person.

PERSON is the only class that may enter the candidate list.
A book, company, product, team, title, or ambiguous phrase is not a person.
"""

import re

EntityClass = str

_DETERMINERS = frozenset({"a", "an", "the"})
_DOCUMENT = frozenset(
    {
        "puzzle",
        "elegant",
        "handbook",
        "guide",
        "manifesto",
        "memoir",
        "novel",
        "book",
        "paper",
        "report",
        "manual",
        "blueprint",
    }
)
_ORG_SUFFIX = frozenset({"inc", "corp", "corporation", "company", "labs", "llc", "ltd", "team", "group"})
_PRODUCT = frozenset(
    {
        "transit",
        "workers",
        "cloud",
        "gateway",
        "suite",
        "platform",
        "search",
        "redis",
        "postgres",
        "kubernetes",
    }
)
_TITLE = frozenset(
    {
        "engineer",
        "engineering",
        "manager",
        "director",
        "head",
        "architect",
        "lead",
        "principal",
        "staff",
        "vp",
        "president",
        "chief",
        "officer",
        "founder",
    }
)
_MARKER = re.compile(
    r"\b(by|author|speaker|said|wrote|joined|described|spoke|discussed|presented|leads|led|works)\b"
    r"|\bis (?:a|an|the)\b|,|\son\b",
    re.I,
)


def classify_entity(name: str, context: str = "") -> EntityClass:
    """Return PERSON, ORG, PRODUCT, TITLE, DOCUMENT, or UNKNOWN."""
    parts = [part.strip(".,:;\"'") for part in name.split() if part.strip(".,:;\"'")]
    lowered = [part.lower() for part in parts]
    if len(lowered) < 2:
        return "UNKNOWN"
    if lowered[0] in _DETERMINERS or any(part in _DOCUMENT for part in lowered):
        return "DOCUMENT"
    if lowered[-1] in _ORG_SUFFIX or "team" in lowered:
        return "ORG"
    if all(part in _TITLE for part in lowered):
        return "TITLE"
    if any(part in _PRODUCT for part in lowered):
        return "PRODUCT"
    if not _plausible_person(parts):
        return "UNKNOWN"
    if _person_marker(context, name):
        return "PERSON"
    return "UNKNOWN"


def _plausible_person(parts: list[str]) -> bool:
    if not 2 <= len(parts) <= 3:
        return False
    for part in parts:
        if len(part) < 2 or not part[:1].isupper():
            return False
        if part.lower() in _TITLE or part.lower() in _DETERMINERS:
            return False
    return True


def _person_marker(context: str, name: str) -> bool:
    if not context:
        return False
    if name in context and _MARKER.search(context):
        return True
    window = context.lower()
    return name.lower() in window and bool(_MARKER.search(window))
