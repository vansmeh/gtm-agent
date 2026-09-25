"""Rank people on explicit dimensions. Seniority does not outrank ownership or evidence."""

from app.domain.models import PersonDossier, PersonFit, PersonRecord

_PRIMARY = (
    "problem_ownership",
    "technical_relevance",
    "role_relevance",
    "public_evidence",
    "timing_relevance",
)


def _key(fit: PersonFit) -> tuple[float, ...]:
    return tuple(getattr(fit, name) for name in _PRIMARY)


def selection_status_for(person: PersonRecord) -> str:
    """Verified only when identity, role, responsibility, and the problem link all hold."""
    fit = person.fit
    identity_ok = (
        person.identity_confidence >= 0.55
        and bool(person.company)
        and bool(person.title)
        and bool(person.identity_excerpt)
        and bool(person.source_urls)
        and person.name in person.identity_excerpt
    )
    if person.contradictions or not identity_ok:
        return "rejected" if person.contradictions else "weak_candidate"
    if person.validity == "stale":
        return "weak_candidate"
    responsibility_ok = person.responsibility_status in {"confirmed", "probable"}
    connection_ok = fit is not None and fit.problem_ownership >= 0.6
    if responsibility_ok and connection_ok and person.validity == "current":
        return "verified_person"
    return "weak_candidate"


def rank_people(people: list[PersonRecord]) -> list[PersonRecord]:
    def sort_key(person: PersonRecord) -> tuple[float, ...]:
        if person.fit is None:
            return (0.0,)
        return _key(person.fit)

    return sorted(people, key=sort_key, reverse=True)


def explain_pair(best: PersonRecord, other: PersonRecord) -> str:
    if best.fit is None or other.fit is None:
        return "Fit dimensions are missing, so no comparison is made."
    ahead: list[str] = []
    for name in _PRIMARY:
        b = float(getattr(best.fit, name))
        o = float(getattr(other.fit, name))
        if b > o + 0.05:
            ahead.append(f"{name} {b:.2f} vs {o:.2f}")
    comparison = ", ".join(ahead) if ahead else "no primary dimension"
    return (
        f"{best.name} ranks ahead of {other.name} on {comparison}. "
        f"Seniority is {best.fit.seniority:.2f} vs {other.fit.seniority:.2f} and is not the selection key."
    )


def build_dossier(person: PersonRecord, *, comparison: str, problem_label: str) -> PersonDossier:
    fit = person.fit
    owns = person.responsibilities or [
        fit.rationale.get("problem_ownership", "Ownership is not established.") if fit else "Unknown."
    ]
    evidence_lines = [
        f"{item.title} ({item.url})" + (" [authored]" if item.authored else "")
        for item in person.activity
    ]
    return PersonDossier(
        who=f"{person.name}, {person.title or 'title not established from public sources'}.",
        appears_to_own=" ".join(owns),
        relevant_problems=[problem_label] if problem_label else [],
        public_technical_evidence=evidence_lines or ["No public technical document was tied to this person."],
        what_changed_recently=fit.rationale.get("timing_relevance", "").split(". ") if fit else [],
        why_they_would_care=(
            "Hypothesis only: the public role sits near the technical problem. "
            "Care, budget, and buying intent are not established."
        ),
        why_this_person_instead_of_another=comparison,
    )
