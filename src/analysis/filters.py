"""Hard criteria filters for discovered jobs (before AI scoring to save quota)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def passes_hard_filters(job: dict[str, Any], settings: dict[str, Any]) -> tuple[bool, str]:
    """Check whether a job meets hard criteria in settings['search'].

    Returns (True, "") if accepted, or (False, reason) if filtered out.
    """
    search_cfg = settings.get("search", {})
    company = (job.get("company") or "").strip().lower()
    title = (job.get("title") or "").strip().lower()
    description = (job.get("description") or "").strip().lower()
    combined_text = f"{title}\n{description}"

    # 1. Excluded companies
    for excluded in search_cfg.get("exclude_companies", []) or []:
        if excluded and excluded.strip().lower() in company:
            return False, f"Excluded company: {excluded}"

    # 2. Excluded keywords
    for kw in search_cfg.get("exclude_keywords", []) or []:
        if kw and kw.strip().lower() in combined_text:
            return False, f"Excluded keyword: {kw}"

    # 3. Required keywords (all must appear if description is present)
    required = [kw.strip().lower() for kw in (search_cfg.get("required_keywords") or []) if kw]
    if required and description:
        missing = [kw for kw in required if kw not in combined_text]
        if missing:
            return False, f"Missing required keywords: {', '.join(missing)}"

    # 4. Minimum salary (only reject if job explicitly lists a max below salary_min)
    salary_min_req = float(search_cfg.get("salary_min") or 0)
    job_salary_max = job.get("salary_max")
    if salary_min_req > 0 and job_salary_max is not None:
        try:
            if float(job_salary_max) > 0 and float(job_salary_max) < salary_min_req:
                return False, f"Salary max {job_salary_max} below minimum {salary_min_req}"
        except (TypeError, ValueError):
            pass

    return True, ""
