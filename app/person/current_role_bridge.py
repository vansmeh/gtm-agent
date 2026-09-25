"""Resolve current employer and current role before ownership.

A search snippet or a bio can name a role. Neither one proves ownership.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict

from app.domain.models import Evidence, RoleHistoryEntry


class _Span(TypedDict):
    title: str
    company: str
    source: str
    date: date | None
    confidence: float
    evidence_id: str
    kind: str
    excerpt: str

_STRONG_DAYS = 183
_ACCEPTABLE_DAYS = 365
_AGING_DAYS = 730
_FUNCTION_TITLES = (
    ("platform", ("platform engineering", "director of platform", "head of platform", "platform architect")),
    ("infrastructure", ("infrastructure engineering", "director of infrastructure", "head of infrastructure")),
    ("search", ("search engineering", "director of search", "head of search")),
)
_GENERIC = ("staff engineer", "senior engineer", "software engineer", "engineer")


@dataclass
class RoleResolution:
    employer: str = ""
    title: str = ""
    role_state: str = "unknown"
    source: str = ""
    as_of: date | None = None
    confidence: float = 0.0
    history: list[RoleHistoryEntry] = field(default_factory=list)
    function: str = ""
    function_level: str = "unknown"
    function_source: str = ""
    evidence_ids: list[str] = field(default_factory=list)


def source_queries(name: str, company: str, domain: str) -> list[str]:
    """Find a public page. The snippet does not have to contain the title."""
    host = domain or company
    return [
        f'"{name}" "{company}" official',
        f'"{name}" "{company}" engineering',
        f'site:{host} "{name}"',
        f'site:{host} "{name}" engineer',
        f'site:{host} "{name}" platform',
        f'site:{host} "{name}" infrastructure',
        f'site:{host} "{name}" architecture',
        f'"{name}" "{company}" speaker',
        f'"{name}" "{company}" conference',
        f'"{name}" "{company}" GitHub',
    ]


def role_queries(name: str, company: str, domain: str = "") -> list[str]:
    return source_queries(name, company, domain or company)


def source_rank(url: str, domain: str) -> int:
    """Lower is a better verification source. LinkedIn is never fetched."""
    lowered = url.lower()
    if "linkedin.com" in lowered:
        return 100
    path = lowered.split("?", 1)[0]
    on_domain = bool(domain) and domain.lower() in lowered
    if on_domain and any(part in path for part in ("/team", "/about", "/leadership", "/people", "/bio")):
        return 1
    if on_domain and "author" in path:
        return 2
    if on_domain and any(part in path for part in ("/blog", "/engineering")):
        return 3
    if on_domain and "/news" in path:
        return 4
    if any(part in path for part in ("/speaker", "/speakers", "/conference", "/talk")):
        return 5
    if "interview" in path:
        return 6
    if "github.com" in lowered:
        return 7
    if on_domain:
        return 8
    return 9


def employer_queries(name: str, company: str) -> list[str]:
    return [
        f'"{name}" "{company}"',
        f'"{name}" new company',
        f'"{name}" joined',
        f'"{name}" "formerly at"',
    ]


def same_person(
    left_name: str,
    right_name: str,
    *,
    left_company: str,
    right_company: str,
    left_topics: list[str],
    right_topics: list[str],
) -> bool:
    """Exact name plus employer or technical continuity. Common names stay split."""
    if left_name.strip().lower() != right_name.strip().lower():
        return False
    if not left_company or not right_company:
        return False
    if left_company.strip().lower() == right_company.strip().lower():
        return True
    shared = {topic.lower() for topic in left_topics} & {topic.lower() for topic in right_topics}
    return bool(shared)


def resolve_role_bridge(
    name: str,
    evidence: list[Evidence],
    *,
    account_name: str,
    observed_on: date,
) -> RoleResolution:
    spans: list[_Span] = []
    for item in evidence:
        span = _span(item, name, account_name)
        if span is not None:
            spans.append(span)
    history = [
        RoleHistoryEntry(
            title=span["title"],
            company=span["company"],
            source=span["source"],
            role_date=span["date"] if isinstance(span["date"], date) else None,
            confidence=span["confidence"],
        )
        for span in spans
    ]
    result = RoleResolution(history=history, employer=account_name)
    if not spans:
        return result
    target = [span for span in spans if span["company"].lower() == account_name.lower()]
    elsewhere = [span for span in spans if span not in target and _left_target(span["excerpt"], account_name)]
    newest_elsewhere = _newest(elsewhere)
    newest_target = _newest(target)
    if (
        newest_elsewhere is not None
        and newest_target is not None
        and _newer(newest_elsewhere["date"], newest_target["date"])
    ):
        result.employer = newest_elsewhere["company"]
        result.title = newest_target["title"]
        result.role_state = "historical"
        result.source = newest_target["source"]
        result.as_of = newest_target["date"]
        result.confidence = newest_target["confidence"]
        result.evidence_ids = [newest_target["evidence_id"]]
        return result
    chosen = newest_target or _newest(spans)
    if chosen is None or chosen["company"].lower() != account_name.lower():
        if chosen is not None and chosen["company"].lower() != account_name.lower():
            result.employer = chosen["company"]
            result.role_state = "unknown"
        return result
    result.employer = account_name
    result.title = chosen["title"]
    result.source = chosen["source"]
    result.as_of = chosen["date"]
    result.confidence = chosen["confidence"]
    result.evidence_ids = [chosen["evidence_id"]]
    result.role_state = _state(chosen, target, observed_on)
    result.function, result.function_level, result.function_source = function_from_role(chosen["title"])
    page_titles = {
        span["title"].lower()
        for span in target
        if span["kind"] != "search_snippet"
        and span["title"] != "changed employer"
        and _band(span["date"] if isinstance(span["date"], date) else None, observed_on) != "historical"
    }
    if len(page_titles) > 1:
        result.role_state = "unknown"
        result.confidence = min(result.confidence, 0.3)
        return result
    pages = [
        span
        for span in target
        if span["kind"] != "search_snippet" and span["title"].lower() == chosen["title"].lower()
    ]
    hosts = {span["source"].split("/")[2].lower() for span in pages if span["source"].count("/") >= 2}
    if len(hosts) >= 2 and result.role_state != "historical":
        result.confidence = max(result.confidence, 0.85)
        result.role_state = "current"
    if chosen["kind"] == "search_snippet" and len(pages) == 0:
        result.role_state = "probable_current" if result.role_state != "historical" else "historical"
        result.confidence = min(result.confidence, 0.45)
    return result


def function_from_role(title: str) -> tuple[str, str, str]:
    """A specific function title is function evidence. Generic seniority is not."""
    lowered = title.lower()
    for function, phrases in _FUNCTION_TITLES:
        if any(phrase in lowered for phrase in phrases):
            return function, "strong", "role"
    if any(token in lowered for token in _GENERIC) and not any(
        word in lowered for word in ("platform", "infrastructure", "search")
    ):
        return "", "unknown", ""
    return "", "unknown", ""


def _span(item: Evidence, name: str, account_name: str) -> _Span | None:
    text = item.excerpt
    if name not in text:
        return None
    company = _company(text, item, account_name)
    title = _title(text, name)
    if not title and ("joined " in text.lower() or "formerly" in text.lower()):
        title = "changed employer"
    if not title or not company:
        return None
    if company.lower() != account_name.lower() and account_name.lower() not in text.lower():
        if not _left_target(text, account_name) and "formerly" not in text.lower():
            return None
    kind = _source_kind(item)
    if kind == "":
        return None
    return {
        "title": title,
        "company": company,
        "source": item.source_url or kind,
        "date": item.published_at,
        "confidence": _confidence(kind, item.published_at),
        "evidence_id": item.id,
        "kind": kind,
        "excerpt": text,
    }


def _company(text: str, item: Evidence, account_name: str) -> str:
    lowered = text.lower()
    if "joined " in lowered:
        joined = lowered.split("joined", 1)[1].split("formerly")[0]
        if account_name.lower() not in joined:
            token = joined.strip(" .,").split(" in ")[0].strip()
            return " ".join(token.split()[:3]).title()
    if account_name.lower() in lowered or account_name.lower() in item.source_url.lower():
        return account_name
    return ""


def _has_role_word(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ("director", "head", "vp", "engineer", "manager", "architect"))


def _title(text: str, name: str) -> str:
    if not name:
        return ""
    tail = text.split(name, 1)[-1].strip(" ,:|-")
    for marker in (" at ", " — ", " - "):
        if marker in tail:
            tail = tail.split(marker, 1)[0]
    title = " ".join(tail.split())[:80].strip(" .")
    words = (
        "director",
        "head",
        "vp",
        "vice president",
        "staff",
        "principal",
        "engineer",
        "manager",
        "architect",
    )
    if not any(word in title.lower() for word in words):
        return ""
    return title


def _source_kind(item: Evidence) -> str:
    if item.source_type == "search_snippet" or item.evidence_type == "search_snippet":
        return "search_snippet"
    if item.evidence_type == "speaker_metadata" or "speaker" in item.source_url.lower():
        return "speaker_bio"
    if item.evidence_type == "interviewee" or item.source_type == "interview":
        return "interview"
    if "github.com" in item.source_url:
        return "github"
    if item.source_type in {"company_news", "biography"} or "/team" in item.source_url or "/news" in item.source_url:
        return "company_page"
    if item.evidence_type in {"author_metadata", "json_ld"} and _has_role_word(item.excerpt):
        return "author_bio"
    if item.source_type in {"engineering_blog", "blog", "technical_article"} and _has_role_word(item.excerpt):
        return "engineering_artifact"
    return ""


def _confidence(kind: str, published: date | None) -> float:
    base = {
        "company_page": 0.8,
        "author_bio": 0.75,
        "speaker_bio": 0.7,
        "engineering_artifact": 0.7,
        "interview": 0.6,
        "github": 0.55,
        "search_snippet": 0.45,
    }.get(kind, 0.4)
    if published is None and kind == "search_snippet":
        return base
    return base


def _state(chosen: _Span, target: list[_Span], observed_on: date) -> str:
    published = chosen["date"]
    kind = str(chosen["kind"])
    band = _band(published if isinstance(published, date) else None, observed_on)
    if band == "historical":
        return "historical"
    if band == "aging":
        return "probable_current" if len(target) >= 2 else "historical"
    if kind == "search_snippet":
        return "probable_current"
    if kind in {"company_page", "author_bio", "engineering_artifact", "speaker_bio", "interview", "github"}:
        return "current"
    return "probable_current"


def _band(published: date | None, observed_on: date) -> str:
    if published is None:
        return "acceptable"
    days = (observed_on - published).days
    if days <= _STRONG_DAYS:
        return "strong"
    if days <= _ACCEPTABLE_DAYS:
        return "acceptable"
    if days <= _AGING_DAYS:
        return "aging"
    return "historical"


def _left_target(text: str, account_name: str) -> bool:
    text = text.lower()
    joined = text.split("joined", 1)[-1].split("formerly")[0] if "joined" in text else ""
    return "formerly" in text or ("joined" in text and account_name.lower() not in joined)


def _newest(spans: list[_Span]) -> _Span | None:
    if not spans:
        return None
    return max(spans, key=lambda span: span["date"] or date.min)


def _newer(left: object, right: object) -> bool:
    if not isinstance(left, date):
        return False
    if not isinstance(right, date):
        return True
    return left > right
