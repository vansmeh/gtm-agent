"""PersonOpportunity: one person, one problem, one reason to contact or not."""

import re
import uuid
from datetime import datetime

from app.domain.models import (
    Contactability,
    Evidence,
    Opportunity,
    PersonHypothesis,
    PersonOpportunity,
    PersonRecord,
    TechnicalSignal,
    WhyNowEvent,
)

_FAMILIES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("rag_architecture", "ai_search_launch", "vector_search", "rag", "retrieval", "vector"),
        ("AI/ML", "Search", "ML Platform", "Platform Engineering", "Architecture"),
    ),
    (
        ("low_latency_serving", "low_latency", "caching"),
        ("Platform", "Infrastructure", "Backend", "Architecture"),
    ),
    (("platform_hiring", "hiring_platform"), ("Platform Engineering", "Infrastructure")),
    (("ml_infrastructure_hiring", "hiring_ml"), ("AI/ML", "ML Platform")),
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_ACCESS = ("director", "head of", "manager")
_ROLES = ("Head", "Director", "VP", "Lead", "Principal", "Staff", "Architect", "Engineering Manager")


def hypotheses_for(signals: list[TechnicalSignal]) -> list[PersonHypothesis]:
    built: list[PersonHypothesis] = []
    for signal in signals:
        families: list[str] = []
        for topics, roles in _FAMILIES:
            if signal.signal_type in topics or any(topic in signal.label.lower() for topic in topics):
                for role in roles:
                    if role not in families:
                        families.append(role)
        if not families:
            families = ["Platform", "Infrastructure", "Architecture"]
        functions = families[:5]
        built.append(
            PersonHypothesis(
                id=str(uuid.uuid4()),
                signal_id=signal.id,
                signal_label=signal.label,
                likely_functions=functions,
                candidate_role_families=list(_ROLES),
                rationale=(
                    f"{signal.label} maps to {', '.join(functions)} "
                    "because the public signal describes that work. Titles alone are not the mapping."
                ),
            )
        )
    return built


def hypothesis_queries(account_name: str, hypotheses: list[PersonHypothesis]) -> list[str]:
    topic = hypotheses[0].signal_label if hypotheses else ""
    short = "vector search" if "vector" in topic.lower() else "search" if "search" in topic.lower() else ""
    queries: list[str] = []
    for role in ("Staff", "Principal", "Architect", "Head", "Director"):
        query = f"{account_name} {role} {short}".strip()
        if query not in queries:
            queries.append(query)
    return queries


_FOOTPRINT_TOPICS = (
    "RAG",
    "search",
    "vector",
    "infrastructure",
    "platform",
    "latency",
    "distributed systems",
)
_TRIGGERS = (
    "promotion",
    "new role",
    "new team",
    "new initiative",
    "technical talk",
    "article",
    "hiring",
    "architecture",
)


def footprint_queries(name: str, account_name: str, topic: str) -> list[str]:
    focus = topic or "architecture"
    queries = [f'"{name}" "{account_name}" {focus}']
    for item in _FOOTPRINT_TOPICS:
        query = f'"{name}" "{account_name}" {item}'
        if query not in queries:
            queries.append(query)
    queries.append(f'"{name}" "{account_name}" architecture')
    queries.append(f'"{name}" github')
    return queries


def trigger_queries(name: str, account_name: str) -> list[str]:
    return [f'"{name}" "{account_name}" {item}' for item in _TRIGGERS]


def current_role_queries(name: str, account_name: str, domain: str, title: str) -> list[str]:
    host = domain or account_name
    role = title or "engineer"
    return [
        f'"{name}" "{account_name}" current role',
        f'"{name}" "{account_name}" 2026',
        f'"{name}" site:{host}',
        f'site:{host} "{name}"',
        f'site:{host} "{role}"',
        f'"{name}" "{account_name}" promoted',
        f'"{name}" "{account_name}" joined',
    ]


def c_suite_without_specialist_role(title: str) -> bool:
    lowered = title.lower()
    specialist = re.search(
        r"\b(head of|director|vice president|\bvp\b|lead|principal|staff|architect|engineering manager)\b",
        lowered,
    )
    if specialist:
        return False
    return re.search(r"\b(chief|ceo|cto|founder|president)\b", lowered) is not None


def research_gap(
    *,
    account_name: str,
    problem: str,
    has_owner: bool,
    has_trigger: bool,
    has_hypothesis: bool,
    functions: list[str] | None = None,
) -> tuple[list[str], str]:
    missing: list[str] = []
    function = (functions or ["Platform"])[0].title()
    if not has_owner:
        missing.append(f"Current {function} owner")
    if not has_trigger:
        missing.append("current trigger linked to a current owner")
    if not has_hypothesis:
        missing.append("credible Redis hypothesis")
    if not problem:
        missing.append("relevant technical problem")
    if not missing:
        return [], ""
    focus = problem or "the affected system"
    question = (
        f"Find current {account_name} {function} leadership and verify ownership of {focus}."
    )
    return missing, question


def person_kind_for(person: PersonRecord) -> str:
    title = person.title.lower()
    fit = person.fit
    owns = (
        person.selection_status == "verified_person"
        and person.responsibility_status in {"confirmed", "probable"}
        and fit is not None
        and fit.problem_ownership >= 0.6
    )
    if owns:
        return "problem_owner"
    if re.search(r"\b(chief|ceo|cto|vp|vice president|president|founder)\b", title):
        return "executive"
    if any(token in title for token in _ACCESS) or "staff" in title or "principal" in title:
        return "access_path"
    return "access_path"


def contactability_for(person: PersonRecord, evidence: list[Evidence]) -> Contactability:
    named = [item for item in evidence if person.name in item.excerpt]
    urls = " ".join(person.source_urls).lower()
    public_email = _EMAIL.search(person.identity_excerpt) is not None
    public_profile = any(
        host in urls for host in ("github.com", "/speaker", "/talk", "conference", "/author", "/bio", "/contact")
    )
    technical = bool(person.authored_urls) or bool(person.footprint_topics)
    known_role = bool(person.title) and person.identity_confidence >= 0.55 and not person.contradictions
    recency = person.validity == "current"
    company_path = bool(person.company) and known_role and not public_email
    if public_email and known_role and technical:
        level = "high"
    elif known_role and (technical or public_profile):
        level = "medium"
    elif known_role:
        level = "low"
    else:
        level = "unknown"
    return Contactability(
        level=level,  # type: ignore[arg-type]
        public_profile=public_profile,
        public_email=public_email,
        company_contact_path=company_path,
        public_technical_presence=technical,
        known_role=known_role,
        recency=recency,
        evidence_ids=[item.id for item in named[:4]],
        note="No email address is invented. Contactability uses only public evidence.",
    )


def angle_for(kind: str, person: PersonRecord, problem: str) -> str:
    if kind == "problem_owner":
        return (
            f"Technical angle for {person.name}: public material ties this role to {problem or 'the problem'}. "
            "This is not the message for an executive sponsor."
        )
    if kind == "executive":
        return (
            f"Executive context for {person.name}. The title is not ownership. "
            "Do not send the owner message to this person."
        )
    return (
        f"Access path for {person.name}. Use this person to reach the owner. "
        "Do not treat them as the problem owner."
    )


def build_opportunities(
    *,
    account_id: str,
    people: list[PersonRecord],
    signals: list[TechnicalSignal],
    evidence: list[Evidence],
    observed_at: datetime,
) -> list[PersonOpportunity]:
    problem = signals[0].label if signals else ""
    signal_ids = [item.id for item in signals]
    rows: list[PersonOpportunity] = []
    for person in people:
        kind = person_kind_for(person)
        named = [item.id for item in evidence if person.name in item.excerpt]
        rows.append(
            PersonOpportunity(
                id=str(uuid.uuid4()),
                account_id=account_id,
                person_id=person.id,
                person_name=person.name,
                person_title=person.title,
                person_kind=kind,  # type: ignore[arg-type]
                technical_problem=problem,
                signal_ids=signal_ids,
                evidence_ids=named or person.source_urls[:1],
                person_fit=person.fit,
                contactability=contactability_for(person, evidence),
                angle=angle_for(kind, person, problem),
                confidence=0.0 if person.fit is None else person.fit.problem_ownership,
                created_at=observed_at,
                updated_at=observed_at,
            )
        )
    return rows


def apply_why_now(
    rows: list[PersonOpportunity],
    events: list[WhyNowEvent],
    evidence: list[Evidence],
    people: list[PersonRecord] | None = None,
) -> None:
    credible = [event for event in events if event.event_type != "unknown"]
    by_id = {person.id: person for person in people or []}
    for row in rows:
        trigger_ids = {eid for event in credible for eid in event.evidence_ids}
        named = [
            item
            for item in evidence
            if row.person_name and row.person_name in item.excerpt and item.id in trigger_ids
        ]
        person = by_id.get(row.person_id)
        account = credible[0].summary if credible else ""
        if named:
            row.why_now = named[0].excerpt
            row.why_now_credible = True
            row.trigger_strength = "strong"
            row.account_trigger = account
            row.trigger_link = "Person is named on the current trigger."
        elif (
            person is not None
            and person.validity == "current"
            and person.current_ownership
            and             person.responsibility_status in {"confirmed", "probable"}
            and person.ownership_level in {"explicit", "strong"}
            and credible
        ):
            row.why_now = "Current account event affects a function this person currently owns."
            row.why_now_credible = True
            row.trigger_strength = "account-linked"
            row.account_trigger = account
            function = person.function_guess or "the affected function"
            row.trigger_link = f"ACCOUNT TRIGGER → {function} → {person.name}"
        else:
            row.why_now = "unknown"
            row.why_now_credible = False
            row.trigger_strength = "unknown"
            row.account_trigger = account
            row.trigger_link = ""


def apply_redis(rows: list[PersonOpportunity], opportunities: list[Opportunity]) -> None:
    primary = next((item for item in opportunities if item.is_primary), None)
    for row in rows:
        if primary is None:
            row.redis_hypothesis = ""
            row.redis_credible = False
            row.alternative_technologies = []
            continue
        row.redis_hypothesis = f"{primary.use_case_id}={primary.relevance}. {primary.hypothesis}"
        row.redis_credible = primary.relevance in {"plausible", "strongly_supported"}
        row.alternative_technologies = list(primary.alternatives)
        row.supporting_evidence_ids = list(primary.supporting_evidence_ids)
        row.contradicting_evidence_ids = list(primary.contradicting_evidence_ids)


def decide_contact(row: PersonOpportunity, person: PersonRecord | None) -> str:
    if person is not None and person.contradictions:
        return "ignore"
    has_problem = bool(row.technical_problem)
    level = "unknown" if person is None else person.ownership_level
    owns = row.person_kind == "problem_owner" and level in {"explicit", "strong"}
    if has_problem and owns and row.why_now_credible and row.redis_credible:
        return "contact_now"
    if level == "probable":
        return "research_more"
    if not has_problem and not owns:
        return "ignore"
    if row.person_kind == "executive" and not owns:
        return "nurture" if has_problem else "research_more"
    return "research_more"


def decide_channel(row: PersonOpportunity, *, prior_touches: int = 0) -> str:
    if row.decision in {"ignore"}:
        return "none"
    fit = row.person_fit
    contact = row.contactability
    if prior_touches > 0 and row.decision != "contact_now":
        return "none"
    if row.person_kind == "problem_owner" and row.decision == "contact_now":
        if contact.public_email:
            return "email"
        if contact.level in {"medium", "high", "low"} and fit is not None and fit.role_relevance >= 0.5:
            return "email"
    if row.person_kind == "access_path" and contact.public_profile:
        return "linkedin"
    if row.person_kind == "executive":
        return "none"
    if contact.public_email:
        return "email"
    return "none"


def assign_threads(rows: list[PersonOpportunity]) -> None:
    owners = [row for row in rows if row.person_kind == "problem_owner" and row.decision == "contact_now"]
    owners.sort(key=lambda row: row.confidence, reverse=True)
    owner_names = {item.person_name for item in owners}
    access = [
        row for row in rows if row.person_kind == "access_path" and row.person_name not in owner_names
    ]
    access.sort(key=lambda row: (row.contactability.public_technical_presence, row.confidence), reverse=True)
    executives = [row for row in rows if row.person_kind == "executive"]
    executives.sort(key=lambda row: row.confidence, reverse=True)
    if owners:
        owners[0].thread_role = "primary_contact"
    if access:
        access[0].thread_role = "secondary_contact"
    if executives:
        executives[0].thread_role = "executive_thread"
