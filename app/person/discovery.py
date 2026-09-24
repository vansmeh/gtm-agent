"""Find candidate people named in sourced evidence. Does not invent names."""

import re

from app.domain.models import Evidence

_PERSON = re.compile(
    r"\b([A-Z][a-z]+ [A-Z][a-z]+),?\s+"
    r"((?:Head of|VP|Vice President of|Director of) [A-Z][^,.]{2,80})"
)
_BLOCK = frozenset(
    {"acme", "search", "platform", "engineering", "infrastructure", "machine", "learning", "redis"}
)


def clean_title(title: str) -> str:
    head = re.split(r"\s+at\s+", title, maxsplit=1)[0]
    return head.strip(" ,.")


def discover_people(evidence: list[Evidence]) -> list[tuple[str, str, str]]:
    """Return (name, title, source_url) tuples that appear in excerpts."""
    found: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        for match in _PERSON.finditer(item.excerpt):
            name = match.group(1).strip()
            parts = name.split()
            if any(part.lower() in _BLOCK for part in parts):
                continue
            title = clean_title(match.group(2))
            key = (name, title)
            if key in seen:
                continue
            seen.add(key)
            found.append((name, title, item.source_url))
    return found
