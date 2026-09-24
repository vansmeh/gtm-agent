"""Separate current role from historical expertise. Old evidence is classified, not deleted."""

from datetime import date

from app.domain.models import Evidence
from app.person.discovery import Mention

CURRENT_ROLE_DAYS = 365
CURRENT_ACTIVITY_DAYS = 365
ACCOUNT_TRIGGER_DAYS = 180

_CURRENT_PATHS = ("/team", "/leadership", "/people", "/about", "/bio", "/author")
_TECH = (
    "platform",
    "infrastructure",
    "search",
    "architecture",
    "backend",
    "distributed",
    "vector",
    "retrieval",
    "caching",
    "latency",
    "rag",
)
_OWN = ("owns", "leads", "responsible", "heads", "runs", "directs", "oversees", "teams are building")


class RoleFreshness:
    def __init__(
        self,
        *,
        validity: str,
        role_freshness: str,
        evidence_classes: list[str],
        current_ownership: str,
        historical_expertise: list[str],
        current_activity: list[str],
    ) -> None:
        self.validity = validity
        self.role_freshness = role_freshness
        self.evidence_classes = evidence_classes
        self.current_ownership = current_ownership
        self.historical_expertise = historical_expertise
        self.current_activity = current_activity


def resolve_freshness(
    name: str,
    mentions: list[Mention],
    evidence: list[Evidence],
    *,
    observed_on: date,
    role_days: int = CURRENT_ROLE_DAYS,
    activity_days: int = CURRENT_ACTIVITY_DAYS,
) -> RoleFreshness:
    own = [item for item in mentions if item.name == name]
    classes: list[str] = []
    current_role = False
    historical_role = False
    for mention in own:
        kind = role_class(mention.published_at, mention.url, observed_on=observed_on, role_days=role_days)
        classes.append(kind)
        current_role = current_role or kind == "CURRENT_ROLE"
        historical_role = historical_role or kind == "HISTORICAL_ROLE"
    ownership = ""
    historical: list[str] = []
    activity: list[str] = []
    for item in evidence:
        if name not in item.excerpt:
            continue
        age = _age(item.published_at, observed_on)
        technical = _technical(item.excerpt, item.topics)
        owns = _owns(item.excerpt)
        fresh_role = age is not None and age <= role_days
        fresh_activity = age is not None and age <= activity_days
        undated_current = age is None and _current_page(item.source_url)
        if owns and (fresh_role or undated_current):
            classes.append("CURRENT_RESPONSIBILITY")
            ownership = ownership or item.excerpt
        elif technical and fresh_activity:
            classes.append("CURRENT_TECHNICAL_ACTIVITY")
            activity.append(item.excerpt)
        elif technical:
            classes.append("HISTORICAL_EXPERTISE")
            historical.append(item.excerpt)
    if current_role or "CURRENT_RESPONSIBILITY" in classes:
        validity = "current"
        freshness = "current"
    elif historical_role or historical:
        validity = "stale"
        freshness = "historical"
    else:
        validity = "unknown"
        freshness = "unknown"
    return RoleFreshness(
        validity=validity,
        role_freshness=freshness,
        evidence_classes=list(dict.fromkeys(classes)),
        current_ownership=ownership,
        historical_expertise=historical[:4],
        current_activity=activity[:4],
    )


def role_class(
    published_at: date | None,
    url: str,
    *,
    observed_on: date,
    role_days: int = CURRENT_ROLE_DAYS,
) -> str:
    age = _age(published_at, observed_on)
    if age is not None and age <= role_days:
        return "CURRENT_ROLE"
    if age is None and _current_page(url):
        return "CURRENT_ROLE"
    if age is not None:
        return "HISTORICAL_ROLE"
    return "HISTORICAL_ROLE"


def _current_page(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in _CURRENT_PATHS)


def _age(published_at: date | None, observed_on: date) -> int | None:
    if published_at is None:
        return None
    return (observed_on - published_at).days


def _technical(excerpt: str, topics: list[str]) -> bool:
    problem = {"low_latency", "distributed_systems", "rag", "caching", "ai_search", "retrieval"}
    if any(topic in problem for topic in topics):
        return True
    lowered = excerpt.lower()
    return any(token in lowered for token in _TECH)


def _owns(excerpt: str) -> bool:
    lowered = excerpt.lower()
    return any(token in lowered for token in _OWN)
