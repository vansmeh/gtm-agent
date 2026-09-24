"""Find people from technical artifacts, then resolve whether they currently own the work."""

import re
from datetime import date

from app.domain.models import Evidence

_TERMS = (
    "low latency",
    "serving",
    "distributed systems",
    "runtime",
    "infrastructure",
    "platform",
    "performance",
    "caching",
    "backend",
    "high throughput",
    "architecture",
)
_BY = re.compile(r"\bBy ([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})\b")
_AUTHOR = re.compile(
    r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,2}),?\s+"
    r"(?:Staff|Principal|Architect|Lead|Head of|Director|Engineer)\b"
)
_TEAM = re.compile(r"\b([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3} team)\b")
_EXEC = re.compile(r"\b(chief|ceo|cfo|coo|cto|founder|president)\b", re.I)
_TECH_ROLE = ("principal", "staff", "architect", "lead", "director", "head of")
_CHANGED = ("formerly", "previously", "left ", "joined ")


def concepts_for_signal(signal_label: str) -> list[str]:
    lowered = signal_label.lower()
    if any(token in lowered for token in ("latency", "serving", "platform", "infrastructure")):
        return list(_TERMS)
    if any(token in lowered for token in ("search", "vector", "rag", "retrieval")):
        return ["search", "retrieval", "architecture", "platform", "infrastructure"]
    return ["architecture", "engineering", "platform"]


def artifact_queries(account_name: str, domain: str, signal_label: str) -> list[str]:
    """Search the technical work before leadership directories."""
    host = domain or account_name
    terms = concepts_for_signal(signal_label)
    queries = [f'{account_name} "{term}"' for term in terms[:8]]
    focus = terms[0]
    queries.extend(
        [
            f"{account_name} engineering blog {focus}",
            f"{account_name} conference {focus}",
            f"{account_name} speaker {focus}",
            f"site:github.com {account_name} {focus}",
            f"site:{host} {focus}",
            f"{account_name} postmortem {focus}",
        ]
    )
    return queries


def person_artifact_queries(name: str, account_name: str, term: str) -> list[str]:
    return [f'"{name}" "{account_name}" "{term}"']


def team_follow_up_queries(account_name: str, team: str) -> list[str]:
    return [
        f'{account_name} "{team}"',
        f'{account_name} "{team}" engineer',
        f'{account_name} "{team}" lead',
    ]


class ArtifactHit:
    def __init__(
        self,
        *,
        author: str,
        url: str,
        topic: str,
        published_at: date | None,
        evidence_id: str,
        kind: str,
    ) -> None:
        self.author = author
        self.url = url
        self.topic = topic
        self.published_at = published_at
        self.evidence_id = evidence_id
        self.kind = kind


def artifacts_from_evidence(evidence: list[Evidence], account_name: str) -> list[ArtifactHit]:
    """A named author is a candidate. The artifact does not prove current ownership."""
    account = account_name.lower()
    found: list[ArtifactHit] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        text = item.excerpt
        if account not in text.lower():
            continue
        if _wrong_company(text, account):
            continue
        names = _names_in(text)
        if not names:
            continue
        if "github.com" in item.source_url and not _reliable_github_attribution(text):
            continue
        kind = _kind(item)
        topic = item.topics[0] if item.topics else "engineering"
        for name in names:
            key = (name, item.source_url)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                ArtifactHit(
                    author=name,
                    url=item.source_url,
                    topic=topic,
                    published_at=item.published_at,
                    evidence_id=item.id,
                    kind=kind,
                )
            )
    return found


def teams_in_text(text: str) -> list[str]:
    names = [match.group(1) for match in _TEAM.finditer(text)]
    return list(dict.fromkeys(name.removeprefix("The ") for name in names))


def candidate_class(title: str, *, workload_connected: bool) -> str:
    lowered = title.lower()
    if _EXEC.search(lowered) and not workload_connected:
        return "executive"
    if any(token in lowered for token in _TECH_ROLE):
        return "technical_owner" if workload_connected else "technical_influencer"
    if "manager" in lowered:
        return "manager"
    if "vp" in lowered or "vice president" in lowered:
        return "technical_owner" if workload_connected else "executive"
    return "unknown"


def currentness_for(
    *,
    artifact_date: date | None,
    role_date: date | None,
    text: str,
    observed_on: date,
    role_days: int = 365,
) -> str:
    lowered = text.lower()
    if any(token in lowered for token in _CHANGED) and "joined" in lowered:
        return "recently_changed"
    role_current = role_date is not None and (observed_on - role_date).days <= role_days
    artifact_old = artifact_date is not None and (observed_on - artifact_date).days > role_days
    if role_current:
        return "current"
    if artifact_old:
        return "historical"
    return "unknown"


def converge_ownership(
    name: str,
    title: str,
    evidence: list[Evidence],
    *,
    observed_on: date,
    functions: list[str],
) -> tuple[str, list[str]]:
    """Several independent current signals can be strong. A title alone cannot."""
    named = [item for item in evidence if name in item.excerpt and _fresh(item, observed_on)]
    if candidate_class(title, workload_connected=False) == "executive":
        connected = [item for item in named if _workload(item, functions)]
        if not connected:
            return "weak", [item.id for item in named[:1]]
    role = [
        item
        for item in named
        if _role_source(item, title) and "github.com" not in item.source_url and item.source_type != "conference"
    ]
    role_urls = {item.source_url for item in role}
    artifacts = [
        item
        for item in named
        if _workload(item, functions) and item.source_url not in role_urls and item.source_type != "job_posting"
    ]
    teams = [item for item in evidence if _team_source(item) and _fresh(item, observed_on)]
    if not role or not artifacts:
        if role and not artifacts:
            return "weak", [role[0].id]
        return "unknown", []
    hosts = {_host(item.source_url) for item in role + artifacts + teams}
    if len(hosts) < 2:
        return "probable", [role[0].id, artifacts[0].id]
    ids = [role[0].id, artifacts[0].id]
    if teams:
        ids.append(teams[0].id)
    if len(ids) >= 2 and any(item.source_type in {"conference", "engineering_blog", "blog"} for item in artifacts):
        return "strong", ids
    return "probable", ids


def _fresh(item: Evidence, observed_on: date) -> bool:
    if item.published_at is None:
        return False
    return (observed_on - item.published_at).days <= 365


def _workload(item: Evidence, functions: list[str]) -> bool:
    lowered = item.excerpt.lower()
    if any(name in lowered for name in functions):
        return True
    return any(topic in item.topics for topic in ("low_latency", "distributed_systems", "rag", "retrieval"))


def _role_source(item: Evidence, title: str) -> bool:
    lowered = item.excerpt.lower()
    return bool(title) and title.lower() in lowered


def _team_source(item: Evidence) -> bool:
    lowered = item.excerpt.lower()
    return item.source_type == "job_posting" or "reports to" in lowered or "team owns" in lowered


def _names_in(text: str) -> list[str]:
    names = [match.group(1) for match in _BY.finditer(text)]
    names.extend(match.group(1) for match in _AUTHOR.finditer(text))
    return list(dict.fromkeys(names))


def _wrong_company(text: str, account: str) -> bool:
    match = re.search(r"\bat ([A-Z][A-Za-z0-9]+)", text)
    if match is None:
        return False
    org = match.group(1).lower()
    return account not in org and account not in text.lower()


def _reliable_github_attribution(text: str) -> bool:
    return bool(_BY.search(text) or _AUTHOR.search(text))


def _kind(item: Evidence) -> str:
    url = item.source_url.lower()
    if "github.com" in url:
        return "github"
    if item.source_type == "conference" or "speaker" in url or "talk" in url:
        return "talk"
    if item.source_type == "job_posting":
        return "job"
    return "article"


def _host(url: str) -> str:
    parts = url.split("/")
    return parts[2].lower() if len(parts) > 2 else ""
