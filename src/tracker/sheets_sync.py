"""Optional Google Sheets synchronization for the Excel application tracker."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..utils.config import CONFIG_DIR
from .excel_writer import ExcelTracker

logger = logging.getLogger(__name__)

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
DEFAULT_SHEETS_TOKEN = CONFIG_DIR / "sheets_token.json"
DEFAULT_CREDS_PATH = CONFIG_DIR / "credentials.json"


def sync_excel_to_sheets(
    excel_tracker: ExcelTracker,
    sheet_id: str,
    worksheet_name: str = "Applications",
    credentials_path: Path | None = None,
    token_path: Path | None = None,
) -> int:
    """Sync all rows from the local Excel tracker to a Google Sheet.

    Returns the number of rows synced.
    """
    if not sheet_id:
        raise ValueError("tracker.sheets_id must be configured in config/settings.yaml")

    import gspread
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_file = credentials_path or DEFAULT_CREDS_PATH
    tok_file = token_path or DEFAULT_SHEETS_TOKEN

    creds: Any = None
    if tok_file.exists():
        creds = Credentials.from_authorized_user_file(str(tok_file), SHEETS_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_file.exists():
                raise FileNotFoundError(
                    f"Google credentials.json not found at '{creds_file}'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SHEETS_SCOPES)
            creds = flow.run_local_server(port=0)
        tok_file.parent.mkdir(parents=True, exist_ok=True)
        tok_file.write_text(creds.to_json(), encoding="utf-8")

    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=15)

    rows = excel_tracker.read_all_rows()
    cleaned_rows = [["" if cell is None else str(cell) for cell in row] for row in rows]

    worksheet.clear()
    if cleaned_rows:
        worksheet.update(range_name="A1", values=cleaned_rows)

    logger.info("Synced %d rows to Google Sheet %s", len(cleaned_rows), sheet_id)
    return len(cleaned_rows)
