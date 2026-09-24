"""Seven explicit fit dimensions. There is no collapsed person score."""

from datetime import date, timedelta

from app.domain.models import Evidence, OwningFunction, PersonFit, PersonRecord
from app.person.responsibility import extract_responsibilities, function_ownership_excerpts
from app.person.trigger_detection import recent_named_evidence

_PROBLEM = frozenset({"low_latency", "distributed_systems", "rag", "caching", "ai_search", "retrieval"})


def _round(value: float) -> float:
    return round(min(0.95, max(0.0, value)), 2)


def assess_fit(
    person: PersonRecord,
    evidence: list[Evidence],
    functions: list[OwningFunction],
    *,
    observed_on: date,
    window_days: int,
) -> PersonFit:
    primary = functions[0] if functions else None
    label = primary.label if primary else ""
    title_l = person.title.lower()
    label_l = label.lower()
    function_tokens = {tok for tok in label_l.split() if len(tok) > 3}
    title_tokens = {tok for tok in title_l.split() if len(tok) > 3}
    if function_tokens and label_l and label_l in title_l:
        role_relevance = 0.92
    elif function_tokens:
        role_relevance = len(function_tokens & title_tokens) / len(function_tokens)
    else:
        role_relevance = 0.0

    direct = extract_responsibilities(person.name, evidence)
    ownership_evidence = function_ownership_excerpts(evidence)
    quoted = [
        item
        for item in evidence
        if person.name in item.excerpt and (set(item.topics) & _PROBLEM)
    ]
    title_matches_function = bool(label_l and label_l in title_l)
    if direct and quoted:
        ownership = 0.9
        ownership_basis = "Public excerpt uses ownership language and discusses the technical problem."
    elif quoted and title_matches_function and ownership_evidence:
        ownership = 0.78
        ownership_basis = (
            "Title matches the function that sources say owns the path, and the person is quoted "
            "on the technical problem. No sentence says this person personally owns it."
        )
    elif title_matches_function and ownership_evidence:
        ownership = 0.62
        ownership_basis = "Ownership is by title match to the function named in sources."
    elif quoted:
        ownership = 0.4
        ownership_basis = "Quoted near the problem without a function-ownership statement."
    else:
        ownership = 0.15 if person.title else 0.0
        ownership_basis = "No public statement connects this person to the technical problem."

    footprint = set(person.footprint_topics) & _PROBLEM
    technical = (len(footprint) / len(_PROBLEM)) if _PROBLEM else 0.0

    named_recent = recent_named_evidence(
        person.name, evidence, observed_on=observed_on, window_days=window_days
    )
    account_recent = [
        item
        for item in evidence
        if item.published_at is not None
        and item.published_at >= observed_on - timedelta(days=window_days)
        and (set(item.topics) & {"ai_search", "hiring_platform", "hiring_ml", "rag"})
    ]
    if named_recent:
        timing = 0.85
        timing_basis = "Named in recent public material that discusses the technical problem."
    elif title_matches_function and account_recent:
        timing = 0.55
        timing_basis = "Recent account triggers match the function in the title. The person is not named on them."
    elif any(person.name in item.excerpt for item in account_recent):
        timing = 0.2
        timing_basis = "Named on a recent page without a technical link."
    else:
        timing = 0.1
        timing_basis = "No recent public trigger tied to this person."

    source_conf = [item.confidence for item in evidence if person.name in item.excerpt]
    source_count = len({item.source_url for item in evidence if person.name in item.excerpt})
    base = 0.85 if source_count >= 3 else 0.7 if source_count == 2 else 0.45 if source_count == 1 else 0.0
    mean_conf = sum(source_conf) / len(source_conf) if source_conf else 0.0
    public = base * min(1.0, mean_conf / 0.6) if source_count else 0.0
    contact = 0.55 if source_count >= 2 and person.title else 0.35 if person.title else 0.15

    return PersonFit(
        role_relevance=_round(role_relevance),
        problem_ownership=_round(ownership),
        technical_relevance=_round(technical),
        timing_relevance=_round(timing),
        public_evidence=_round(public),
        seniority=_round(person.seniority),
        contact_confidence=_round(contact),
        rationale={
            "role_relevance": f"Title '{person.title}' compared with function '{label or 'unknown'}'.",
            "problem_ownership": ownership_basis,
            "technical_relevance": f"Footprint topics {sorted(footprint) or ['none']} overlap the problem set.",
            "timing_relevance": timing_basis,
            "public_evidence": f"{source_count} public source(s) name this person.",
            "seniority": "Read from the title only. Seniority is not the selection key.",
            "contact_confidence": "No verified public email or phone. Identity confidence is not a contact method.",
        },
    )
