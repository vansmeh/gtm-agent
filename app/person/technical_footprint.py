"""Technical topics in pages the person authored or was quoted on."""

from app.domain.models import Evidence, Observation

_TECH = frozenset(
    {"low_latency", "distributed_systems", "caching", "retrieval", "rag", "ai_search", "feature_pipeline"}
)


def authored_urls(name: str, observations: list[Observation]) -> list[str]:
    urls: list[str] = []
    for obs in observations:
        if obs.poisoned:
            continue
        if obs.sanitized_text.startswith(f"By {name}") or f"By {name}," in obs.sanitized_text:
            urls.append(obs.url)
    return urls


def build_footprint(
    name: str,
    evidence: list[Evidence],
    observations: list[Observation],
) -> list[str]:
    own = set(authored_urls(name, observations))
    topics: set[str] = set()
    for item in evidence:
        named = name in item.excerpt
        if not named and item.source_url not in own:
            continue
        topics.update(topic for topic in item.topics if topic in _TECH)
    return sorted(topics)
