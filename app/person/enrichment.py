"""Cheap candidate filter, then deep research only for the strongest few."""

from dataclasses import dataclass
from datetime import date

_OWN = ("owns", "leads", "leading", "responsible", "heads", "runs", "directs")
_STALE = ("formerly", "previously", "left ", "no longer")
_IRRELEVANT = ("chief financial", "cfo", "chief executive", "ceo", "chief operating", "coo")
_TECH = ("principal", "staff", "architect", "lead", "director", "head of", "engineer")


@dataclass
class CandidateView:
    name: str
    title: str
    company: str
    url: str
    excerpt: str
    published_at: date | None
    priority_reason: str = ""
    reject_reason: str = ""
    entity_type: str = ""
    entity_confidence: float = 0.0


def profile_queries(name: str, account_name: str, functions: list[str]) -> list[str]:
    """Public indexed profile queries. LinkedIn hits are discovery only and are not fetched."""
    function = functions[0] if functions else "engineering"
    return [
        f'"{name}" "{account_name}" 2026',
        f'"{name}" "{account_name}" current role',
        f'site:linkedin.com/in "{name}" "{account_name}"',
        f'site:linkedin.com/in "{account_name}" "{function}"',
    ]


def deep_research_queries(name: str, account_name: str, topic: str) -> list[str]:
    focus = topic or "architecture"
    return [
        f'"{name}" "{account_name}" current role',
        f'"{name}" "{account_name}" {focus}',
        f'"{name}" "{account_name}" architecture',
        f'"{name}" "{account_name}" hiring',
    ]


def next_owner_query(account_name: str, function: str, name: str, problem: str) -> str:
    focus = problem or "that function"
    team = function or "platform"
    return (
        f'Find current {account_name} {team} team ownership and verify whether {name} leads {focus}.'
    )


def cheap_reject(
    candidate: CandidateView,
    *,
    account_name: str,
    functions: list[str],
    observed_on: date,
    role_days: int = 365,
) -> str:
    """Return a rejection reason, or an empty string when the candidate can be enriched."""
    account = account_name.lower()
    text = f"{candidate.excerpt} {candidate.company}".lower()
    title = candidate.title.lower()
    if account and account not in text and candidate.company and account not in candidate.company.lower():
        return "wrong company"
    if any(token in text for token in _STALE) and "joined" in text and account not in text.split("joined", 1)[-1]:
        return "stale employment"
    if candidate.published_at is not None and (observed_on - candidate.published_at).days > role_days:
        return "stale employment"
    if not candidate.name or len(candidate.name.split()) < 2:
        return "ambiguous identity"
    if functions and any(token in title for token in _IRRELEVANT):
        if not any(function in title or function in candidate.excerpt.lower() for function in functions):
            return "irrelevant function"
    return ""


def prioritize(
    candidates: list[CandidateView],
    *,
    functions: list[str],
    observed_on: date,
    role_days: int = 365,
) -> list[CandidateView]:
    """Order by evidence. Seniority is not part of the key."""
    ranked = sorted(
        candidates,
        key=lambda item: _dimensions(item, functions, observed_on, role_days),
        reverse=True,
    )
    for item in ranked:
        item.priority_reason = _reason(item, functions, observed_on, role_days)
    return ranked


def _dimensions(
    candidate: CandidateView,
    functions: list[str],
    observed_on: date,
    role_days: int,
) -> tuple[int, int, int, int, int, int]:
    text = f"{candidate.title} {candidate.excerpt}".lower()
    function_match = int(any(function in text for function in functions)) if functions else 0
    role = int(any(token in candidate.title.lower() for token in _TECH) and function_match)
    ownership = int(any(verb in text for verb in _OWN) and function_match)
    technical = int(any(token in text for token in ("latency", "serving", "search", "architecture", "infrastructure")))
    current = 0
    if candidate.published_at is None or (observed_on - candidate.published_at).days <= role_days:
        current = 1
    public = int("by " in candidate.excerpt.lower() or "blog" in candidate.url or "conference" in candidate.url)
    return (ownership, role, function_match, technical, current, public)


def _reason(
    candidate: CandidateView,
    functions: list[str],
    observed_on: date,
    role_days: int,
) -> str:
    ownership, role, function_match, technical, current, public = _dimensions(
        candidate, functions, observed_on, role_days
    )
    parts: list[str] = []
    if role:
        parts.append("current role matches the affected function")
    elif function_match:
        parts.append("excerpt names the affected function")
    if ownership:
        parts.append("likely problem ownership is stated")
    if technical:
        parts.append("technical signal terms appear in the source")
    parts.append("currentness is recent" if current else "currentness is not established")
    if public:
        parts.append("a public technical page names the person")
    if not parts:
        parts.append("identity is present and no stronger evidence is public yet")
    return "; ".join(parts)
