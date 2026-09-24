"""Public documents that name a person or carry their byline."""

from app.domain.models import ActivityItem, Evidence, Observation


def _authored(name: str, text: str) -> bool:
    return text.startswith(f"By {name}") or f"By {name}," in text


def collect_activity(
    name: str,
    observations: list[Observation],
    evidence: list[Evidence],
) -> list[ActivityItem]:
    urls = {item.source_url for item in evidence if name in item.excerpt}
    items: list[ActivityItem] = []
    for obs in observations:
        if obs.poisoned:
            continue
        authored = _authored(name, obs.sanitized_text)
        if obs.url not in urls and not authored:
            continue
        items.append(
            ActivityItem(
                url=obs.url,
                title=obs.title,
                source_type=obs.source_type,
                published_at=obs.published_at,
                authored=authored,
            )
        )
    return items
