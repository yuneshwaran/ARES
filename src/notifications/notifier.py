"""Notification helpers for Windows Toast and Discord webhooks."""
from __future__ import annotations

import logging
from typing import Any

import requests

from ..utils.config import load_env

logger = logging.getLogger(__name__)


def send_windows_toast(title: str, message: str) -> bool:
    """Display a native Windows 10/11 toast notification via winotify."""
    try:
        from winotify import Notification

        toast = Notification(
            app_id="AresJobSearch",
            title=title,
            msg=message,
            duration="short",
        )
        toast.show()
        return True
    except Exception as exc:
        logger.debug("Windows toast failed: %s", exc)
        return False


def send_discord_webhook(webhook_url: str, title: str, message: str) -> bool:
    """Post an embed-style message to a Discord webhook URL."""
    if not webhook_url:
        return False
    try:
        resp = requests.post(
            webhook_url,
            json={"content": f"**{title}**\n{message}"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Discord notification failed: %s", exc)
        return False


def notify(settings: dict[str, Any], title: str, message: str) -> None:
    """Dispatch notifications according to settings['notifications']."""
    notif_cfg = settings.get("notifications", {})
    if notif_cfg.get("windows_toast", True):
        send_windows_toast(title, message)

    webhook = notif_cfg.get("discord_webhook") or load_env("DISCORD_WEBHOOK_URL") or ""
    if webhook:
        send_discord_webhook(webhook, title, message)
