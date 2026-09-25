"""Map evidence onto Redis use cases without forcing a positive fit."""

import uuid

from app.domain.models import Evidence, Opportunity, RedisRelevance

_ORDER = {
    "strongly_supported": 4,
    "plausible": 3,
    "competing_solution_likely": 2,
    "insufficient_information": 1,
    "not_relevant": 0,
}


class UseCase:
    def __init__(
        self,
        use_case_id: str,
        name: str,
        summary: str,
        problem_topics: frozenset[str],
        strong_topics: frozenset[str],
        alternatives: list[str],
        alternative_topics: frozenset[str],
        falsifier: str,
    ) -> None:
        self.use_case_id = use_case_id
        self.name = name
        self.summary = summary
        self.problem_topics = problem_topics
        self.strong_topics = strong_topics
        self.alternatives = alternatives
        self.alternative_topics = alternative_topics
        self.falsifier = falsifier


CATALOG: tuple[UseCase, ...] = (
    UseCase(
        "low_latency_cache",
        "Low-latency cache for interactive retrieval",
        "A low-latency cache could sit on an interactive retrieval path. Public sources do not say one is missing.",
        frozenset({"low_latency", "caching", "distributed_systems", "ai_search"}),
        frozenset({"low_latency", "caching"}),
        ["Memcached", "in-process cache", "CDN"],
        frozenset({"memcached"}),
        "False if interactive search already meets its latency target without a separate serving cache, "
        "or if platform engineering does not own that path.",
    ),
    UseCase(
        "vector_search",
        "In-memory vector search for RAG",
        "Redis vector search can serve embedding similarity. A named incumbent store argues against displacement.",
        frozenset({"rag", "retrieval"}),
        frozenset({"rag"}),
        ["pgvector", "PostgreSQL", "Pinecone", "Milvus", "FAISS", "Weaviate", "Elasticsearch"],
        frozenset({"incumbent_stack"}),
        "False if production retrieval stays on the documented store, or if recall is the only requirement.",
    ),
    UseCase(
        "semantic_cache",
        "Semantic cache for repeated model queries",
        "A semantic cache matters only when sources describe repeated model queries.",
        frozenset({"semantic_cache"}),
        frozenset({"semantic_cache"}),
        ["in-application cache", "gateway cache"],
        frozenset(),
        "False if query repetition is low or caching is already handled elsewhere.",
    ),
    UseCase(
        "online_feature_store",
        "Online feature serving",
        "An online feature store is plausible only with evidence of online feature lookup, not hiring alone.",
        frozenset({"feature_pipeline"}),
        frozenset({"online_feature_lookup"}),
        ["warehouse feature tables", "in-process feature cache"],
        frozenset(),
        "False if feature pipelines are batch-only or owned outside the researched problem.",
    ),
)


def _relevance(use_case: UseCase, supporting: list[Evidence], competing: list[Evidence]) -> RedisRelevance:
    explicit = [item for item in supporting if "explicit_redis_requirement" in item.topics]
    strong = [item for item in supporting if set(item.topics) & use_case.strong_topics]
    if explicit and not competing:
        return "strongly_supported"
    if competing and use_case.alternative_topics:
        return "competing_solution_likely"
    if strong and not competing:
        return "plausible"
    if supporting:
        return "insufficient_information"
    return "not_relevant"


def map_opportunities(evidence: list[Evidence]) -> list[Opportunity]:
    built: list[Opportunity] = []
    for use_case in CATALOG:
        supporting = [
            item
            for item in evidence
            if set(item.topics) & use_case.problem_topics and not item.contradicts_redis
        ]
        competing = [
            item
            for item in evidence
            if set(item.topics) & use_case.alternative_topics or (
                item.contradicts_redis and bool(set(item.topics) & use_case.problem_topics)
            )
        ]
        relevance = _relevance(use_case, supporting, competing)
        gaps = [item.excerpt for item in evidence if item.is_explicit_gap]
        unknowns = list(dict.fromkeys(gaps))
        unknowns.append("No public source states a production SLO, budget, or decision owner.")
        unknowns.append("Technical relevance is not buying intent.")
        built.append(
            Opportunity(
                id=str(uuid.uuid4()),
                use_case_id=use_case.use_case_id,
                name=use_case.name,
                relevance=relevance,
                hypothesis=use_case.summary,
                falsifier=use_case.falsifier,
                alternatives=list(use_case.alternatives),
                unknowns=unknowns,
                supporting_evidence_ids=[item.id for item in supporting],
                contradicting_evidence_ids=[item.id for item in competing],
                forced_positive=False,
            )
        )
    primary = _choose_primary(built)
    if primary is not None:
        for item in built:
            item.is_primary = item.id == primary.id
    return built


def _choose_primary(opportunities: list[Opportunity]) -> Opportunity | None:
    """Prefer a non-forced plausible or strongly supported case. Do not promote a competitor."""
    ranked = sorted(
        opportunities,
        key=lambda item: (_ORDER[item.relevance], len(item.supporting_evidence_ids)),
        reverse=True,
    )
    for item in ranked:
        if item.relevance in {"strongly_supported", "plausible"}:
            return item
    return ranked[0] if ranked else None
