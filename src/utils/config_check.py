"""Configuration and integration diagnostics for AresJobSearch."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..notifications.notifier import send_discord_webhook
from .ai_client import GeminiClient
from .config import (
    CONFIG_DIR,
    DATA_DIR,
    LOGS_DIR,
    load_env,
    load_profile,
    load_settings,
    resolve_project_path,
)

logger = logging.getLogger(__name__)


def inspect_local_config() -> dict[str, Any]:
    """Inspect local config files and credentials without making external network calls."""
    checks: list[dict[str, Any]] = []

    # 1. settings.yaml
    settings_path = CONFIG_DIR / "settings.yaml"
    settings: dict[str, Any] = {}
    try:
        settings = load_settings(settings_path)
        titles = settings.get("search", {}).get("titles", [])
        locations = settings.get("search", {}).get("locations", [])
        enabled_boards = [
            name
            for name, cfg in (settings.get("boards") or {}).items()
            if isinstance(cfg, dict) and cfg.get("enabled")
        ]
        checks.append(
            {
                "id": "settings",
                "name": "Search Settings (settings.yaml)",
                "ok": bool(titles),
                "detail": f"{len(titles)} title(s), {len(locations)} location(s), boards: {', '.join(enabled_boards) or 'none'}",
            }
        )
    except Exception as exc:
        checks.append(
            {
                "id": "settings",
                "name": "Search Settings (settings.yaml)",
                "ok": False,
                "detail": str(exc),
            }
        )

    # 2. profile.yaml
    profile_path = CONFIG_DIR / "profile.yaml"
    try:
        profile = load_profile(profile_path)
        personal = profile.get("personal", {})
        filled = bool(personal.get("first_name") and personal.get("email"))
        checks.append(
            {
                "id": "profile",
                "name": "Candidate Profile (profile.yaml)",
                "ok": filled,
                "detail": "Ready for auto-fill" if filled else "Personal name/email empty (needed only for auto-apply)",
            }
        )
    except Exception as exc:
        checks.append(
            {
                "id": "profile",
                "name": "Candidate Profile (profile.yaml)",
                "ok": False,
                "detail": str(exc),
            }
        )

    # 3. Master resume PDF
    resume_path = CONFIG_DIR / "resume.pdf"
    if resume_path.exists():
        try:
            from ..resume.parser import extract_resume_text

            text = extract_resume_text(resume_path)
            checks.append(
                {
                    "id": "resume",
                    "name": "Master Resume (config/resume.pdf)",
                    "ok": True,
                    "detail": f"Readable PDF ({len(text)} chars extracted)",
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "id": "resume",
                    "name": "Master Resume (config/resume.pdf)",
                    "ok": False,
                    "detail": f"PDF read error: {exc}",
                }
            )
    else:
        checks.append(
            {
                "id": "resume",
                "name": "Master Resume (config/resume.pdf)",
                "ok": False,
                "detail": "Missing — place your resume PDF at config/resume.pdf for scoring & tailoring",
            }
        )

    # 4. GEMINI_API_KEY
    gemini_key = load_env("GEMINI_API_KEY") or ""
    checks.append(
        {
            "id": "gemini_key",
            "name": "Gemini API Key (.env)",
            "ok": bool(gemini_key.strip()),
            "detail": f"Configured (prefix: {gemini_key[:4]}..., len={len(gemini_key)})"
            if gemini_key.strip()
            else "Missing GEMINI_API_KEY in config/.env",
        }
    )

    # 5. DISCORD_WEBHOOK_URL
    webhook = (settings.get("notifications", {}) or {}).get("discord_webhook") or load_env("DISCORD_WEBHOOK_URL") or ""
    checks.append(
        {
            "id": "discord",
            "name": "Discord Webhook",
            "ok": webhook.startswith("https://discord.com/api/webhooks/") or webhook.startswith("https://discordapp.com/api/webhooks/"),
            "detail": "Webhook URL configured" if webhook else "Not configured",
        }
    )

    # 6. Google OAuth credentials.json
    creds_path = CONFIG_DIR / "credentials.json"
    if creds_path.exists():
        try:
            creds_data = json.loads(creds_path.read_text(encoding="utf-8"))
            has_client = "installed" in creds_data or "web" in creds_data
            project_id = (creds_data.get("installed") or creds_data.get("web") or {}).get("project_id", "unknown")
            checks.append(
                {
                    "id": "credentials",
                    "name": "Google OAuth (credentials.json)",
                    "ok": has_client,
                    "detail": f"Valid OAuth client JSON (project: {project_id})" if has_client else "Unexpected JSON schema",
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "id": "credentials",
                    "name": "Google OAuth (credentials.json)",
                    "ok": False,
                    "detail": f"Invalid JSON: {exc}",
                }
            )
    else:
        checks.append(
            {
                "id": "credentials",
                "name": "Google OAuth (credentials.json)",
                "ok": False,
                "detail": "Missing config/credentials.json",
            }
        )

    # 7. Gmail OAuth token
    token_path = CONFIG_DIR / "gmail_token.json"
    checks.append(
        {
            "id": "gmail_token",
            "name": "Gmail Auth Token (gmail_token.json)",
            "ok": token_path.exists(),
            "detail": "Authorized token cached" if token_path.exists() else "Not authorized yet (run `check-email` once to sign in via browser)",
        }
    )

    # 8. Storage paths
    excel_rel = (settings.get("tracker", {}) or {}).get("excel_path", "data/tracker.xlsx")
    excel_path = resolve_project_path(excel_rel)
    db_path = DATA_DIR / "ares.db"
    checks.append(
        {
            "id": "storage",
            "name": "Database & Excel Tracker",
            "ok": True,
            "detail": f"DB: {'exists' if db_path.exists() else 'will initialize'}, Excel: {'exists' if excel_path.exists() else 'will initialize'}",
        }
    )

    return {
        "checks": checks,
        "summary": {
            "passed": sum(1 for c in checks if c["ok"]),
            "total": len(checks),
        },
        "log_file": str(LOGS_DIR / "ares.log"),
    }


def run_live_integration_tests(
    test_gemini: bool = True,
    test_discord: bool = True,
) -> dict[str, Any]:
    """Run live network tests for Gemini API and Discord webhook."""
    settings = load_settings()
    results: dict[str, Any] = {}

    if test_gemini:
        model_name = (settings.get("scoring", {}) or {}).get("gemini_model", "gemini-2.0-flash")
        try:
            client = GeminiClient(model_name=model_name)
            reply = client.generate_text("Reply with the single word: READY").strip()
            results["gemini"] = {
                "ok": bool(reply),
                "detail": f"Connected ({model_name}): {reply[:80]}",
            }
        except Exception as exc:
            results["gemini"] = {
                "ok": False,
                "detail": f"Gemini test failed: {exc}",
            }

    if test_discord:
        webhook = (settings.get("notifications", {}) or {}).get("discord_webhook") or load_env("DISCORD_WEBHOOK_URL") or ""
        if not webhook:
            results["discord"] = {
                "ok": False,
                "detail": "DISCORD_WEBHOOK_URL is not set",
            }
        else:
            sent = send_discord_webhook(
                webhook,
                "AresJobSearch Config Test",
                "Discord webhook connection verified successfully.",
            )
            results["discord"] = {
                "ok": sent,
                "detail": "Test notification delivered to Discord" if sent else "Webhook POST failed (see logs/ares.log)",
            }

    return results
