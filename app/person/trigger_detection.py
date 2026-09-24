"""Recent public changes tied to a person. Timing is not buying intent."""

from datetime import date, timedelta

from app.domain.models import Evidence

_TRIGGER_TOPICS = frozenset(
    {"ai_search", "rag", "hiring_platform", "hiring_ml", "low_latency", "ownership_platform"}
)


def recent_named_evidence(
    name: str,
    evidence: list[Evidence],
    *,
    observed_on: date,
    window_days: int,
) -> list[Evidence]:
    cutoff = observed_on - timedelta(days=window_days)
    matched: list[Evidence] = []
    for item in evidence:
        if name not in item.excerpt:
            continue
        if item.published_at is None or item.published_at < cutoff:
            continue
        if not (set(item.topics) & _TRIGGER_TOPICS):
            continue
        matched.append(item)
    return matched
