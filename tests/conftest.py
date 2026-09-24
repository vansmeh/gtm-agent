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
    ):
        monkeypatch.delenv(key, raising=False)
