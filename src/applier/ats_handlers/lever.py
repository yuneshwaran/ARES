"""Lever ATS form handler (jobs.lever.co)."""
from __future__ import annotations

import logging
from typing import Any

from .generic import fill_empty_textareas, fill_standard_fields, human_delay, upload_resume_file

logger = logging.getLogger(__name__)


async def fill_lever_form(
    page: Any,
    profile: dict[str, Any],
    resume_path: str,
    job_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle Lever application form layout."""
    personal = profile.get("personal", {})
    full_name = f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()

    lever_selectors = [
        ('input[name="name"]', full_name),
        ('input[name="email"]', personal.get("email", "")),
        ('input[name="phone"]', personal.get("phone", "")),
        ('input[name="org"]', profile.get("experience", {}).get("current_company", "")),
        ('input[name="urls[LinkedIn]"]', personal.get("linkedin_url", "")),
        ('input[name="urls[GitHub]"]', personal.get("github_url", "")),
        ('input[name="urls[Portfolio]"]', personal.get("portfolio_url", "")),
    ]

    filled = 0
    for sel, val in lever_selectors:
        if not val:
            continue
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.fill(str(val))
                filled += 1
                await human_delay((0.2, 0.5))
        except Exception:
            continue

    filled += await fill_standard_fields(page, profile)
    resume_uploaded = await upload_resume_file(page, resume_path)
    questions_filled = await fill_empty_textareas(page, profile, job_context=job_context)
    return {
        "handler": "lever",
        "fields_filled": filled,
        "resume_uploaded": resume_uploaded,
        "questions_filled": questions_filled,
    }
