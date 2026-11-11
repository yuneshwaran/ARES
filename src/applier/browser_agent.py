"""Playwright browser automation agent for job applications."""
from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Any

from .ats_handlers.generic import fill_generic_form
from .ats_handlers.greenhouse import fill_greenhouse_form
from .ats_handlers.lever import fill_lever_form

logger = logging.getLogger(__name__)


def select_ats_handler(url: str):
    """Pick an ATS-specific form handler based on the target URL."""
    lowered = (url or "").lower()
    if "greenhouse.io" in lowered:
        return fill_greenhouse_form
    if "lever.co" in lowered:
        return fill_lever_form
    return fill_generic_form


class ApplicationAgent:
    """Automated browser form-filler with human-in-the-loop review support."""

    def __init__(
        self,
        profile: dict[str, Any],
        headless: bool = False,
        delay_range: tuple[float, float] = (2.0, 5.0),
    ):
        self.profile = profile
        self.headless = headless
        self.delay_range = delay_range

    async def apply_to_job(
        self,
        job_url: str,
        resume_path: str = "",
        mode: str = "review",
        job_context: dict[str, Any] | None = None,
    ) -> bool:
        """Navigate to job_url, fill application form, and submit or wait for user review."""
        if not job_url:
            logger.warning("Cannot apply: empty job_url")
            return False

        from playwright.async_api import async_playwright

        user_data_dir = Path.home() / ".ares" / "browser_profile"
        user_data_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()

            try:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=35000)
                await asyncio.sleep(random.uniform(*self.delay_range))

                handler = select_ats_handler(page.url or job_url)
                summary = await handler(
                    page,
                    self.profile,
                    resume_path,
                    job_context=job_context,
                )
                logger.info("Form fill summary for %s: %s", job_url, summary)

                if mode == "review":
                    print(
                        "\n[REVIEW MODE] Form pre-filled in browser. "
                        "Review everything, submit manually if satisfied, then press Enter "
                        "(or type 'skip' + Enter if you did NOT apply): "
                    )
                    reply = input().strip().lower()
                    return reply != "skip"

                if mode in ("semi_auto", "full_auto"):
                    submit = page.locator(
                        'button[type="submit"], input[type="submit"], button:has-text("Submit Application")'
                    ).first
                    if await submit.count() > 0 and await submit.is_visible():
                        await asyncio.sleep(random.uniform(*self.delay_range))
                        await submit.click()
                        await asyncio.sleep(2.0)
                        logger.info("Submitted application for %s", job_url)
                        return True
                    logger.warning("No visible submit button found on %s", job_url)
                    return False

                return False
            except Exception as exc:
                logger.error("Application failed for %s: %s", job_url, exc)
                return False
            finally:
                await browser.close()
