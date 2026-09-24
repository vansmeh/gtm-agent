"""Sheets adapters. Tabs match the V1 operating cadence."""

from typing import Protocol, cast

TAB_NAMES: tuple[str, ...] = (
    "ACCOUNTS",
    "PEOPLE",
    "OPPORTUNITIES",
    "ACTIONS",
    "RESEARCH LOG",
    "OUTCOMES",
)

HEADERS: dict[str, list[str]] = {
    "ACCOUNTS": ["account_id", "name", "domain", "run_id", "observed_at"],
    "PEOPLE": [
        "person_id",
        "name",
        "role",
        "role_relevance",
        "problem_ownership",
        "technical_relevance",
        "timing_relevance",
        "public_evidence",
        "seniority",
        "contact_confidence",
        "why_this_person",
        "sources",
    ],
    "OPPORTUNITIES": [
        "id",
        "use_case",
        "relevance",
        "hypothesis",
        "supporting_evidence",
        "contradicting_evidence",
        "unknowns",
        "alternatives",
        "falsifier",
        "is_primary",
    ],
    "ACTIONS": ["action_id", "person", "channel", "template", "status", "sent", "draft"],
    "RESEARCH LOG": ["cycle", "node", "message"],
    "OUTCOMES": ["action_id", "result", "notes", "ranking_updated"],
}


class _Execute(Protocol):
    def execute(self) -> dict[str, object]: ...


class _ValuesApi(Protocol):
    def get(self, *, spreadsheetId: str, range: str) -> _Execute: ...

    def append(
        self,
        *,
        spreadsheetId: str,
        range: str,
        valueInputOption: str,
        insertDataOption: str,
        body: dict[str, list[list[str]]],
    ) -> _Execute: ...


class _Spreadsheets(Protocol):
    def get(self, *, spreadsheetId: str) -> _Execute: ...

    def values(self) -> _ValuesApi: ...

    def batchUpdate(self, *, spreadsheetId: str, body: dict[str, object]) -> _Execute: ...


class SheetsProvider(Protocol):
    def ensure_tabs(self) -> None:
        """Create the six tabs and header rows."""

    def append(self, tab: str, row: dict[str, str]) -> None:
        """Append one row."""

    def read(self, tab: str) -> list[dict[str, str]]:
        """Return stored rows."""


class MockSheetsProvider:
    def __init__(self) -> None:
        self.tabs: dict[str, list[dict[str, str]]] = {name: [] for name in TAB_NAMES}

    def ensure_tabs(self) -> None:
        for name in TAB_NAMES:
            self.tabs.setdefault(name, [])

    def append(self, tab: str, row: dict[str, str]) -> None:
        if tab not in HEADERS:
            raise KeyError(tab)
        self.tabs.setdefault(tab, []).append({key: row.get(key, "") for key in HEADERS[tab]})

    def read(self, tab: str) -> list[dict[str, str]]:
        return list(self.tabs.get(tab, []))


class GoogleSheetsProvider:
    """Google Sheets API v4. Constructed only when a spreadsheet id and credentials exist."""

    def __init__(self, spreadsheet_id: str, service: object) -> None:
        self.spreadsheet_id = spreadsheet_id
        self._service = service

    def ensure_tabs(self) -> None:
        existing = self._titles()
        missing = [name for name in TAB_NAMES if name not in existing]
        if missing:
            self._batch(
                [
                    {"addSheet": {"properties": {"title": name}}}
                    for name in missing
                ]
            )
        for name in TAB_NAMES:
            current = self._values(f"'{name}'!A1:Z1")
            if not current:
                self._append(name, HEADERS[name])

    def append(self, tab: str, row: dict[str, str]) -> None:
        if tab not in HEADERS:
            raise KeyError(tab)
        self._append(tab, [row.get(key, "") for key in HEADERS[tab]])

    def read(self, tab: str) -> list[dict[str, str]]:
        values = self._values(f"'{tab}'!A1:Z500")
        if len(values) < 2:
            return []
        header = values[0]
        rows: list[dict[str, str]] = []
        for raw in values[1:]:
            rows.append({header[i]: raw[i] if i < len(raw) else "" for i in range(len(header))})
        return rows

    def _titles(self) -> set[str]:
        meta = self._api().get(spreadsheetId=self.spreadsheet_id).execute()
        sheets = meta.get("sheets", [])
        titles: set[str] = set()
        if isinstance(sheets, list):
            for sheet in sheets:
                if isinstance(sheet, dict):
                    props = sheet.get("properties", {})
                    if isinstance(props, dict) and isinstance(props.get("title"), str):
                        titles.add(props["title"])
        return titles

    def _values(self, range_name: str) -> list[list[str]]:
        result = self._api().values().get(spreadsheetId=self.spreadsheet_id, range=range_name).execute()
        values = result.get("values", [])
        if not isinstance(values, list):
            return []
        return [[str(cell) for cell in row] for row in values if isinstance(row, list)]

    def _append(self, tab: str, row: list[str]) -> None:
        self._api().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

    def _batch(self, requests: list[dict[str, object]]) -> None:
        self._api().batchUpdate(spreadsheetId=self.spreadsheet_id, body={"requests": requests}).execute()

    def _api(self) -> "_Spreadsheets":
        spreadsheets = getattr(self._service, "spreadsheets", None)
        if not callable(spreadsheets):
            raise TypeError("Google Sheets service is missing spreadsheets()")
        return cast("_Spreadsheets", spreadsheets())


def build_sheets_provider(
    *,
    provider: str,
    spreadsheet_id: str | None,
    credentials_file: str | None,
) -> SheetsProvider:
    if provider == "google" and spreadsheet_id and credentials_file:
        from app.sheets.google_load import build_service, load_credentials

        return GoogleSheetsProvider(spreadsheet_id, build_service(load_credentials(credentials_file)))
    return MockSheetsProvider()
