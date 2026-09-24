"""Account-research queries and the stop condition. At most three cycles."""

PROBLEM_TOPICS = frozenset({"ai_search", "rag", "low_latency", "retrieval", "distributed_systems"})
ORG_TOPICS = frozenset({"hiring_platform", "hiring_ml", "ownership_platform", "reports_platform", "person_mention"})


def queries_for(account_name: str, cycle: int) -> list[str]:
    if cycle <= 1:
        return [
            f"{account_name} AI search product",
            f"{account_name} retrieval architecture",
            f"{account_name} platform engineering hiring",
            f"{account_name} engineering leadership",
        ]
    if cycle == 2:
        return [
            f"{account_name} infrastructure latency",
            f"{account_name} machine learning infrastructure",
        ]
    return [f"{account_name} technical blog"]


def person_discovery_queries(
    account_name: str,
    domain: str,
    function_label: str,
    signal_label: str,
) -> list[str]:
    function = function_label or "engineering"
    host = domain or account_name
    title = _title_for_function(function)
    topic = _topic_phrase(signal_label, function)
    return [
        f"site:{host} team",
        f"{account_name} team",
        f"{account_name} {topic} blog",
        f"{account_name} conference speaker {topic}",
        f"{account_name} {function}",
        f"{account_name} {title}",
        f"site:github.com {account_name} {topic}",
        f"{account_name} engineering leadership",
    ]


def _topic_phrase(signal: str, function: str) -> str:
    lowered = signal.lower()
    if "vector" in lowered:
        return "vector search"
    if "rag" in lowered or "retrieval" in lowered or "search" in lowered:
        return "search"
    if "platform" in lowered or "platform" in function.lower():
        return "platform"
    return "engineering"


def _title_for_function(function: str) -> str:
    lowered = function.lower()
    if "platform" in lowered:
        return "Head of Platform"
    if "ml" in lowered or "machine learning" in lowered:
        return "Head of Machine Learning"
    return "VP Engineering"


def source_rank(url: str, domain: str) -> int:
    """Lower is better. Snippets are not ranked because they are not fetched as evidence."""
    from app.research.fetch import classify_source_type

    host = url.split("/")[2].lower() if "://" in url else ""
    official = bool(domain) and (host == domain.lower() or host.endswith("." + domain.lower()))
    kind = classify_source_type(url)
    kind_rank = {
        "biography": 1,
        "blog": 2,
        "conference": 3,
        "public_code": 5,
        "job_posting": 6,
        "untrusted_web": 7,
    }.get(kind, 7)
    if official and kind == "biography":
        return 0
    if official:
        return min(kind_rank, 2)
    return kind_rank


def evidence_is_sufficient(topics: set[str], source_urls: set[str]) -> bool:
    has_problem = bool(topics & PROBLEM_TOPICS)
    has_org = bool(topics & ORG_TOPICS)
    return len(source_urls) >= 3 and has_problem and has_org
