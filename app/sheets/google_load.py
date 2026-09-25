"""Load Google credentials. Isolated so the rest of the app stays strictly typed."""


def load_credentials(path: str) -> object:
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(
        path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )


def build_service(credentials: object) -> object:
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=credentials, cache_discovery=False)
