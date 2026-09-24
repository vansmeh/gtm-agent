"""Why-now is first-class. A trigger is not a recommendation to contact."""

import uuid
from datetime import date, timedelta

from app.domain.models import Evidence, WhyNowEvent

_EVENTS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("product_launch", "Product launch", frozenset({"ai_search"})),
    ("ai_initiative", "AI initiative", frozenset({"ai_search", "rag"})),
    ("hiring", "Hiring", frozenset({"hiring_platform", "hiring_ml"})),
    ("new_technical_project", "New technical project", frozenset({"rag"})),
)


def detect_why_now(
    evidence: list[Evidence],
    *,
    observed_on: date,
    window_days: int,
) -> list[WhyNowEvent]:
    cutoff = observed_on - timedelta(days=window_days)
    events: list[WhyNowEvent] = []
    for event_type, label, topics in _EVENTS:
        matched = [
            item
            for item in evidence
            if set(item.topics) & topics
            and item.published_at is not None
            and item.published_at >= cutoff
        ]
        if not matched:
            continue
        newest = max(item.published_at for item in matched if item.published_at is not None)
        events.append(
            WhyNowEvent(
                id=str(uuid.uuid4()),
                event_type=event_type,
                summary=(
                    f"{label} appears in public material dated {newest.isoformat()}. "
                    "This is a timing signal, not buying intent."
                ),
                event_date=newest,
                strength=round(min(0.9, 0.45 + 0.1 * len(matched)), 2),
                evidence_ids=[item.id for item in matched],
                buying_intent=False,
            )
        )
    return events
