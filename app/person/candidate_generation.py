"""High-recall name extraction from public search results. Snippets are not identity."""

import re
from dataclasses import dataclass

from app.person.entity import classify_entity
from app.research.search import SearchHit

_NAME = r"([A-Z][a-z]{2,}(?: [A-Z][a-z]{2,}){1,2})"
_BY = re.compile(rf"\b(?:By|Author|Written by)\s+{_NAME}\b")
_SPEAKER = re.compile(rf"\b(?:Speaker|Presented by|Talk by)\s*:?\s+{_NAME}\b")
_ROLE = re.compile(
    rf"\b{_NAME},?\s+(?:Senior |Staff |Principal |Lead )?(?:Engineer|Architect|Director|Head of|Manager)\b"
)
_BARE = re.compile(rf"\b{_NAME}\b")
_COMMON = frozenset(
    {
        "reference",
        "architectures",
        "architecture",
        "zero",
        "trust",
        "open",
        "positions",
        "now",
        "hiring",
        "simplify",
        "jobs",
        "security",
        "frontend",
        "development",
        "united",
        "states",
        "distributed",
        "core",
        "web",
        "vitals",
        "getting",
        "started",
        "connectivity",
        "grow",
        "revenue",
        "step",
        "guide",
        "deep",
        "dive",
        "early",
        "career",
        "opportunities",
        "technical",
        "roles",
        "product",
        "filter",
        "design",
        "principles",
        "machine",
        "learning",
        "remote",
        "site",
        "reliability",
        "data",
        "internship",
        "program",
        "ecommerce",
        "user",
        "manual",
        "apply",
        "center",
        "solution",
        "solutions",
        "content",
        "delivery",
        "payments",
        "emerging",
        "talent",
        "production",
        "scaling",
        "blueprint",
        "join",
        "system",
        "real",
        "world",
        "teardown",
        "teardowns",
        "ultimate",
        "dual",
        "display",
        "port",
        "back",
        "bone",
        "developer",
        "developers",
        "careers",
        "salaries",
        "salary",
        "company",
        "about",
        "home",
        "docs",
        "documentation",
        "overview",
        "introduction",
        "what",
        "how",
        "why",
        "new",
        "best",
        "top",
        "free",
        "online",
        "global",
        "public",
        "private",
        "cloud",
        "network",
        "networks",
        "service",
        "services",
        "support",
        "customer",
        "customers",
        "business",
        "enterprise",
        "app",
        "apps",
        "store",
        "shop",
        "blog",
        "news",
        "press",
        "media",
        "contact",
        "login",
        "sign",
        "privacy",
        "terms",
        "policy",
        "legal",
        "status",
        "changelog",
        "release",
        "notes",
        "read",
        "more",
        "learn",
        "view",
        "see",
        "all",
        "page",
        "article",
        "post",
        "posts",
        "tag",
        "tags",
        "category",
        "related",
        "share",
        "subscribe",
        "download",
        "install",
        "build",
        "scale",
        "fast",
        "high",
        "low",
        "latency",
        "search",
        "vector",
        "model",
        "models",
        "training",
        "inference",
        "feature",
        "features",
        "pipeline",
        "pipelines",
        "infrastructure",
        "platform",
        "engineering",
        "compliance",
        "fail",
        "small",
        "project",
        "glasswing",
        "hot",
        "module",
        "replacement",
        "buy",
        "domains",
        "actors",
        "risk",
        "who",
        "subpoena",
        "bug",
        "bash",
        "round",
        "scope",
        "industry",
        "leaders",
        "elegant",
        "puzzle",
        "south",
        "san",
        "francisco",
        "beat",
        "either",
        "rails",
        "administrative",
        "assistant",
        "commerce",
        "components",
        "modern",
        "exteriors",
        "agentic",
        "storefronts",
        "announces",
        "multi",
        "intern",
        "microsite",
        "make",
        "money",
        "elasticsearch",
        "georgia",
        "scales",
        "exponentially",
        "practical",
        "reason",
        "chief",
        "executive",
        "officer",
    }
)
_GENERIC = frozenset(
    {
        "full",
        "stack",
        "platform",
        "engineering",
        "infrastructure",
        "leadership",
        "software",
        "senior",
        "staff",
        "principal",
        "architect",
        "engineer",
        "manager",
        "director",
        "head",
        "team",
        "search",
        "backend",
        "runtime",
        "performance",
        "interview",
        "interviews",
        "github",
        "blog",
        "speaker",
        "author",
        "our",
        "the",
        "and",
    }
)


@dataclass
class ExtractedName:
    name: str
    title: str
    url: str
    excerpt: str
    tier: str
    reason: str = ""


def recall_queries(account_name: str, domain: str, functions: list[str]) -> list[str]:
    """Up to 10 queries for each affected function. Empty when no function is known."""
    if not functions:
        return []
    host = domain or account_name
    families = (
        "platform engineer",
        "platform engineering",
        "infrastructure engineer",
        "backend engineer",
        "distributed systems",
        "runtime engineering",
        "performance engineering",
        "search engineering",
        "AI platform",
        "ML platform",
        "architecture",
        "principal engineer",
        "staff engineer",
        "engineering manager",
    )
    site_terms = ("engineer", "platform", "infrastructure", "architecture", '"our team"', "author", "speaker")
    queries: list[str] = []
    for function in functions:
        focus = function.lower()
        ordered = [item for item in families if focus in item or item in focus] + list(families)
        phrases = [f"{account_name} {phrase}" for phrase in dict.fromkeys(ordered)]
        sites = [f"site:{host} {term}" for term in site_terms]
        queries.extend(phrases[:6] + sites[:4])
    return queries


def source_tier(url: str, domain: str) -> str:
    host = url.split("/")[2].lower() if "://" in url else ""
    official = bool(domain) and (host == domain.lower() or host.endswith("." + domain.lower()))
    path = url.lower()
    if official and any(part in path for part in ("/blog", "/engineering", "/author", "/team")):
        return "tier_2"
    if official:
        return "tier_1"
    if any(part in path for part in ("/speaker", "/talk", "/agenda", "conference", "podcast", "interview")):
        return "tier_3"
    if "linkedin.com" in host:
        return "tier_4"
    if "github.com" in host:
        return "tier_5"
    return "tier_6"


def extract_names(
    hits: list[SearchHit], account_name: str, domain: str
) -> tuple[list[ExtractedName], int, int, int]:
    """Return retained names, raw extraction count, and rejection count."""
    account = account_name.lower()
    extracted: list[ExtractedName] = []
    rejected = 0
    for hit in hits:
        text = f"{hit.title}. {hit.snippet}"
        connected = account in text.lower() or (domain and domain.lower() in hit.url.lower())
        if not connected:
            continue
        found = _names_from_text(text)
        if not found:
            if _looks_like_title_only(text):
                rejected += 1
            continue
        for name, title, kind in found:
            reason = _reject_name(name, hit.url, kind, account, text)
            if reason:
                rejected += 1
                continue
            extracted.append(
                ExtractedName(
                    name=name,
                    title=title,
                    url=hit.url,
                    excerpt=" ".join(text.split())[:500],
                    tier=source_tier(hit.url, domain),
                )
            )
    kept, duplicates = cluster_people(extracted)
    return kept, len(extracted) + rejected, rejected, duplicates


def cluster_people(names: list[ExtractedName]) -> tuple[list[ExtractedName], int]:
    """Collapse the same person and mirrored reposts."""
    kept: list[ExtractedName] = []
    seen_names: set[str] = set()
    seen_slugs: set[str] = set()
    duplicates = 0
    for item in names:
        slug = item.url.rstrip("/").rsplit("/", 1)[-1].lower()
        key = item.name.lower()
        if key in seen_names or (slug and slug in seen_slugs):
            duplicates += 1
            continue
        seen_names.add(key)
        if slug:
            seen_slugs.add(slug)
        kept.append(item)
    return kept, duplicates


def _names_from_text(text: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for kind, pattern in (("byline", _BY), ("speaker", _SPEAKER), ("role", _ROLE)):
        for match in pattern.finditer(text):
            found.append((match.group(1), _nearby_title(text, match.group(1)), kind))
    if not found:
        for match in _BARE.finditer(text):
            if not _bare_name_in_prose(text, match.start(), match.end()):
                continue
            found.append((match.group(1), "", "bare"))
    unique: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for name, title, kind in found:
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        unique.append((name, title, kind))
    return unique


def _bare_name_in_prose(text: str, start: int, end: int) -> bool:
    """A heading of two capitalized words is not a person. Prose names are."""
    if start > 0 and text[start - 1].isalpha():
        return False
    return bool(re.match(r"(?:,|\s+[a-z])", text[end:]))


def _nearby_title(text: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)},?\s+([A-Z][^,.]{{0,60}})", text)
    if match is None:
        return ""
    title = match.group(1).strip()
    if any(token in title.lower() for token in ("engineer", "architect", "director", "head", "manager", "lead")):
        return title[:80]
    return ""


def _reject_name(name: str, url: str, kind: str, account: str, context: str = "") -> str:
    parts = name.split()
    lowered = [part.lower() for part in parts]
    if len(set(lowered)) < 2:
        return "generic heading"
    if len(parts) < 2 or any(part in _GENERIC or part in _COMMON or part == account for part in lowered):
        return "generic heading"
    if kind == "bare" and "github.com" in url:
        return "github username without attribution"
    if not any(part[:1].isupper() for part in parts):
        return "not a person name"
    marker = context if kind in {"byline", "speaker", "role"} else context
    entity = classify_entity(name, marker if kind != "bare" else context)
    if entity != "PERSON":
        return f"not a person ({entity})"
    return ""


def _looks_like_title_only(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("engineer", "architect", "leadership", "full stack")) and not _BY.search(
        text
    )
