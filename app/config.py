from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Business decisions do not read a model vendor."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "redis-gtm-agent"
    database_url: str = "sqlite:///./data/gtm.db"
    search_provider: Literal["mock", "searxng"] = "mock"
    searxng_base_url: str = "http://localhost:8080"
    laya_mode: Literal["shadow", "active"] = "shadow"
    laya_base_url: str | None = None
    sheets_provider: Literal["mock", "google"] = "mock"
    google_sheets_spreadsheet_id: str | None = None
    google_credentials_file: str | None = None
    max_research_cycles: int = 3
    max_searches_per_cycle: int = 4
    max_pages_per_run: int = 8
    why_now_window_days: int = 180


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
