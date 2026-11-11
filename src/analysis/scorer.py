"""Score job-resume match using Google Gemini AI."""
from __future__ import annotations

import logging
from typing import Any

from ..utils.ai_client import GeminiClient

logger = logging.getLogger(__name__)

SCORING_PROMPT = """You are a job-resume match evaluator. Given a job description and a candidate's
resume text, score the match from 0 to 100 and explain why.

Consider:
- Skills alignment (hard & soft skills)
- Experience level match
- Industry relevance
- Location compatibility
- Job title alignment with career trajectory

Respond ONLY with valid JSON:
{{
    "score": <integer 0-100>,
    "reasoning": "<2-3 sentence explanation>",
    "missing_skills": ["skill1", "skill2"],
    "strong_matches": ["match1", "match2"]
}}

RESUME:
{resume_text}

JOB POSTING:
Title: {job_title}
Company: {company}
Location: {location}
Description: {job_description}
"""


class JobScorer:
    """Evaluate how well a candidate's resume matches a job posting."""

    def __init__(
        self,
        model_name: str = "gemini-2.0-flash",
        ai_client: GeminiClient | None = None,
    ):
        self.ai = ai_client or GeminiClient(model_name=model_name)

    def score_job(self, resume_text: str, job: dict[str, Any]) -> dict[str, Any]:
        """Score a single job against the resume. Returns dict with score & reasoning."""
        prompt = SCORING_PROMPT.format(
            resume_text=(resume_text or "")[:3500],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            job_description=str(job.get("description", ""))[:4500],
        )

        try:
            result = self.ai.generate_json(prompt)
            raw_score = float(result.get("score", 50))
            result["score"] = max(0.0, min(100.0, raw_score))
            result.setdefault("reasoning", "")
            result.setdefault("missing_skills", [])
            result.setdefault("strong_matches", [])
            return result
        except Exception as exc:
            logger.error(
                "Scoring failed for %s at %s: %s",
                job.get("title"),
                job.get("company"),
                exc,
            )
            return {
                "score": 50.0,
                "reasoning": f"Scoring failed ({exc}); defaulted to 50.",
                "missing_skills": [],
                "strong_matches": [],
            }
