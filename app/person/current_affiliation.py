"""Separate current affiliation, role, function, and ownership.

A recent company technical article shows affiliation and activity.
It does not, by itself, prove ownership or a current title.
"""

from dataclasses import dataclass, field
from datetime import date

from app.domain.models import Evidence, EvidenceEdge
from app.person.timeline import build_timeline

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
        f'"{name}" "{account_name}" "current title"',
        f'site:linkedin.com/in "{name}" "{account_name}"',
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
    activity = [
        item
        for item in named
        if _recent(item, observed_on)
        and not _interviewee_only(item, name)
        and (_technical(item, functions) or _author_metadata(item))
    ]
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
    snippets = [
        item
        for item in roles
        if item.source_type == "search_snippet" or item.evidence_type == "speaker_metadata"
    ]
    dated_roles = [item for item in roles if item.source_type != "search_snippet" and item.published_at is not None]
    timeline = build_timeline(name, title, evidence, observed_on=observed_on)
    if timeline.current is not None and timeline.current.state == "current":
        result.role_state = "current"
        result.role_evidence_ids = [timeline.current.evidence_id]
    elif snippets and not any(_dated(item, observed_on) for item in dated_roles):
        result.role_state = "probable_current"
        result.role_evidence_ids = [snippets[0].id]
        if result.affiliation == "unknown":
            result.affiliation = "probable"
            result.affiliation_evidence_ids = [snippets[0].id]
    elif result.affiliation in {"current", "probable"}:
        result.role_state = "probable_current"
        result.role_evidence_ids = list(result.affiliation_evidence_ids)
    elif timeline.historical and not recent_company:
        result.role_state = "historical"
        result.role_evidence_ids = [timeline.historical[-1].evidence_id]
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
    if roles and team and not _same_copy(roles[0], team[0]):
        return "strong", [roles[0].id, team[0].id]
    if activity and roles and not _same_copy(activity[0], roles[0]):
        return "probable", [activity[0].id, roles[0].id]
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
    usable_roles = [item for item in roles if item.source_type != "search_snippet"]
    role = usable_roles[0] if usable_roles else None
    artifact = next((item for item in activity if role is None or not _same_copy(item, role)), None)
    if (
        artifact is not None
        and role is not None
        and team
        and result.affiliation in {"current", "probable"}
        and _independent_group(artifact, role, team[0])
    ):
        return "strong", [artifact.id, role.id, team[0].id]
    if activity and result.role_state in {"current", "probable_current"}:
        return "probable", [activity[0].id]
    if result.function_level == "weak":
        return "weak", []
    return "unknown", []


def evidence_graph(
    name: str,
    result: AffiliationResolution,
    *,
    responsibility: str,
    trigger: str,
    trigger_evidence_ids: list[str],
    observed_on: date | None,
) -> list[EvidenceEdge]:
    """Each claim is an edge. A missing claim does not invent the next one."""
    edges: list[EvidenceEdge] = []
    if result.affiliation == "unknown":
        return edges
    edges.append(
        EvidenceEdge(
            source=name,
            target=result.affiliation,
            relation="current_affiliation",
            evidence_type="affiliation",
            evidence_ids=result.affiliation_evidence_ids,
            confidence=0.7 if result.affiliation == "current" else 0.45,
            observed_on=observed_on,
        )
    )
    if result.role_state == "unknown":
        return edges
    edges.append(
        EvidenceEdge(
            source=result.affiliation,
            target=result.role_state,
            relation="current_role",
            evidence_type="current_role",
            evidence_ids=result.role_evidence_ids,
            confidence=0.8 if result.role_state == "current" else 0.5,
            observed_on=observed_on,
        )
    )
    if result.function_level == "unknown":
        return edges
    edges.append(
        EvidenceEdge(
            source=result.role_state,
            target=result.function_level,
            relation="current_function",
            evidence_type="function",
            evidence_ids=result.function_evidence_ids,
            confidence=0.75 if result.function_level == "strong" else 0.4,
            observed_on=observed_on,
        )
    )
    if not responsibility:
        return edges
    edges.append(
        EvidenceEdge(
            source=result.function_level,
            target=responsibility,
            relation="technical_responsibility",
            evidence_type="technical_responsibility",
            evidence_ids=result.function_evidence_ids,
            confidence=0.6 if result.function_level == "strong" else 0.35,
            observed_on=observed_on,
        )
    )
    if trigger:
        edges.append(
            EvidenceEdge(
                source=responsibility,
                target=trigger,
                relation="account_trigger",
                evidence_type="account_trigger",
                evidence_ids=trigger_evidence_ids,
                confidence=0.7 if trigger_evidence_ids else 0.3,
                observed_on=observed_on,
            )
        )
    if result.technical_activity != "unknown":
        edges.append(
            EvidenceEdge(
                source=name,
                target=result.technical_activity,
                relation="technical_expertise",
                evidence_type="technical_attribution",
                evidence_ids=result.activity_evidence_ids,
                confidence=0.7 if result.technical_activity == "strong" else 0.35,
                observed_on=observed_on,
            )
        )
    if result.ownership_level != "unknown":
        edges.append(
            EvidenceEdge(
                source=name,
                target=result.ownership_level,
                relation="ownership",
                evidence_type="ownership",
                evidence_ids=result.ownership_evidence_ids,
                confidence=0.8 if result.ownership_level == "strong" else 0.4,
                observed_on=observed_on,
            )
        )
    return edges


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


def _author_metadata(item: Evidence) -> bool:
    return item.evidence_type in {"author_metadata", "json_ld"} and item.field in {
        "author",
        "article:author",
        "og:article:author",
    }


def _interviewee_only(item: Evidence, name: str) -> bool:
    if item.evidence_type == "interviewee":
        return True
    text = item.excerpt.lower()
    return f"hosting {name.lower()}" in text or text.startswith("interview with")


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


def _same_copy(left: Evidence, right: Evidence) -> bool:
    words_a = set(left.excerpt.lower().split())
    words_b = set(right.excerpt.lower().split())
    if not words_a or not words_b:
        return False
    return len(words_a & words_b) / min(len(words_a), len(words_b)) >= 0.8


def _independent_group(activity: Evidence, role: Evidence, team: Evidence) -> bool:
    items = [activity, role, team]
    hosts = {_host(item.source_url) for item in items}
    if len(hosts) < 2:
        return False
    return not (_same_copy(activity, role) or _same_copy(activity, team) or _same_copy(role, team))


def _host(url: str) -> str:
    parts = url.split("/")
    return parts[2].lower() if len(parts) > 2 else ""
