from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Business decisions do not read a model vendor."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "redis-gtm-agent"
    database_url: str = "sqlite:///./data/gtm.db"
    search_provider: Literal["mock", "searxng", "direct"] = "mock"
    searxng_base_url: str = Field(
        default="http://localhost:8080",
        validation_alias=AliasChoices("SEARXNG_URL", "SEARXNG_BASE_URL"),
    )
    search_timeout_seconds: float = 8.0
    search_retries: int = 2
    search_budget: int = 12
    laya_mode: Literal["shadow", "active"] = "shadow"
    laya_base_url: str | None = None
    sheets_provider: Literal["mock", "google"] = "mock"
    google_sheets_spreadsheet_id: str | None = None
    google_credentials_file: str | None = None
    max_research_cycles: int = 3
    max_searches_per_cycle: int = 4
    max_pages_per_run: int = 8
    person_page_budget: int = 6
    person_query_budget: int = 10
    discovery_query_budget: int = 10
    discovery_page_budget: int = 4
    verification_query_budget: int = 6
    verification_page_budget: int = 3
    deep_query_budget: int = 10
    deep_page_budget: int = 6
    why_now_window_days: int = 180
    current_role_window_days: int = 365
    current_activity_window_days: int = 365


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
