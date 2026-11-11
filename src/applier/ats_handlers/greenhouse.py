"""Greenhouse ATS form handler (boards.greenhouse.io / job-boards.greenhouse.io)."""
from __future__ import annotations

import logging
from typing import Any

from .generic import fill_empty_textareas, fill_standard_fields, human_delay, upload_resume_file

logger = logging.getLogger(__name__)


async def fill_greenhouse_form(
    page: Any,
    profile: dict[str, Any],
    resume_path: str,
    job_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Handle Greenhouse application form layout."""
    personal = profile.get("personal", {})
    gh_selectors = [
        ("#first_name", personal.get("first_name", "")),
        ("#last_name", personal.get("last_name", "")),
        ("#email", personal.get("email", "")),
        ("#phone", personal.get("phone", "")),
    ]

    filled = 0
    for sel, val in gh_selectors:
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
        "handler": "greenhouse",
        "fields_filled": filled,
        "resume_uploaded": resume_uploaded,
        "questions_filled": questions_filled,
    }
