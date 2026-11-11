"""API-based job discovery clients (Remotive, Arbeitnow, The Muse, Adzuna, JSearch)."""
from __future__ import annotations

import logging
import re
from typing import Any

import requests

from ..utils.config import load_env

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub(" ", text or "").strip()


def fetch_remotive_jobs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch remote jobs from Remotive public API (free, no key required)."""
    cfg = settings.get("boards", {}).get("remotive", {})
    if not cfg.get("enabled", True):
        return []

    titles = settings.get("search", {}).get("titles", []) or [""]
    limit = int(cfg.get("limit", 25))
    rows: list[dict[str, Any]] = []

    for title in titles[:3]:
        params: dict[str, Any] = {"limit": limit}
        if title:
            params["search"] = title
        try:
            resp = requests.get("https://remotive.com/api/remote-jobs", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("Remotive API error for '%s': %s", title, exc)
            continue

        for item in data.get("jobs", []):
            rows.append(
                {
                    "title": item.get("title", ""),
                    "company": item.get("company_name", ""),
                    "location": item.get("candidate_required_location", "") or "Remote",
                    "description": _strip_html(item.get("description", "")),
                    "job_url": item.get("url", ""),
                    "site": "remotive",
                    "date_posted": item.get("publication_date"),
                    "min_amount": None,
                    "max_amount": None,
                    "job_type": item.get("job_type", ""),
                }
            )

    logger.info("Remotive API returned %d jobs", len(rows))
    return rows


def fetch_arbeitnow_jobs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch jobs from Arbeitnow public API (free, no key required)."""
    cfg = settings.get("boards", {}).get("arbeitnow", {})
    if not cfg.get("enabled", False):
        return []

    titles = [t.lower() for t in (settings.get("search", {}).get("titles") or []) if t]
    rows: list[dict[str, Any]] = []

    try:
        resp = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Arbeitnow API error: %s", exc)
        return []

    for item in data.get("data", []):
        title = item.get("title", "")
        if titles and not any(t in title.lower() for t in titles):
            continue
        rows.append(
            {
                "title": title,
                "company": item.get("company_name", ""),
                "location": item.get("location", "") or ("Remote" if item.get("remote") else ""),
                "description": _strip_html(item.get("description", "")),
                "job_url": item.get("url", ""),
                "site": "arbeitnow",
                "date_posted": item.get("created_at"),
                "min_amount": None,
                "max_amount": None,
                "job_type": ", ".join(item.get("job_types") or []),
            }
        )

    logger.info("Arbeitnow API returned %d matching jobs", len(rows))
    return rows


def fetch_themuse_jobs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch jobs from The Muse public API (disabled by default)."""
    cfg = settings.get("boards", {}).get("themuse", {})
    if not cfg.get("enabled", False):
        return []

    api_key = load_env("THE_MUSE_API_KEY")
    max_pages = int(cfg.get("max_pages", 2))
    titles = [t.lower() for t in (settings.get("search", {}).get("titles") or []) if t]
    rows: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        params: dict[str, Any] = {"page": page}
        if api_key:
            params["api_key"] = api_key
        try:
            resp = requests.get("https://www.themuse.com/api/public/jobs", params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("The Muse API error (page %d): %s", page, exc)
            break

        for item in data.get("results", []):
            title = item.get("name", "")
            if titles and not any(t in title.lower() for t in titles):
                continue
            company = (item.get("company") or {}).get("name", "")
            locs = [loc.get("name", "") for loc in item.get("locations", []) if loc.get("name")]
            rows.append(
                {
                    "title": title,
                    "company": company,
                    "location": ", ".join(locs) or "Remote",
                    "description": _strip_html(item.get("contents", "")),
                    "job_url": (item.get("refs") or {}).get("landing_page", ""),
                    "site": "themuse",
                    "date_posted": item.get("publication_date"),
                    "min_amount": None,
                    "max_amount": None,
                    "job_type": settings.get("search", {}).get("job_type", "fulltime"),
                }
            )

    logger.info("The Muse API returned %d matching jobs", len(rows))
    return rows


def fetch_adzuna_jobs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch jobs from Adzuna API (free ~250 calls/day with free registration)."""
    cfg = settings.get("boards", {}).get("adzuna", {})
    if not cfg.get("enabled", False):
        return []

    app_id = load_env("ADZUNA_APP_ID")
    app_key = load_env("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        logger.warning("Adzuna enabled in settings, but ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
        return []

    country = cfg.get("country", "in")
    search_cfg = settings.get("search", {})
    rows: list[dict[str, Any]] = []

    for title in search_cfg.get("titles", []):
        for location in search_cfg.get("locations", ["Remote"]):
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
            params = {
                "app_id": app_id,
                "app_key": app_key,
                "what": title,
                "where": location,
                "results_per_page": min(int(search_cfg.get("results_per_board", 25)), 50),
                "content-type": "application/json",
            }
            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("Adzuna API error for '%s' in '%s': %s", title, location, exc)
                continue

            for item in data.get("results", []):
                rows.append(
                    {
                        "title": item.get("title", ""),
                        "company": (item.get("company") or {}).get("display_name", ""),
                        "location": (item.get("location") or {}).get("display_name", location),
                        "description": item.get("description", ""),
                        "job_url": item.get("redirect_url", ""),
                        "site": "adzuna",
                        "date_posted": item.get("created"),
                        "min_amount": item.get("salary_min"),
                        "max_amount": item.get("salary_max"),
                        "job_type": item.get("contract_time", ""),
                    }
                )

    logger.info("Adzuna API returned %d jobs", len(rows))
    return rows


def fetch_jsearch_jobs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch jobs from JSearch (RapidAPI). Disabled by default (~200 req/month free)."""
    cfg = settings.get("boards", {}).get("jsearch", {})
    if not cfg.get("enabled", False):
        return []

    api_key = load_env("JSEARCH_API_KEY")
    if not api_key:
        logger.warning("JSearch enabled in settings, but JSEARCH_API_KEY not set")
        return []

    search_cfg = settings.get("search", {})
    rows: list[dict[str, Any]] = []
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    for title in search_cfg.get("titles", []):
        for location in search_cfg.get("locations", ["Remote"]):
            query = f"{title} in {location}"
            try:
                resp = requests.get(
                    "https://jsearch.p.rapidapi.com/search",
                    headers=headers,
                    params={"query": query, "num_pages": "1"},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning("JSearch API error for '%s': %s", query, exc)
                continue

            for item in data.get("data", []):
                city = item.get("job_city") or ""
                country = item.get("job_country") or ""
                loc = ", ".join(p for p in [city, country] if p) or "Remote"
                rows.append(
                    {
                        "title": item.get("job_title", ""),
                        "company": item.get("employer_name", ""),
                        "location": loc,
                        "description": item.get("job_description", ""),
                        "job_url": item.get("job_apply_link") or item.get("job_google_link", ""),
                        "site": f"jsearch:{item.get('job_publisher', 'google')}",
                        "date_posted": item.get("job_posted_at_datetime_utc"),
                        "min_amount": item.get("job_min_salary"),
                        "max_amount": item.get("job_max_salary"),
                        "job_type": item.get("job_employment_type", ""),
                    }
                )

    logger.info("JSearch API returned %d jobs", len(rows))
    return rows


def fetch_all_api_jobs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate jobs from all enabled API sources."""
    return (
        fetch_remotive_jobs(settings)
        + fetch_arbeitnow_jobs(settings)
        + fetch_themuse_jobs(settings)
        + fetch_adzuna_jobs(settings)
        + fetch_jsearch_jobs(settings)
    )
