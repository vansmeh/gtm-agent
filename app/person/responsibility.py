"""Responsibility is a sourced connection to the problem. A title is not enough."""

import re

from app.domain.models import Evidence

_VERB = re.compile(
    r"\b(owns|owned|leads|lead|leading|responsible|heads|runs|directs|oversees)\b",
    re.I,
)
_TOPIC = re.compile(
    r"\b(platform|infrastructure|search|architecture|backend|distributed|"
    r"vector|retrieval|caching|latency|rag|machine learning|ml infra)\b",
    re.I,
)
_PROBLEM = frozenset(
    {"low_latency", "distributed_systems", "rag", "caching", "ai_search", "retrieval", "vector_search"}
)


def extract_responsibilities(name: str, evidence: list[Evidence]) -> list[str]:
    found: list[str] = []
    for item in evidence:
        if name in item.excerpt and _VERB.search(item.excerpt) and _topic_hit(item):
            found.append(item.excerpt)
    return found


def function_ownership_excerpts(evidence: list[Evidence]) -> list[Evidence]:
    return [
        item
        for item in evidence
        if "ownership_platform" in item.topics or "reports_platform" in item.topics
    ]


def classify_responsibility(
    name: str,
    title: str,
    evidence: list[Evidence],
    function_label: str,
) -> tuple[str, list[str]]:
    named = [item for item in evidence if name in item.excerpt]
    confirmed = [item.excerpt for item in named if _VERB.search(item.excerpt) and _topic_hit(item)]
    if confirmed:
        return "confirmed", confirmed
    quoted = [item for item in named if set(item.topics) & _PROBLEM or _TOPIC.search(item.excerpt)]
    title_matches = bool(function_label) and function_label.lower() in title.lower()
    technical_title = _TOPIC.search(title) is not None
    if quoted and (title_matches or technical_title):
        return "probable", [item.excerpt for item in quoted]
    return "unknown", []


def _topic_hit(item: Evidence) -> bool:
    if set(item.topics) & _PROBLEM:
        return True
    return _TOPIC.search(item.excerpt) is not None
