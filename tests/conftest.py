import pytest


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DATABASE_URL",
        "SEARXNG_URL",
        "SEARXNG_BASE_URL",
        "MAX_PAGES_PER_RUN",
        "MAX_SEARCHES_PER_CYCLE",
        "MAX_RESEARCH_CYCLES",
        "SEARCH_BUDGET",
        "SEARCH_TIMEOUT_SECONDS",
        "PERSON_PAGE_BUDGET",
        "PERSON_QUERY_BUDGET",
        "DISCOVERY_QUERY_BUDGET",
        "DISCOVERY_PAGE_BUDGET",
        "VERIFICATION_QUERY_BUDGET",
        "VERIFICATION_PAGE_BUDGET",
        "DEEP_QUERY_BUDGET",
        "DEEP_PAGE_BUDGET",
        "ROLE_BRIDGE_BUDGET",
    ):
        monkeypatch.delenv(key, raising=False)
