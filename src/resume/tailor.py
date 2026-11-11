"""Tailor resume content and cover letters to specific job descriptions using Gemini."""
from __future__ import annotations

import logging
from typing import Any

from ..utils.ai_client import GeminiClient

logger = logging.getLogger(__name__)

TAILOR_PROMPT = """You are a professional resume writer. Given the candidate's original resume
and a target job description, rewrite the resume summary and bullet points to better match the
job requirements while keeping ALL information 100% truthful.

Rules:
- Do NOT invent experience, roles, degrees, metrics, or skills the candidate does not have.
- DO rephrase bullets to highlight relevant accomplishments using keywords from the job description.
- DO reorder skills and bullets to put the most relevant qualifications first.
- Output ONLY valid JSON matching this schema:
{{
    "name": "Candidate Full Name",
    "contact_line": "email | phone | city | linkedin | github",
    "summary": "2-3 sentence tailored professional summary",
    "experience": [
        {{
            "title": "Job Title",
            "company": "Company Name",
            "dates": "Start - End",
            "location": "City, Country",
            "bullets": ["Action verb + task + impact", "..."]
        }}
    ],
    "projects": [
        {{
            "name": "Project Name",
            "tech": "Tech stack",
            "bullets": ["...", "..."]
        }}
    ],
    "skills": ["skill1", "skill2"],
    "education": [
        {{"degree": "...", "school": "...", "year": "..."}}
    ]
}}

Original Resume:
{resume_text}

Target Job:
Title: {job_title}
Company: {company}
Description: {job_description}
"""

COVER_LETTER_PROMPT = """You are a professional career coach. Write a concise, tailored cover letter
(3-4 short paragraphs, ~250-300 words) based ONLY on the candidate's real background in the resume.

Rules:
- Do NOT fabricate experience or skills.
- Address the specific role and company naturally.
- Output ONLY valid JSON:
{{
    "name": "Candidate Full Name",
    "contact_line": "email | phone | city",
    "date": "Today's date or Current",
    "recipient": "Hiring Team",
    "company": "{company}",
    "role": "{job_title}",
    "paragraphs": ["Opening paragraph...", "Body paragraph 1...", "Body paragraph 2...", "Closing paragraph..."]
}}

Resume:
{resume_text}

Target Job:
Title: {job_title}
Company: {company}
Description: {job_description}
"""


class ResumeTailor:
    """Use Gemini to tailor resumes and cover letters per job posting."""

    def __init__(
        self,
        model_name: str = "gemini-2.0-flash",
        ai_client: GeminiClient | None = None,
    ):
        self.ai = ai_client or GeminiClient(model_name=model_name)

    def tailor(self, resume_text: str, job: dict[str, Any]) -> dict[str, Any]:
        """Return structured tailored resume content as a dict."""
        prompt = TAILOR_PROMPT.format(
            resume_text=(resume_text or "")[:4000],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=str(job.get("description", ""))[:4500],
        )
        data = self.ai.generate_json(prompt)
        data.setdefault("name", "Candidate")
        data.setdefault("contact_line", "")
        data.setdefault("summary", "")
        data.setdefault("experience", [])
        data.setdefault("projects", [])
        data.setdefault("skills", [])
        data.setdefault("education", [])
        return data

    def generate_cover_letter(self, resume_text: str, job: dict[str, Any]) -> dict[str, Any]:
        """Return structured cover letter content as a dict."""
        prompt = COVER_LETTER_PROMPT.format(
            resume_text=(resume_text or "")[:4000],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=str(job.get("description", ""))[:4500],
        )
        data = self.ai.generate_json(prompt)
        data.setdefault("name", "Candidate")
        data.setdefault("contact_line", "")
        data.setdefault("recipient", "Hiring Team")
        data.setdefault("company", job.get("company", ""))
        data.setdefault("role", job.get("title", ""))
        data.setdefault("paragraphs", [])
        return data
