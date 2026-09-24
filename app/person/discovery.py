"""Find candidate people named in fetched pages. Search snippets are not identity."""

import re
from dataclasses import dataclass
from datetime import date

from app.domain.models import Evidence, Observation
from app.person.entity import classify_entity

_TITLE = (
    r"(?:Head of|VP|Vice President(?: of)?|Director of|Chief|CEO|CTO|CIO|CPO|"
    r"Co-Founder|Founder|SVP|EVP|President|Principal|Staff|Distinguished|"
    r"Engineering Manager|Engineering Lead|Tech Lead|Lead Engineer|"
    r"Software Engineer|Architect|Evangelist|Advocate|Engineering VPs?)"
)
_PREFIX = r"(?:senior |staff |principal |lead |distinguished |software ){0,3}"
_NAME = r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})"
_TITLE_TAIL = rf"({_PREFIX}{_TITLE}(?: [^,.\n]{{0,50}})?)"
_PATTERNS = (
    re.compile(rf"\b{_NAME},?\s+{_TITLE_TAIL}"),
    re.compile(rf"\bBy {_NAME},?\s+{_TITLE_TAIL}"),
    re.compile(rf"\b{_NAME} is (?:the |a |an )?{_TITLE_TAIL}", re.I),
    re.compile(rf"\b{_NAME}, [^.\n]{{0,50}}?\b{_TITLE_TAIL}"),
)
_BLOCK = frozenset(
    {
        "acme",
        "search",
        "platform",
        "engineering",
        "infrastructure",
        "machine",
        "learning",
        "redis",
        "vector",
        "northwind",
        "team",
        "blog",
        "github",
        "conference",
        "speaker",
        "by",
        "the",
        "and",
        "head",
        "director",
        "vice",
        "president",
        "data",
        "systems",
        "distributed",
        "solutions",
        "protection",
        "partner",
        "source",
        "our",
        "this",
        "their",
        "performance",
        "reference",
        "magic",
        "transit",
        "connectivity",
        "cloud",
        "full",
        "stack",
        "leadership",
        "software",
        "senior",
        "interviews",
        "interview",
    }
)
_AT = re.compile(r"\bat ([A-Z][^,.]{2,80})")


@dataclass(frozen=True)
class Mention:
    name: str
    title: str
    url: str
    excerpt: str
    published_at: date | None


def clean_title(title: str) -> str:
    first = title.split("\n", 1)[0]
    head = re.split(r"\s+at\s+|\s+is\s+", first, maxsplit=1, flags=re.I)[0]
    return " ".join(head.split())[:80].strip(" ,.-")


def discover_people(evidence: list[Evidence]) -> list[tuple[str, str, str]]:
    """Return (name, title, source_url) from excerpts. Kept for callers that only have evidence."""
    found: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        for name, title in _names_in(item.excerpt):
            key = (name, title)
            if key in seen:
                continue
            seen.add(key)
            found.append((name, title, item.source_url))
    return found


def discover_mentions(observations: list[Observation], account_name: str) -> list[Mention]:
    """Identity mentions from fetched page text. The account name must be in that page."""
    account = account_name.strip().lower()
    found: list[Mention] = []
    seen: set[tuple[str, str, str]] = set()
    for obs in observations:
        if obs.poisoned or not obs.sanitized_text:
            continue
        if account not in obs.sanitized_text.lower():
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", obs.sanitized_text):
            if _anchored_elsewhere(sentence, account):
                continue
            for name, title in _names_in(sentence):
                if any(part.lower() == account or account in part.lower() for part in name.split()):
                    continue
                key = (name, title, obs.url)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    Mention(
                        name=name,
                        title=title,
                        url=obs.url,
                        excerpt=" ".join(sentence.split())[:500],
                        published_at=obs.published_at,
                    )
                )
    return found


def _names_in(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            name = " ".join(part.capitalize() if part.islower() else part for part in match.group(1).split())
            parts = name.split()
            if any(part.lower() in _BLOCK for part in parts):
                continue
            if classify_entity(name, text) != "PERSON":
                continue
            if len(parts) < 2:
                continue
            title = clean_title(match.group(2))
            if len(title) < 4:
                continue
            found.append((name, title))
    return found


def _anchored_elsewhere(sentence: str, account: str) -> bool:
    match = _AT.search(sentence)
    if match is None:
        return False
    org = match.group(1).lower()
    return account not in org and account not in sentence.lower()
