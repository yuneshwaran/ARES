"""Map candidate profile fields to common ATS form inputs and custom questions."""
from __future__ import annotations

import logging
from typing import Any

from ..utils.ai_client import GeminiClient

logger = logging.getLogger(__name__)


def build_field_mapping(profile: dict[str, Any]) -> list[tuple[str, str]]:
    """Build ordered (CSS selector, value) pairs from profile.yaml."""
    personal = profile.get("personal", {})
    experience = profile.get("experience", {})
    education = profile.get("education", {})

    full_name = f"{personal.get('first_name', '')} {personal.get('last_name', '')}".strip()

    raw_pairs = [
        (
            'input[name*="first" i][name*="name" i], input[id*="first" i][id*="name" i], input[autocomplete="given-name"]',
            personal.get("first_name", ""),
        ),
        (
            'input[name*="last" i][name*="name" i], input[id*="last" i][id*="name" i], input[autocomplete="family-name"]',
            personal.get("last_name", ""),
        ),
        (
            'input[name="name"], input[id="name"], input[autocomplete="name"]',
            full_name,
        ),
        (
            'input[type="email"], input[name*="email" i], input[id*="email" i]',
            personal.get("email", ""),
        ),
        (
            'input[type="tel"], input[name*="phone" i], input[id*="phone" i]',
            personal.get("phone", ""),
        ),
        (
            'input[name*="linkedin" i], input[id*="linkedin" i], input[placeholder*="linkedin" i]',
            personal.get("linkedin_url", ""),
        ),
        (
            'input[name*="github" i], input[id*="github" i], input[placeholder*="github" i]',
            personal.get("github_url", ""),
        ),
        (
            'input[name*="portfolio" i], input[name*="website" i], input[id*="website" i]',
            personal.get("portfolio_url", ""),
        ),
        (
            'input[name*="city" i], input[id*="city" i], input[name*="location" i]',
            personal.get("city", ""),
        ),
        (
            'input[name*="company" i], input[id*="current_company" i]',
            experience.get("current_company", ""),
        ),
        (
            'input[name*="university" i], input[name*="school" i]',
            education.get("university", ""),
        ),
    ]

    return [(sel, str(val).strip()) for sel, val in raw_pairs if val and str(val).strip()]


def answer_custom_question(
    question_text: str,
    profile: dict[str, Any],
    job_context: dict[str, Any] | None = None,
    ai_client: GeminiClient | None = None,
) -> str:
    """Resolve an application question from cached custom_answers or Gemini AI."""
    q_clean = (question_text or "").strip()
    if not q_clean:
        return ""

    custom_answers = profile.get("custom_answers", {}) or {}
    for cached_q, cached_a in custom_answers.items():
        if cached_q.lower() in q_clean.lower() or q_clean.lower() in cached_q.lower():
            if str(cached_a).strip().upper() != "AI_GENERATE":
                return str(cached_a)

    # Fallback to Gemini if available
    if ai_client is None:
        try:
            ai_client = GeminiClient()
        except Exception:
            return ""

    job_info = job_context or {}
    prompt = (
        "Answer this job application question concisely (1-3 sentences, truthful to the profile).\n"
        f"Question: {q_clean}\n"
        f"Role: {job_info.get('title', '')} at {job_info.get('company', '')}\n"
        f"Candidate experience: {profile.get('experience', {})}\n"
        f"Candidate skills: {profile.get('skills', [])}\n"
        "Return ONLY the answer text."
    )
    try:
        return ai_client.generate_text(prompt).strip()
    except Exception as exc:
        logger.warning("Failed to generate answer for '%s': %s", q_clean, exc)
        return ""
