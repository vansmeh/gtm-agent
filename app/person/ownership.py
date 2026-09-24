"""Resolve which current person owns the function behind a technical signal."""

from datetime import date
from urllib.parse import urlparse

from app.domain.models import Evidence

_FUNCTION_MAP: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("low-latency", "low_latency", "latency", "serving"),
        ("platform", "infrastructure", "distributed systems", "backend", "runtime"),
    ),
    (
        ("vector", "rag", "retrieval", "search"),
        ("search", "platform", "ml platform", "infrastructure"),
    ),
    (("hiring", "platform"), ("platform", "infrastructure")),
)

_OWN = ("owns", "leads", "responsible", "heads", "runs", "directs", "oversees", "teams are building")
_ROLE = ("head of", "director", "vp", "vice president", "principal", "staff", "architect")
_CURRENT_DAYS = 365
_STRONG_DAYS = 180


def affected_functions(signal_label: str) -> list[str]:
    lowered = signal_label.lower()
    found: list[str] = []
    for keys, functions in _FUNCTION_MAP:
        if any(key in lowered for key in keys):
            for name in functions:
                if name not in found:
                    found.append(name)
    if not found and lowered.strip() and lowered.strip() != "technical":
        found.append("platform")
    return found


def function_owner_queries(account_name: str, domain: str, functions: list[str]) -> list[str]:
    """Search the current function before any executive bio."""
    host = domain or account_name
    queries = [
        f"{account_name} platform leadership",
        f"{account_name} infrastructure leadership",
        f"{account_name} distributed systems",
        f"{account_name} runtime engineering",
        f"{account_name} backend platform",
        f"{account_name} site:{host}",
        f'{account_name} "Head of Platform"',
        f'{account_name} "Director Platform"',
        f'{account_name} "VP Infrastructure"',
        f'{account_name} "Principal Engineer"',
        f'{account_name} "Head of Platform" 2026',
        f'{account_name} "Director Infrastructure" 2026',
        f'{account_name} "VP Engineering" platform 2026',
        f'site:linkedin.com/in "{account_name}" platform engineer',
        f'site:linkedin.com/in "{account_name}" infrastructure',
        f'site:linkedin.com/in "{account_name}" search engineering',
    ]
    for function in functions:
        specific = f'{account_name} "{function}" leadership'
        if specific not in queries:
            queries.append(specific)
    return queries


def job_function_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """A posting can show the current function. It does not name a leader by itself."""
    found: list[Evidence] = []
    for item in evidence:
        text = item.excerpt.lower()
        posting = item.source_type == "job_posting" or "hiring" in text or "reports to" in text
        structure = any(token in text for token in ("team", "reports to", "responsible", "owns"))
        if posting and structure:
            found.append(item)
    return found


def classify_ownership(
    name: str,
    title: str,
    evidence: list[Evidence],
    *,
    observed_on: date,
    functions: list[str],
) -> tuple[str, list[str]]:
    named = [item for item in evidence if name in item.excerpt]
    current = [item for item in named if _is_current(item, observed_on)]
    if not current:
        return "unknown", []
    explicit = [item for item in current if _states_responsibility(item.excerpt) and _on_org_page(item)]
    if explicit:
        return "explicit", [item.id for item in explicit]
    role_pages = [item for item in current if _states_role(item.excerpt, title)]
    function_pages = [item for item in current if _connects_function(item, functions)]
    if role_pages and function_pages and _independent(role_pages, function_pages):
        role = role_pages[0]
        other = next(
            item
            for item in function_pages
            if item.id != role.id and _host(item.source_url) != _host(role.source_url) and not _syndicated(role, item)
        )
        return "strong", [role.id, other.id]
    mapped = _title_maps(title, functions)
    corroboration = [item for item in current if item not in role_pages]
    if mapped and (role_pages or corroboration):
        return "probable", [item.id for item in (role_pages or corroboration)[:2]]
    if title and role_pages:
        return "weak", [item.id for item in role_pages[:1]]
    return "unknown", []


def _is_current(item: Evidence, observed_on: date) -> bool:
    if item.published_at is None:
        return _on_org_page(item)
    return (observed_on - item.published_at).days <= _CURRENT_DAYS


def _states_responsibility(excerpt: str) -> bool:
    lowered = excerpt.lower()
    return any(token in lowered for token in _OWN)


def _states_role(excerpt: str, title: str) -> bool:
    lowered = excerpt.lower()
    if title and title.lower() in lowered:
        return True
    return any(token in lowered for token in _ROLE)


def _connects_function(item: Evidence, functions: list[str]) -> bool:
    lowered = item.excerpt.lower()
    if any(name in lowered for name in functions):
        return True
    problem = ("low_latency", "distributed_systems", "rag", "retrieval", "ai_search")
    return any(topic in item.topics for topic in problem)


def _title_maps(title: str, functions: list[str]) -> bool:
    lowered = title.lower()
    return any(name.split()[0] in lowered for name in functions) or "platform" in lowered


def _on_org_page(item: Evidence) -> bool:
    url = item.source_url.lower()
    if item.source_type in {"biography", "job_posting", "company_news", "engineering_blog", "blog"}:
        return True
    return any(part in url for part in ("/team", "/leadership", "/about", "/engineering", "/blog"))


def _independent(left: list[Evidence], right: list[Evidence]) -> bool:
    for item in left:
        for other in right:
            if item.id == other.id:
                continue
            if _host(item.source_url) != _host(other.source_url) and not _syndicated(item, other):
                return True
    return False


def _syndicated(left: Evidence, right: Evidence) -> bool:
    slug_a = left.source_url.rstrip("/").split("/")[-1]
    slug_b = right.source_url.rstrip("/").split("/")[-1]
    if slug_a and slug_a == slug_b:
        return True
    words_a = set(left.excerpt.lower().split())
    words_b = set(right.excerpt.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
    return overlap >= 0.8


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _dedupe(items: list[Evidence]) -> list[Evidence]:
    seen: set[str] = set()
    unique: list[Evidence] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)
    return unique


def stronger_if_recent(item: Evidence, observed_on: date) -> bool:
    if item.published_at is None:
        return False
    return (observed_on - item.published_at).days <= _STRONG_DAYS
