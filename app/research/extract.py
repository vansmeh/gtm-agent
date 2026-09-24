"""Turn fetched pages into sourced evidence. Poisoned pages yield no claims."""

import hashlib
import re
import uuid

from app.domain.models import Evidence, Observation
from app.research.fetch import FetchedPage
from app.security import document_is_poisoned, split_sentences

_SOURCE_PRIOR = {
    "engineering_blog": 0.78,
    "job_posting": 0.72,
    "blog": 0.66,
    "personal_technical_writing": 0.62,
    "company_news": 0.55,
    "untrusted_web": 0.35,
}

_PROBLEM_TOPICS = frozenset(
    {"ai_search", "rag", "low_latency", "distributed_systems", "caching", "retrieval", "feature_pipeline"}
)
_INCUMBENT = re.compile(
    r"\b(pgvector|pinecone|weaviate|milvus|faiss|elasticsearch|opensearch|memcached)\b",
    re.I,
)
_GAP = re.compile(r"\bdoes not\b", re.I)

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ai_search", re.compile(r"\blaunch(?:ed|ing)?\b", re.I)),
    ("rag", re.compile(r"retrieval-augmented generation|\bRAG\b", re.I)),
    ("low_latency", re.compile(r"low[- ]latency|tail latency", re.I)),
    ("distributed_systems", re.compile(r"distributed systems", re.I)),
    ("caching", re.compile(r"\bcach(?:e|ing)\b", re.I)),
    ("retrieval", re.compile(r"\bretrieval\b", re.I)),
    ("hiring_platform", re.compile(r"hiring a Platform Engineer", re.I)),
    ("hiring_ml", re.compile(r"hiring an ML Infrastructure", re.I)),
    ("ownership_platform", re.compile(r"platform engineering.{0,80}(owns|responsible)", re.I)),
    ("reports_platform", re.compile(r"reports to the Head of Platform Engineering", re.I)),
    ("feature_pipeline", re.compile(r"feature pipelines", re.I)),
    ("person_mention", re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+,\s+(?:Head of|VP|Vice President|Director of)\b")),
)


def classify_sentence(sentence: str) -> tuple[list[str], bool, bool, bool]:
    topics = [name for name, pattern in _RULES if pattern.search(sentence)]
    if "ai_search" in topics and not re.search(r"\bsearch\b", sentence, re.I):
        topics = [topic for topic in topics if topic != "ai_search"]
    contradicts = _INCUMBENT.search(sentence) is not None
    if contradicts and "incumbent_stack" not in topics:
        topics.append("incumbent_stack")
    gap = _GAP.search(sentence) is not None
    if gap and "explicit_gap" not in topics:
        topics.append("explicit_gap")
    supports = bool(set(topics) & _PROBLEM_TOPICS) or "ai_search" in topics
    return topics, supports, contradicts, gap


def observation_from_page(page: FetchedPage, *, observed_at: object, cycle: int) -> Observation:
    from datetime import datetime

    if not isinstance(observed_at, datetime):
        raise TypeError("observed_at must be datetime")
    poisoned = document_is_poisoned(page.text)
    sentences = [] if poisoned else split_sentences(page.text)
    sanitized = " ".join(sentences)[:4000]
    digest = hashlib.sha256(page.text.encode("utf-8")).hexdigest()
    return Observation(
        id=str(uuid.uuid4()),
        url=page.url,
        title=page.title,
        source_type=page.source_type,
        published_at=page.published_at,
        observed_at=observed_at,
        text_sha256=digest,
        sanitized_text=sanitized,
        poisoned=poisoned,
        cycle=cycle,
    )


def extract_evidence(observation: Observation) -> list[Evidence]:
    if observation.poisoned or not observation.sanitized_text:
        return []
    prior = _SOURCE_PRIOR.get(observation.source_type, 0.4)
    found: list[Evidence] = []
    seen: set[str] = set()
    for sentence in split_sentences(observation.sanitized_text):
        topics, supports, contradicts, gap = classify_sentence(sentence)
        if not topics:
            continue
        key = f"{observation.url}|{sentence}"
        if key in seen:
            continue
        seen.add(key)
        confidence = min(0.9, prior + 0.03 * max(0, len(topics) - 1))
        found.append(
            Evidence(
                id=str(uuid.uuid4()),
                observation_id=observation.id,
                excerpt=sentence,
                source_url=observation.url,
                source_title=observation.title,
                source_type=observation.source_type,
                published_at=observation.published_at,
                observed_at=observation.observed_at,
                confidence=round(confidence, 2),
                lineage=[
                    f"observation:{observation.id}",
                    "extractor:rules",
                    f"document:{observation.url}",
                ],
                topics=topics,
                supports_problem=supports,
                contradicts_redis=contradicts,
                is_explicit_gap=gap,
            )
        )
    return found
