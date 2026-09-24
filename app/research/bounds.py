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
    signal = signal_label or "technical"
    host = domain or account_name
    return [
        f"{account_name} {function} leadership team",
        f"{account_name} engineering blog {signal}",
        f"{account_name} conference speaker {function}",
        f"{host} public biography {function}",
        f"{account_name} github {function}",
    ]


def evidence_is_sufficient(topics: set[str], source_urls: set[str]) -> bool:
    has_problem = bool(topics & PROBLEM_TOPICS)
    has_org = bool(topics & ORG_TOPICS)
    return len(source_urls) >= 3 and has_problem and has_org
