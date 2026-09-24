"""Attribute a document to a person only when the text says who wrote or spoke it."""

import re
import uuid
from dataclasses import dataclass
from datetime import date

from app.domain.models import ArtifactPersonLink, Evidence, TechnicalArtifact
from app.person.entity import classify_entity

_NAME = r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})"
_AUTHOR = re.compile(rf"\b(?:By|Written by|Author)\s*:?\s+{_NAME}\b")
_SPEAKER = re.compile(rf"\b(?:Speaker|Presented by|Talk by)\s*:?\s+{_NAME}\b")
_CONTRIBUTOR = re.compile(rf"\b(?:Contributor|Contributed by|Authored by)\s*:?\s+{_NAME}\b")
_INTERVIEW = re.compile(rf"\b(?:Interview with|Interviewee)\s*:?\s+{_NAME}\b")
_PROSE = re.compile(rf"\b{_NAME}\s+(?:wrote|presented|authored)\b")
_MENTION = re.compile(rf"\b{_NAME}\b")
_STRONG = frozenset({"author", "speaker", "contributor"})


@dataclass
class ResolvedPerson:
    person_id: str
    name: str
    company: str
    source_urls: list[str]
    source_types: list[str]
    identity_confidence: float


def attributions_in(text: str, url: str) -> list[tuple[str, str]]:
    """Return (name, relationship). A URL slug is not authorship."""
    del url
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for relationship, pattern in (
        ("author", _AUTHOR),
        ("speaker", _SPEAKER),
        ("contributor", _CONTRIBUTOR),
        ("interviewee", _INTERVIEW),
        ("author", _PROSE),
    ):
        for match in pattern.finditer(text):
            name = match.group(1)
            if name.lower() in seen or classify_entity(name, text) in {"ORG", "PRODUCT", "TITLE", "DOCUMENT"}:
                continue
            seen.add(name.lower())
            found.append((name, relationship))
    for match in _MENTION.finditer(text):
        name = match.group(1)
        kind = classify_entity(name, text)
        if name.lower() in seen or kind in {"ORG", "PRODUCT", "TITLE", "DOCUMENT"}:
            continue
        if kind == "UNKNOWN" and not _person_shaped(name):
            continue
        seen.add(name.lower())
        found.append((name, "mentioned_person"))
    return found


def _person_shaped(name: str) -> bool:
    parts = name.split()
    return len(parts) == 2 and all(part[:1].isupper() and part[1:].islower() for part in parts)


def strengthens_expertise(relationship: str) -> bool:
    return relationship in _STRONG


def source_quality(url: str, domain: str, source_type: str) -> str:
    host = urlparse_host(url)
    official = bool(domain) and (host == domain.lower() or host.endswith("." + domain.lower()))
    if official and source_type in {
        "engineering_blog",
        "technical_article",
        "architecture_post",
        "incident_postmortem",
        "documentation",
        "blog",
    }:
        return "tier_1"
    if source_type in {"conference_talk", "conference_bio", "interview", "conference"}:
        return "tier_2"
    if "github.com" in host:
        return "tier_3"
    if official:
        return "tier_1"
    if any(part in host for part in ("infoq.com", "leaddev.com", "acm.org", "ieee.org")):
        return "tier_4"
    return "tier_5"


def resolve_identities(
    rows: list[tuple[str, str, str, str]],
) -> list[ResolvedPerson]:
    """rows are (name, company, url, source_type). Same name without corroboration stays split."""
    groups: list[ResolvedPerson] = []
    for name, company, url, source_type in rows:
        match = next(
            (
                person
                for person in groups
                if person.name.lower() == name.lower()
                and person.company.lower() == company.lower()
                and _corroborated(person, url)
            ),
            None,
        )
        if match is None:
            groups.append(
                ResolvedPerson(
                    person_id=str(uuid.uuid4()),
                    name=name,
                    company=company,
                    source_urls=[url],
                    source_types=[source_type],
                    identity_confidence=0.45,
                )
            )
            continue
        if url not in match.source_urls:
            match.source_urls.append(url)
        if source_type not in match.source_types:
            match.source_types.append(source_type)
        match.identity_confidence = min(0.9, 0.45 + 0.2 * (len(match.source_urls) - 1))
    return groups


def build_artifacts(
    evidence: list[Evidence],
    *,
    account_name: str,
    domain: str,
) -> tuple[list[TechnicalArtifact], list[ArtifactPersonLink]]:
    artifacts: list[TechnicalArtifact] = []
    links: list[ArtifactPersonLink] = []
    people = resolve_identities(
        [
            (name, account_name, item.source_url, item.source_type)
            for item in evidence
            if _about_company(item, account_name, domain)
            for name, _rel in attributions_in(item.excerpt, item.source_url)
        ]
    )
    by_name = {person.name.lower(): person for person in people}
    for item in evidence:
        if not _about_company(item, account_name, domain):
            continue
        named = attributions_in(item.excerpt, item.source_url)
        if not named:
            continue
        artifact_id = item.id
        author = next((name for name, rel in named if rel in _STRONG), "")
        person = by_name.get(author.lower()) if author else None
        artifacts.append(
            TechnicalArtifact(
                id=artifact_id,
                source_url=item.source_url,
                url=item.source_url,
                title=item.source_title,
                topic=item.topics[0] if item.topics else "engineering",
                author=author,
                author_person_id="" if person is None else person.person_id,
                company_id=account_name,
                published_at=item.published_at,
                evidence_id=item.id,
                evidence_ids=[item.id],
                kind=_artifact_kind(item.source_type, item.source_url),
                source_type=item.source_type,
                source_quality=source_quality(item.source_url, domain, item.source_type),
            )
        )
        for name, relationship in named:
            linked = by_name.get(name.lower())
            if linked is None:
                continue
            links.append(
                ArtifactPersonLink(
                    person_id=linked.person_id,
                    person_name=linked.name,
                    artifact_id=artifact_id,
                    relationship=relationship,  # type: ignore[arg-type]
                )
            )
    return artifacts, links


def _about_company(item: Evidence, account_name: str, domain: str) -> bool:
    if account_name.lower() in item.excerpt.lower():
        return True
    host = urlparse_host(item.source_url)
    return bool(domain) and (host == domain.lower() or host.endswith("." + domain.lower()))


def _corroborated(person: ResolvedPerson, url: str) -> bool:
    if url in person.source_urls:
        return True
    return urlparse_host(url) in {urlparse_host(existing) for existing in person.source_urls}


def _artifact_kind(source_type: str, url: str) -> str:
    if "github.com" in url:
        return "github"
    allowed = {
        "engineering_blog",
        "technical_article",
        "conference_talk",
        "conference_bio",
        "interview",
        "github",
        "documentation",
        "architecture_post",
        "incident_postmortem",
        "job_posting",
        "conference",
        "blog",
    }
    if source_type in allowed:
        return "conference_talk" if source_type == "conference" else source_type
    return "technical_article"


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def dated_label(published_at: date | None) -> str:
    return "undated" if published_at is None else published_at.isoformat()
