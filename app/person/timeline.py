"""Role timeline. The oldest source does not erase a newer one."""

from dataclasses import dataclass, field
from datetime import date

from app.domain.models import Evidence

_ROLE_WORDS = ("engineer", "director", "manager", "head of", "architect", "vp", "vice president")


@dataclass
class RoleSpan:
    title: str
    published_at: date | None
    evidence_id: str
    state: str


@dataclass
class RoleTimeline:
    historical: list[RoleSpan] = field(default_factory=list)
    current: RoleSpan | None = None
    transitions: list[str] = field(default_factory=list)
    confidence: float = 0.0


def build_timeline(
    name: str,
    title: str,
    evidence: list[Evidence],
    *,
    observed_on: date,
    role_days: int = 365,
) -> RoleTimeline:
    spans = [
        _span(item, title, observed_on, role_days)
        for item in evidence
        if name in item.excerpt and _is_role(item, title)
    ]
    unique = _drop_syndicated(spans, evidence)
    unique.sort(key=lambda item: item.published_at or date.min)
    timeline = RoleTimeline()
    if not unique:
        return timeline
    newest = unique[-1]
    timeline.historical = [item for item in unique if item.state == "historical" and item is not newest]
    if newest.state in {"current", "probable_current"}:
        timeline.current = newest
        timeline.confidence = 0.8 if newest.state == "current" else 0.55
    else:
        timeline.historical.append(newest)
        timeline.confidence = 0.35
    titles = [item.title for item in unique if item.title]
    pairs = zip(titles, titles[1:], strict=False)
    timeline.transitions = [
        f"{left} -> {right}" for left, right in pairs if left != right
    ]
    return timeline


def indexed_profile_queries(account_name: str, functions: list[str]) -> list[str]:
    """Public profile queries. The pages are not fetched."""
    function = functions[0] if functions else "engineering"
    return [
        f'site:linkedin.com/in "{account_name}" "Director"',
        f'site:linkedin.com/in "{account_name}" "Platform"',
        f'site:linkedin.com/in "{account_name}" "Infrastructure"',
        f'site:linkedin.com/in "{account_name}" "{function}"',
    ]


def team_responsibilities(evidence: list[Evidence], functions: list[str]) -> list[tuple[str, str, str]]:
    """Map a posting to a function. The posting does not name a person."""
    found: list[tuple[str, str, str]] = []
    for item in evidence:
        if item.source_type != "job_posting" and "hiring" not in item.excerpt.lower():
            continue
        text = item.excerpt.lower()
        matched = [function for function in functions if function in text]
        if not matched and "serving" not in text and "platform" not in text:
            continue
        function = matched[0] if matched else "platform"
        found.append((item.excerpt[:80], function, item.id))
    return found


def _span(item: Evidence, title: str, observed_on: date, role_days: int) -> RoleSpan:
    label = title if title and title.lower() in item.excerpt.lower() else _title_from(item.excerpt)
    if item.source_type == "search_snippet":
        state = "probable_current"
    elif item.published_at is not None and (observed_on - item.published_at).days <= role_days:
        state = "current"
    elif item.published_at is None:
        state = "probable_current"
    else:
        state = "historical"
    return RoleSpan(title=label, published_at=item.published_at, evidence_id=item.id, state=state)


def _is_role(item: Evidence, title: str) -> bool:
    text = item.excerpt.lower()
    if title and title.lower() in text:
        return True
    return any(token in text for token in _ROLE_WORDS)


def _title_from(excerpt: str) -> str:
    return " ".join(excerpt.split())[:80]


def _drop_syndicated(spans: list[RoleSpan], evidence: list[Evidence]) -> list[RoleSpan]:
    by_id = {item.id: item for item in evidence}
    kept: list[RoleSpan] = []
    for span in spans:
        item = by_id.get(span.evidence_id)
        if item is None:
            continue
        if any(_copy(item, by_id[other.evidence_id]) for other in kept if other.evidence_id in by_id):
            continue
        kept.append(span)
    return kept


def _copy(left: Evidence, right: Evidence) -> bool:
    words_a = set(left.excerpt.lower().split())
    words_b = set(right.excerpt.lower().split())
    if not words_a or not words_b:
        return False
    return len(words_a & words_b) / min(len(words_a), len(words_b)) >= 0.8
