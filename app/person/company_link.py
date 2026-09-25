"""Link a person to the target company. A link is not current employment or ownership."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_ROLE = re.compile(
    r"\b(Director|Head of|VP|Vice President|Staff|Principal|Engineer|Manager|Architect|Founder)\b",
    re.I,
)
_HISTORICAL = re.compile(r"\b(formerly|previously|left|no longer|ex-)\b", re.I)
_AUTHOR = re.compile(r"\b(?:written by|authors?|by)\b\s*:?\s*", re.I)
_INTERVIEW = re.compile(r"\b(interview(?:ed|ing)?|hosting|in conversation with)\b", re.I)


@dataclass(frozen=True)
class CompanyLink:
    associated: bool
    strength: str
    path: str
    relationship: str
    reason: str


def source_kind(url: str, source_type: str) -> str:
    """Map a URL to an explicit association source."""
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path.lower()
    kind = source_type.lower()
    if kind == "search_snippet" or "search_snippet" in kind:
        return "SEARCH_RESULT"
    if "github.com" in host:
        return "GITHUB"
    if any(token in path for token in ("/speaker", "/speakers")) or kind == "speaker_metadata":
        return "SPEAKER_PAGE"
    if any(token in path for token in ("/conference", "/talk", "/agenda")) or kind == "conference":
        return "CONFERENCE"
    if "interview" in path or kind == "interview":
        return "INTERVIEW"
    if any(token in path for token in ("/career", "/jobs", "/job")) or kind == "job_posting":
        return "JOB_POSTING"
    if any(token in path for token in ("/blog", "/engineering")):
        return "ENGINEERING_ARTICLE"
    return "COMPANY_PAGE"


def official_host(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    root = domain.lower().removeprefix("www.")
    if not host or not root:
        return False
    return host == root or host.endswith("." + root)


def link_person(
    name: str,
    context: str,
    company: str,
    *,
    source_url: str = "",
    source_type: str = "",
    domain: str = "",
    evidence_kind: str = "",
) -> CompanyLink:
    """Return whether this person has a credible association with the target company."""
    kind = source_kind(source_url, evidence_kind or source_type)
    text = context or ""
    official = official_host(source_url, domain)
    window = _near(text, name)
    historical = bool(_HISTORICAL.search(window))
    if _explicit_works_at(name, window, company):
        relationship = "historical_employee" if historical else ""
        return CompanyLink(True, "strong", "explicit_text", relationship, "explicit works_at")
    if _separate_blocks(text, name, company):
        relationship = "speaker" if kind in {"SPEAKER_PAGE", "CONFERENCE"} else ""
        return CompanyLink(True, "strong", "speaker_card", relationship, "role and company in nearby blocks")
    if evidence_kind in {"json_ld", "author_metadata"} and _metadata_links(text, name, company, official):
        return CompanyLink(True, "strong", "structured_metadata", "author", "structured author or worksFor")
    if official and _author_identified(name, text, source_url):
        return CompanyLink(True, "strong", "page_context", "author", "author on the company domain")
    if kind == "SPEAKER_PAGE" and company.lower() in window.lower():
        return CompanyLink(True, "strong", "speaker_card", "speaker", "speaker card names the company")
    if kind == "INTERVIEW" and company.lower() in window.lower():
        relationship = "historical_employee" if historical else "interviewee"
        return CompanyLink(True, "strong", "explicit_text", relationship, "interview names the company")
    if kind == "SEARCH_RESULT" and _snippet_link(name, text, company):
        return CompanyLink(True, "probable", "search_snippet", "", "search snippet names the company")
    if kind == "GITHUB" and _github_org(source_url, company) and name.lower() in text.lower():
        return CompanyLink(True, "probable", "github", "", "named contributor on the company GitHub org")
    if kind in {"CONFERENCE", "SPEAKER_PAGE"} and not official:
        return CompanyLink(False, "none", "", "external_person", "external speaker without company association")
    if company.lower() in text.lower() and name.lower() in text.lower():
        return CompanyLink(False, "none", "", "external_person", "mentioned without employment or authorship")
    return CompanyLink(False, "none", "", "", "no company association")


def _explicit_works_at(name: str, window: str, company: str) -> bool:
    line = next((item for item in window.splitlines() if name.lower() in item.lower()), window)
    if company.lower() not in line.lower():
        return False
    if re.search(rf"\bat\s+{re.escape(company)}\b", line, re.I):
        return True
    return bool(_ROLE.search(line))


def _separate_blocks(text: str, name: str, company: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if name.lower() not in line.lower():
            continue
        block = " ".join(lines[index : index + 4])
        if company.lower() in block.lower() and _ROLE.search(block):
            return True
    return False


def _metadata_links(text: str, name: str, company: str, official: bool) -> bool:
    if name.lower() not in text.lower() and not text.lower().startswith("author"):
        return False
    if "worksfor" in text.lower() and company.lower() in text.lower():
        return True
    return official and (_AUTHOR.search(text) is not None or name.lower() in text.lower())


def _author_identified(name: str, text: str, url: str) -> bool:
    if _AUTHOR.search(text) and name.lower() in text.lower():
        return True
    slug = name.lower().replace(" ", "-")
    if "/author/" in url.lower() and slug in url.lower():
        return True
    stripped = text.strip()
    return stripped.lower().startswith(name.lower())


def _snippet_link(name: str, text: str, company: str) -> bool:
    if name.lower() not in text.lower() or company.lower() not in text.lower():
        return False
    return bool(re.search(rf"{re.escape(name)}\s*[|—–-]\s*.{{0,60}}{re.escape(company)}", text, re.I))


def _github_org(url: str, company: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if "github.com" not in host:
        return False
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        return False
    org = parts[0].lower()
    account = re.sub(r"[^a-z0-9]", "", company.lower())
    return account in org or org in account


def linked_page_people(
    text: str,
    url: str,
    source_type: str,
    company: str,
    domain: str,
) -> list[tuple[str, str, str]]:
    """Persons on a fetched page who link to the company. Current role is not required."""
    from app.person.qualify import explain_qualification

    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for chunk in _chunks(text):
        from app.person.qualify import _spans

        for label, name, _score in _spans(chunk):
            if label != "PERSON" or len(name.split()) < 2 or name.lower() in seen:
                continue
            seen.add(name.lower())
            qualified, _reason = explain_qualification(
                name,
                chunk,
                company,
                source_url=url,
                source_type=source_type,
                domain=domain,
            )
            if qualified is None:
                continue
            found.append((name, qualified.context, qualified.relationship))
    return found


def _chunks(text: str) -> list[str]:
    chunks = [text[:1800]]
    for match in re.finditer(r"\b(?:Author|Authors|Written by|By|Speaker)\b", text):
        chunks.append(text[max(0, match.start() - 40) : match.start() + 500])
    return chunks


def _near(text: str, name: str) -> str:
    idx = text.lower().find(name.lower())
    if idx < 0:
        return text[:500]
    return text[max(0, idx - 80) : idx + len(name) + 220]
