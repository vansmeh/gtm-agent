"""Read author and role claims from page metadata and search snippets.

A metadata field is evidence for the claim it states. It is not ownership.
"""

import json
import re
from datetime import datetime

from app.domain.models import Evidence, StructuredFact
from app.person.entity import classify_entity

_NAME = r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})"
_ROLE = r"(Director|Head|VP|Vice President|Staff|Principal|Engineer|Manager|Architect)[^|]{0,60}"
_PIPE = re.compile(rf"{_NAME}\s*[|—–-]\s*({_ROLE})\s*[|—–-]\s*([A-Za-z][^|]{{1,40}})")
_AT = re.compile(rf"{_NAME},\s+({_ROLE})\s+at\s+([A-Z][A-Za-z0-9 ]{{1,40}})")


def extract_structured(html: str, url: str) -> list[StructuredFact]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    facts: list[StructuredFact] = []
    for node in soup.find_all("meta"):
        key = str(node.get("name") or node.get("property") or "").lower()
        content = str(node.get("content") or "").strip()
        if not content:
            continue
        if key in {"author", "article:author", "og:article:author"}:
            facts.extend(_person_fact(url, "author_metadata", key, content, 0.75))
        elif key in {"speaker", "article:speaker"}:
            facts.extend(_person_fact(url, "speaker_metadata", key, content, 0.7))
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        facts.extend(_json_ld(script.get_text(" ", strip=True), url))
    for node in soup.select(".byline, .author, .bio, .speaker, .team-member, .member-card"):
        text = " ".join(node.get_text(" ", strip=True).split())[:240]
        field = "team_member" if "member" in " ".join(node.get("class") or []) else "bio"
        facts.extend(_person_fact(url, "visible_block", field, text, 0.6))
    for node in soup.select("[itemtype*='BreadcrumbList'] [itemprop='name']"):
        label = node.get_text(" ", strip=True)
        if label:
            facts.append(
                StructuredFact(
                    evidence_type="breadcrumb",
                    source_url=url,
                    field="breadcrumb",
                    value=label[:80],
                    raw_text=label[:240],
                    confidence=0.3,
                    sentence="",
                )
            )
    return mark_contradictions(dedupe_facts(facts))


def snippet_role_facts(
    *,
    title: str,
    snippet: str,
    url: str,
    account_name: str,
    observed_at: datetime,
    provider: str = "",
    query: str = "",
) -> list[Evidence]:
    """A snippet that states name, title, and company is probable role evidence only."""
    text = f"{title} {snippet}"
    account = account_name.lower()
    found: list[Evidence] = []
    for pattern in (_PIPE, _AT):
        match = pattern.search(text)
        if match is None:
            continue
        name, title_text, company = match.group(1), match.group(2).strip(), match.group(3).strip()
        if account not in company.lower() and account not in text.lower():
            continue
        if classify_entity(name, text) != "PERSON" and classify_entity(name, f"{name}, {title_text}") != "PERSON":
            if classify_entity(name, text) in {"ORG", "PRODUCT", "TITLE", "DOCUMENT"}:
                continue
        sentence = f"{name}, {title_text} at {company}."
        found.append(
            Evidence(
                id=f"snippet:{url}:{name}",
                observation_id="snippet",
                excerpt=sentence,
                source_url=url,
                source_title=title,
                source_type="search_snippet",
                published_at=None,
                observed_at=observed_at,
                confidence=0.45,
                lineage=_snippet_lineage(provider, query),
                topics=[],
                supports_problem=False,
                contradicts_redis=False,
                is_explicit_gap=False,
                evidence_type="search_snippet",
                field="current_role",
                value=title_text,
                raw_text=text[:240],
            )
        )
    return found


def dedupe_facts(facts: list[StructuredFact]) -> list[StructuredFact]:
    """Identical metadata copied across hosts is one claim."""
    kept: list[StructuredFact] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        key = (fact.field, fact.value.lower())
        if fact.field != "breadcrumb" and key in seen:
            continue
        seen.add(key)
        kept.append(fact)
    return kept


def mark_contradictions(facts: list[StructuredFact]) -> list[StructuredFact]:
    authors = [fact for fact in facts if fact.field in {"author", "article:author", "og:article:author"}]
    names = {fact.value.lower() for fact in authors}
    if len(names) < 2:
        return facts
    lowered: list[StructuredFact] = []
    for fact in facts:
        if fact in authors:
            lowered.append(fact.model_copy(update={"confidence": round(fact.confidence * 0.5, 2)}))
        else:
            lowered.append(fact)
    return lowered


def evidence_from_facts(facts: list[StructuredFact], *, observed_at: datetime, observation_id: str) -> list[Evidence]:
    rows: list[Evidence] = []
    for fact in facts:
        if not fact.sentence:
            continue
        rows.append(
            Evidence(
                id=f"meta:{fact.source_url}:{fact.field}:{fact.value}"[:180],
                observation_id=observation_id,
                excerpt=fact.sentence,
                source_url=fact.source_url,
                source_title=fact.field,
                source_type="structured_metadata",
                published_at=None,
                observed_at=observed_at,
                confidence=fact.confidence,
                lineage=[f"field:{fact.field}"],
                topics=[],
                supports_problem=False,
                contradicts_redis=False,
                is_explicit_gap=False,
                evidence_type=fact.evidence_type,
                field=fact.field,
                value=fact.value,
                raw_text=fact.raw_text,
            )
        )
    return rows


def _person_fact(url: str, evidence_type: str, field: str, raw: str, confidence: float) -> list[StructuredFact]:
    name = _clean_name(raw)
    if not name or classify_entity(name, raw) in {"ORG", "PRODUCT", "TITLE", "DOCUMENT"}:
        return []
    sentence = f"Author: {name}." if "author" in field or field == "bio" else f"Speaker: {name}."
    if field == "team_member":
        sentence = raw if name in raw else f"{name} is listed on the team page."
    return [
        StructuredFact(
            evidence_type=evidence_type,
            source_url=url,
            field=field,
            value=name,
            raw_text=raw[:240],
            confidence=confidence,
            sentence=sentence,
        )
    ]


def _json_ld(raw: str, url: str) -> list[StructuredFact]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    nodes = payload if isinstance(payload, list) else [payload]
    facts: list[StructuredFact] = []
    for node in nodes:
        if isinstance(node, dict) and "@graph" in node and isinstance(node["@graph"], list):
            nodes.extend(item for item in node["@graph"] if isinstance(item, dict))
        if not isinstance(node, dict):
            continue
        kind = str(node.get("@type", ""))
        if "Person" in kind:
            facts.extend(_person_node(node, url))
        author = node.get("author")
        if isinstance(author, dict):
            facts.extend(_person_node(author, url))
        elif isinstance(author, str):
            facts.extend(_person_fact(url, "json_ld", "author", author, 0.8))
        speaker = node.get("performer") or node.get("speaker")
        if isinstance(speaker, dict):
            facts.extend(_person_fact(url, "speaker_metadata", "speaker", str(speaker.get("name", "")), 0.7))
    return facts


def _person_node(node: dict[str, object], url: str) -> list[StructuredFact]:
    name = str(node.get("name", "")).strip()
    title = str(node.get("jobTitle", "")).strip()
    works = node.get("worksFor")
    company = ""
    if isinstance(works, dict):
        company = str(works.get("name", ""))
    elif isinstance(works, str):
        company = works
    if not name:
        return []
    raw = name if not title else f"{name}, {title}" + (f" at {company}" if company else "")
    facts = _person_fact(url, "json_ld", "author", name, 0.8)
    if title and facts:
        sentence = f"{name}, {title} at {company or 'the company'}."
        facts[0] = facts[0].model_copy(update={"sentence": sentence, "raw_text": raw})
    return facts


def _snippet_lineage(provider: str, query: str) -> list[str]:
    lineage = ["search_snippet"]
    if provider:
        lineage.append(f"provider:{provider}")
    if query:
        lineage.append(f"query:{query}")
    return lineage


def _clean_name(raw: str) -> str:
    match = re.search(_NAME, raw)
    return match.group(1) if match else ""
