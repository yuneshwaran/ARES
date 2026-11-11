"""Gmail API client for fetching recruiter and application status emails."""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from ..utils.config import CONFIG_DIR

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_TOKEN_PATH = CONFIG_DIR / "gmail_token.json"
DEFAULT_CREDS_PATH = CONFIG_DIR / "credentials.json"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _decode_b64(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_body_from_payload(payload: dict[str, Any]) -> str:
    """Recursively extract plain text (or stripped HTML) from a Gmail message payload."""
    mime = payload.get("mimeType", "")
    body_data = (payload.get("body") or {}).get("data", "")

    if mime == "text/plain" and body_data:
        return _decode_b64(body_data)

    parts = payload.get("parts") or []
    # Prefer text/plain first
    for part in parts:
        if part.get("mimeType") == "text/plain":
            text = _extract_body_from_payload(part)
            if text:
                return text

    # Recurse into multipart containers or fall back to text/html
    html_fallback = ""
    for part in parts:
        text = _extract_body_from_payload(part)
        if text:
            if part.get("mimeType") == "text/html":
                html_fallback = text
            else:
                return text

    if html_fallback:
        return _HTML_TAG_RE.sub(" ", html_fallback).strip()

    if mime == "text/html" and body_data:
        return _HTML_TAG_RE.sub(" ", _decode_b64(body_data)).strip()

    if body_data:
        return _decode_b64(body_data)
    return ""


class GmailClient:
    """OAuth 2.0 Gmail API client for reading application-related emails."""

    def __init__(
        self,
        credentials_path: Path | str | None = None,
        token_path: Path | str | None = None,
        service: Any = None,
    ):
        self.credentials_path = Path(credentials_path) if credentials_path else DEFAULT_CREDS_PATH
        self.token_path = Path(token_path) if token_path else DEFAULT_TOKEN_PATH
        self.service = service or self._authenticate()

    def _authenticate(self) -> Any:
        """Authenticate using OAuth 2.0 Desktop App credentials."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds: Credentials | None = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"Google OAuth credentials not found at '{self.credentials_path}'. "
                        "Download Desktop App credentials.json from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        return build("gmail", "v1", credentials=creds)

    def search_emails(self, query: str, max_results: int = 30) -> list[dict[str, Any]]:
        """Search Gmail messages matching `query` and return parsed dicts."""
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])
        parsed: list[dict[str, Any]] = []

        for msg_meta in messages:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_meta["id"], format="full")
                .execute()
            )
            payload = msg.get("payload", {})
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            raw_date = headers.get("date", "")
            parsed_date: datetime | None = None
            if raw_date:
                try:
                    parsed_date = parsedate_to_datetime(raw_date)
                except Exception:
                    parsed_date = None

            body = _extract_body_from_payload(payload)
            parsed.append(
                {
                    "id": msg_meta["id"],
                    "from": headers.get("from", ""),
                    "subject": headers.get("subject", ""),
                    "date": raw_date,
                    "parsed_date": parsed_date,
                    "snippet": msg.get("snippet", ""),
                    "body": body[:3000],
                }
            )

        return parsed
