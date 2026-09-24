"""Group sourced excerpts into technical signals. Labels classify evidence; they do not add facts."""

import uuid

from app.domain.models import Evidence, TechnicalSignal

_SIGNALS: tuple[tuple[str, str, str], ...] = (
    ("ai_search_launch", "AI search product launch", "ai_search"),
    ("rag_architecture", "Retrieval-augmented generation architecture", "rag"),
    ("vector_search", "Vector search", "vector_search"),
    ("low_latency_serving", "Low-latency serving concern", "low_latency"),
    ("platform_hiring", "Platform engineering hiring", "hiring_platform"),
    ("ml_infrastructure_hiring", "ML infrastructure hiring", "hiring_ml"),
)

PROBLEM_SIGNAL_TYPES = frozenset(
    {"ai_search_launch", "rag_architecture", "low_latency_serving", "vector_search"}
)


def detect_signals(evidence: list[Evidence]) -> list[TechnicalSignal]:
    signals: list[TechnicalSignal] = []
    for signal_type, label, topic in _SIGNALS:
        matched = [item for item in evidence if topic in item.topics]
        if not matched:
            continue
        confidence = round(max(item.confidence for item in matched), 2)
        signals.append(
            TechnicalSignal(
                id=str(uuid.uuid4()),
                signal_type=signal_type,
                label=label,
                confidence=confidence,
                evidence_ids=[item.id for item in matched],
            )
        )
    signals.sort(key=lambda item: item.confidence, reverse=True)
    return signals


def strongest_problem(signals: list[TechnicalSignal]) -> TechnicalSignal | None:
    problems = [item for item in signals if item.signal_type in PROBLEM_SIGNAL_TYPES]
    if not problems:
        return None
    return max(problems, key=lambda item: (len(item.evidence_ids), item.confidence))
