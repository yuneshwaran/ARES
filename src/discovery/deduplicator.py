"""Deduplicate jobs across multiple sources using deterministic IDs and fuzzy matching."""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_CORP_SUFFIX_RE = re.compile(r"\b(inc|llc|ltd|corp|corporation|co|limited|pvt)\b")


def _normalize(text: str, strip_corp_suffix: bool = False) -> str:
    cleaned = _NON_ALNUM_RE.sub(" ", (text or "").lower())
    if strip_corp_suffix:
        cleaned = _CORP_SUFFIX_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def generate_job_id(title: str, company: str) -> str:
    """Generate a deterministic ID from normalized title + company."""
    normalized = f"{_normalize(title)}|{_normalize(company, strip_corp_suffix=True)}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def deduplicate_jobs(
    jobs: list[dict[str, Any]],
    existing_ids: set[str],
    fuzzy_threshold: int = 90,
) -> list[dict[str, Any]]:
    """Remove duplicate jobs (exact ID, fuzzy title+company within batch, and against DB)."""
    if not jobs:
        return []

    before = len(jobs)
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set(existing_ids)
    seen_pairs: list[tuple[str, str]] = []

    for job in jobs:
        title = str(job.get("title") or "").strip()
        company = str(job.get("company") or "").strip()
        if not title or not company:
            continue

        ext_id = generate_job_id(title, company)
        if ext_id in seen_ids:
            continue

        t_norm = _normalize(title)
        c_norm = _normalize(company, strip_corp_suffix=True)
        is_dup = any(
            fuzz.token_set_ratio(c_norm, seen_c) >= fuzzy_threshold
            and fuzz.token_sort_ratio(t_norm, seen_t) >= fuzzy_threshold
            for seen_t, seen_c in seen_pairs
        )
        if is_dup:
            continue

        seen_ids.add(ext_id)
        seen_pairs.append((t_norm, c_norm))
        enriched = dict(job)
        enriched["external_id"] = ext_id
        enriched["title"] = title
        enriched["company"] = company
        kept.append(enriched)

    logger.info("Deduplication: %d -> %d jobs (%d duplicates removed)", before, len(kept), before - len(kept))
    return kept
