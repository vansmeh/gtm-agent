"""Composition root. Provider choice stays here, not in the decision nodes."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.models import RunModel
from app.fixtures.acme_ai import DOCUMENTS
from app.graph.builder import build_graph
from app.graph.nodes import PipelineDeps
from app.graph.state import dump_run, load_run
from app.laya.adapter import LayaAdapter, default_kernel
from app.laya.llm import HttpLLMClient
from app.persistence.store import Store
from app.playbook.selection import Playbook, load_playbook
from app.research.fetch import FixtureFetcher, HttpxPageFetcher
from app.research.search import MockSearchProvider, SearXNGSearchProvider
from app.sheets.provider import SheetsProvider, build_sheets_provider

PLAYBOOK_PATH = Path(__file__).resolve().parent.parent / "templates" / "playbook.json"


def build_kernel(settings: Settings, http_client: object | None = None) -> LayaAdapter:
    if settings.laya_base_url and http_client is not None:
        return LayaAdapter(
            HttpLLMClient(settings.laya_base_url, http_client),
            mode=settings.laya_mode,
        )
    return default_kernel(settings.laya_mode)


def execute_run(
    *,
    settings: Settings,
    account_name: str,
    domain: str,
    search: object,
    fetcher: object,
    sheets: SheetsProvider,
    kernel: LayaAdapter,
    playbook: Playbook,
    session: Session,
    observed_at: datetime | None = None,
) -> RunModel:
    from app.research.fetch import PageFetcher
    from app.research.search import SearchProvider

    if not isinstance(search, SearchProvider):
        raise TypeError("search provider is invalid")
    if not isinstance(fetcher, PageFetcher):
        raise TypeError("fetcher is invalid")
    moment = observed_at or datetime.now(UTC)
    account_id = str(uuid.uuid4())
    run = RunModel(
        run_id=str(uuid.uuid4()),
        account_id=account_id,
        account_name=account_name,
        domain=domain,
        observed_at=moment,
        max_cycles=settings.max_research_cycles,
        max_pages=settings.max_pages_per_run,
    )
    store = Store(session)
    store.create_account(account_id, account_name, domain, moment)
    deps = PipelineDeps(
        search=search,
        fetcher=fetcher,
        sheets=sheets,
        kernel=kernel,
        playbook=playbook,
        observed_at=moment,
        max_searches_per_cycle=settings.max_searches_per_cycle,
        search_provider_name=settings.search_provider,
    )
    graph = build_graph(deps)
    final = graph(dump_run(run), {"recursion_limit": 40})
    completed = load_run(final)
    store.save_run(
        completed,
        search_provider=settings.search_provider,
        laya_mode=settings.laya_mode,
        created_at=moment,
    )
    return completed


def run_acme_demo(
    session: Session,
    settings: Settings,
    sheets: SheetsProvider | None = None,
) -> tuple[RunModel, SheetsProvider]:
    board = sheets or build_sheets_provider(provider="mock", spreadsheet_id=None, credentials_file=None)
    playbook = load_playbook(PLAYBOOK_PATH)
    run = execute_run(
        settings=settings,
        account_name="Acme AI",
        domain="acme.example",
        search=MockSearchProvider(DOCUMENTS),
        fetcher=FixtureFetcher(DOCUMENTS),
        sheets=board,
        kernel=default_kernel(settings.laya_mode),
        playbook=playbook,
        session=session,
        observed_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    return run, board


def default_providers(settings: Settings, http_client: object | None = None) -> tuple[object, object]:
    if settings.search_provider == "searxng":
        return (
            SearXNGSearchProvider(
                settings.searxng_base_url,
                timeout=settings.search_timeout_seconds,
                retries=settings.search_retries,
                budget=settings.search_budget,
            ),
            HttpxPageFetcher(http_client) if http_client is not None else HttpxPageFetcher(_default_http_client()),
        )
    return MockSearchProvider([]), FixtureFetcher([])


def _default_http_client() -> object:
    import httpx

    return httpx.Client(timeout=settings_timeout(), follow_redirects=True)


def settings_timeout() -> float:
    return 10.0
