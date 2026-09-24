"""Separate current affiliation, role, function, and ownership.

A recent company technical article shows affiliation and activity.
It does not, by itself, prove ownership or a current title.
"""

from dataclasses import dataclass, field
from datetime import date

from app.domain.models import Evidence

_DAYS = 365
_OFFICIAL = ("engineering_blog", "blog", "company_news", "biography")
_ACTIVITY = ("low_latency", "distributed_systems", "rag", "retrieval", "ai_search", "latency", "serving")


@dataclass
class AffiliationResolution:
    affiliation: str = "unknown"
    affiliation_evidence_ids: list[str] = field(default_factory=list)
    role_state: str = "unknown"
    role_evidence_ids: list[str] = field(default_factory=list)
    function_level: str = "unknown"
    function_evidence_ids: list[str] = field(default_factory=list)
    technical_activity: str = "unknown"
    activity_evidence_ids: list[str] = field(default_factory=list)
    ownership_level: str = "unknown"
    ownership_evidence_ids: list[str] = field(default_factory=list)
    candidate_state: str = "rejected"


def current_role_search_queries(name: str, account_name: str, domain: str) -> list[str]:
    """Look for a newer role source before treating an older page as the current one."""
    host = domain or account_name
    return [
        f'"{name}" "{account_name}" 2026',
        f'"{name}" "{account_name}" current',
        f'"{name}" site:{host}',
        f'site:{host} "{name}"',
        f'site:{host} "{name}" engineering',
        f'site:{host} "{name}" platform',
        f'site:{host} "{name}" infrastructure',
    ]


def resolve_affiliation(
    name: str,
    title: str,
    evidence: list[Evidence],
    *,
    account_name: str,
    domain: str,
    functions: list[str],
    observed_on: date,
) -> AffiliationResolution:
    named = [item for item in evidence if name in item.excerpt]
    company = [item for item in named if _company_source(item, account_name, domain)]
    recent_company = [item for item in company if _recent(item, observed_on)]
    old_company = [item for item in company if item not in recent_company and _dated(item, observed_on)]
    activity = [item for item in named if _recent(item, observed_on) and _technical(item, functions)]
    company_activity = [item for item in activity if item in company]
    roles = [item for item in named if _states_role(item, title)]
    recent_roles = [item for item in roles if _recent(item, observed_on) or _undated_org(item)]
    team = [
        item
        for item in evidence
        if _team_page(item) and _recent(item, observed_on) and _technical(item, functions)
    ]
    result = AffiliationResolution()
    if recent_company:
        result.affiliation = "current" if any(_official(item) for item in recent_company) else "probable"
        result.affiliation_evidence_ids = [item.id for item in recent_company[:2]]
    elif old_company and not recent_company:
        result.affiliation = "historical"
        result.affiliation_evidence_ids = [old_company[0].id]
    if company_activity:
        result.technical_activity = "strong"
        result.activity_evidence_ids = [item.id for item in company_activity[:2]]
    elif any(_technical(item, functions) for item in old_company):
        result.technical_activity = "historical"
        result.activity_evidence_ids = [item.id for item in old_company[:1]]
    if recent_roles:
        result.role_state = "current"
        result.role_evidence_ids = [item.id for item in recent_roles[:1]]
    elif result.affiliation in {"current", "probable"}:
        result.role_state = "probable_current"
        result.role_evidence_ids = list(result.affiliation_evidence_ids)
    elif roles and not recent_company:
        result.role_state = "historical"
        result.role_evidence_ids = [roles[0].id]
    result.function_level, result.function_evidence_ids = _function_level(
        title, activity, recent_roles, team, functions
    )
    result.ownership_level, result.ownership_evidence_ids = _ownership(
        result, activity, recent_roles, team
    )
    result.candidate_state = _state(result)
    return result


def _function_level(
    title: str,
    activity: list[Evidence],
    roles: list[Evidence],
    team: list[Evidence],
    functions: list[str],
) -> tuple[str, list[str]]:
    if activity and (roles or team):
        ids = [activity[0].id]
        ids.append((roles or team)[0].id)
        if any(_states_role(item, title) and _technical(item, functions) for item in activity):
            return "strong", ids
        if roles or team:
            return "strong", ids
    if activity:
        return "probable", [activity[0].id]
    lowered = title.lower()
    if title and not any(function.split()[0] in lowered for function in functions):
        if any(token in lowered for token in ("manager", "engineer", "director", "vp")):
            return "weak", []
    return "unknown", []


def _ownership(
    result: AffiliationResolution,
    activity: list[Evidence],
    roles: list[Evidence],
    team: list[Evidence],
) -> tuple[str, list[str]]:
    if result.technical_activity != "strong" and result.affiliation != "current":
        return "unknown", []
    if result.function_level == "weak" and not activity:
        return "weak", []
    sources = activity + roles + team
    hosts = {_host(item.source_url) for item in sources}
    if activity and (roles or team) and len(hosts) >= 2 and result.affiliation in {"current", "probable"}:
        ids = [activity[0].id, (roles or team)[0].id]
        if team and team[0].id not in ids:
            ids.append(team[0].id)
        return "strong", ids
    if activity and result.role_state in {"current", "probable_current"}:
        return "probable", [activity[0].id]
    if result.function_level == "weak":
        return "weak", []
    return "unknown", []


def _state(result: AffiliationResolution) -> str:
    if (
        result.affiliation in {"current", "probable"}
        and result.role_state in {"current", "probable_current"}
        and result.ownership_level in {"explicit", "strong"}
        and result.function_level in {"explicit", "strong"}
    ):
        return "verified_current_owner"
    if result.affiliation == "current" and result.role_state == "current":
        return "verified_current_person"
    if result.affiliation in {"current", "probable"} and result.role_state == "probable_current":
        return "probable_current_person"
    if result.affiliation == "historical" or result.role_state == "historical":
        return "historical_person"
    return "rejected"


def _company_source(item: Evidence, account_name: str, domain: str) -> bool:
    url = item.source_url.lower()
    text = item.excerpt.lower()
    if domain and domain.lower() in url:
        return True
    return account_name.lower() in text and (_official(item) or "speaker" in url or item.source_type == "conference")


def _official(item: Evidence) -> bool:
    if item.source_type in _OFFICIAL:
        return True
    url = item.source_url.lower()
    return any(part in url for part in ("/blog", "/engineering", "/author", "/news"))


def _recent(item: Evidence, observed_on: date) -> bool:
    if item.published_at is None:
        return False
    return (observed_on - item.published_at).days <= _DAYS


def _dated(item: Evidence, observed_on: date) -> bool:
    return item.published_at is not None and not _recent(item, observed_on)


def _technical(item: Evidence, functions: list[str]) -> bool:
    text = item.excerpt.lower()
    if any(function in text for function in functions):
        return True
    return any(topic in item.topics for topic in _ACTIVITY)


def _states_role(item: Evidence, title: str) -> bool:
    text = item.excerpt.lower()
    if title and title.lower() in text:
        return True
    return any(token in text for token in ("engineer", "director", "manager", "head of", "architect"))


def _undated_org(item: Evidence) -> bool:
    return item.published_at is None and any(
        part in item.source_url.lower() for part in ("/team", "/leadership", "/people", "/about")
    )


def _team_page(item: Evidence) -> bool:
    text = item.excerpt.lower()
    return item.source_type == "job_posting" or "reports to" in text or "team owns" in text or "team is" in text


def _host(url: str) -> str:
    parts = url.split("/")
    return parts[2].lower() if len(parts) > 2 else ""
