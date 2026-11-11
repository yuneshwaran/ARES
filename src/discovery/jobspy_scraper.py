"""Multi-board job scraper using python-jobspy (gracefully degrades if unavailable)."""
from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger(__name__)


def _clean_val(val: Any) -> Any:
    if isinstance(val, float) and math.isnan(val):
        return None
    return val


def scrape_all_boards(settings: dict[str, Any], limit: int = 0) -> list[dict[str, Any]]:
    """Scrape jobs from all enabled python-jobspy boards and return normalized job dicts."""
    search_cfg = settings.get("search", {})
    board_cfg = settings.get("boards", {}).get("jobspy", {})

    if not board_cfg.get("enabled", True):
        logger.info("JobSpy scraping disabled in settings")
        return []

    try:
        from jobspy import scrape_jobs
    except Exception as exc:
        logger.warning(
            "python-jobspy unavailable (%s); continuing with API job sources.",
            exc,
        )
        return []

    all_jobs: list[dict[str, Any]] = []
    titles = search_cfg.get("titles", [])
    locations = search_cfg.get("locations", ["Remote"])
    sites = board_cfg.get("sites", ["linkedin", "indeed", "glassdoor"])
    country_indeed = search_cfg.get("country_indeed", "india")
    configured_per_board = int(search_cfg.get("results_per_board", 50))
    results_wanted = min(configured_per_board, limit) if limit > 0 else configured_per_board

    query_idx = 0
    for title in titles:
        for location in locations:
            if limit > 0 and len(all_jobs) >= limit:
                return all_jobs[:limit]
            if query_idx > 0:
                time.sleep(2.0)  # Polite pause between queries to reduce 429 rate limits
            query_idx += 1

            try:
                logger.info("Scraping '%s' in '%s' from %s", title, location, sites)
                kwargs: dict[str, Any] = {
                    "site_name": sites,
                    "search_term": title,
                    "location": location,
                    "results_wanted": results_wanted,
                    "hours_old": search_cfg.get("hours_old", 24),
                    "job_type": search_cfg.get("job_type", "fulltime"),
                    "country_indeed": country_indeed,
                }
                if board_cfg.get("proxy"):
                    kwargs["proxies"] = board_cfg["proxy"]

                jobs_df = scrape_jobs(**kwargs)
                if jobs_df is not None and not jobs_df.empty:
                    records = jobs_df.to_dict(orient="records")
                    for rec in records:
                        cleaned = {k: _clean_val(v) for k, v in rec.items()}
                        all_jobs.append(cleaned)
                    logger.info("Found %d jobs for '%s' in '%s'", len(records), title, location)
                else:
                    logger.info("Found 0 jobs for '%s' in '%s'", title, location)
            except Exception as exc:
                logger.error("Error scraping '%s' in '%s': %s", title, location, exc)

    logger.info("Total raw JobSpy jobs scraped: %d", len(all_jobs))
    return all_jobs[:limit] if limit > 0 else all_jobs
