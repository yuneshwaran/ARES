"""Generic ATS form filler with AI-assisted custom question handling."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from ..form_mapper import answer_custom_question, build_field_mapping

logger = logging.getLogger(__name__)


async def human_delay(delay_range: tuple[float, float] = (0.4, 1.2)) -> None:
    await asyncio.sleep(random.uniform(delay_range[0], delay_range[1]))


async def fill_standard_fields(page: Any, profile: dict[str, Any]) -> int:
    """Fill visible standard input fields using profile mappings. Returns count filled."""
    filled = 0
    for selector, value in build_field_mapping(profile):
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0 and await locator.is_visible():
                current = await locator.input_value()
                if not current:
                    await locator.fill(value)
                    filled += 1
                    await human_delay((0.2, 0.6))
        except Exception:
            continue
    return filled


async def upload_resume_file(page: Any, resume_path: str) -> bool:
    """Upload a PDF resume to the first file input on the page."""
    if not resume_path:
        return False
    try:
        file_inputs = page.locator('input[type="file"]')
        count = await file_inputs.count()
        if count > 0:
            await file_inputs.first.set_input_files(resume_path)
            logger.info("Uploaded resume: %s", resume_path)
            return True
    except Exception as exc:
        logger.warning("Resume upload failed: %s", exc)
    return False


async def fill_empty_textareas(
    page: Any,
    profile: dict[str, Any],
    job_context: dict[str, Any] | None = None,
) -> int:
    """Fill empty visible textareas by reading their associated label and asking form_mapper."""
    filled = 0
    try:
        textareas = page.locator("textarea")
        count = await textareas.count()
        for i in range(min(count, 5)):
            ta = textareas.nth(i)
            if not await ta.is_visible():
                continue
            if (await ta.input_value()).strip():
                continue

            ta_id = await ta.get_attribute("id")
            question = ""
            if ta_id:
                label = page.locator(f'label[for="{ta_id}"]').first
                if await label.count() > 0:
                    question = (await label.inner_text()).strip()
            if not question:
                question = (await ta.get_attribute("placeholder")) or "Additional information"

            answer = answer_custom_question(question, profile, job_context=job_context)
            if answer:
                await ta.fill(answer)
                filled += 1
                await human_delay((0.4, 1.0))
    except Exception as exc:
        logger.debug("Textarea fill error: %s", exc)
    return filled


async def fill_generic_form(
    page: Any,
    profile: dict[str, Any],
    resume_path: str,
    job_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fill generic application form fields, upload resume, and handle textareas."""
    fields_filled = await fill_standard_fields(page, profile)
    resume_uploaded = await upload_resume_file(page, resume_path)
    questions_filled = await fill_empty_textareas(page, profile, job_context=job_context)
    return {
        "handler": "generic",
        "fields_filled": fields_filled,
        "resume_uploaded": resume_uploaded,
        "questions_filled": questions_filled,
    }
