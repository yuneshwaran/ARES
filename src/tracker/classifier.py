"""Classify recruiter emails into application statuses using regex + Gemini fallback."""
from __future__ import annotations

import logging
import re
from typing import Any

from ..utils.ai_client import GeminiClient

logger = logging.getLogger(__name__)

# Ordered by priority (offer > interview > rejected > applied)
STATUS_PATTERNS: dict[str, list[str]] = {
    "offer": [
        r"\boffer letter\b",
        r"\bpleased to offer\b",
        r"\bextend an offer\b",
        r"\bcongratulations\b",
        r"\bwelcome to the team\b",
        r"\bcompensation package\b",
    ],
    "interview": [
        r"\bschedule (?:a |an )?(?:call|interview|chat)\b",
        r"\binvite you to (?:an )?interview\b",
        r"\binterview\b",
        r"\bavailability\b",
        r"\bnext steps\b",
        r"\brecruiter screen\b",
        r"\bphone screen\b",
        r"\btechnical assessment\b",
        r"\bcoding challenge\b",
    ],
    "rejected": [
        r"\bunfortunately\b",
        r"\bnot moving forward\b",
        r"\bother candidates\b",
        r"\bnot selected\b",
        r"\bregret to inform\b",
        r"\bposition has been filled\b",
        r"\bdecided not to proceed\b",
        r"\bnot a match\b",
        r"\bwill not be advancing\b",
    ],
    "applied": [
        r"\bapplication received\b",
        r"\bthank you for applying\b",
        r"\bthanks for applying\b",
        r"\bsuccessfully submitted\b",
        r"\bwe have received your application\b",
    ],
}

_FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "greenhouse.io",
    "lever.co",
    "workday.com",
    "myworkday.com",
    "ashbyhq.com",
    "smartrecruiters.com",
    "icims.com",
    "jobvite.com",
}


def extract_company_from_sender(sender: str) -> str:
    """Best-effort company name extraction from an email From header."""
    if not sender:
        return ""
    # e.g., "Stripe Recruiting <recruiting@stripe.com>"
    display_match = re.match(r'^"?([^"<]+)"?\s*<', sender.strip())
    domain_match = re.search(r"@([A-Za-z0-9.-]+)", sender)
    if domain_match:
        domain = domain_match.group(1).lower()
        if domain not in _FREE_EMAIL_DOMAINS and not any(domain.endswith(f".{d}") for d in _FREE_EMAIL_DOMAINS):
            parts = domain.split(".")
            if len(parts) >= 2:
                return parts[-2].capitalize()
    if display_match:
        name = display_match.group(1).strip()
        for noise in ("recruiting", "talent", "careers", "hiring", "team", "jobs", "hr"):
            name = re.sub(rf"\b{noise}\b", "", name, flags=re.IGNORECASE).strip(" -|")
        return name
    return ""


def classify_email_fast(subject: str, body: str) -> str | None:
    """Quick regex classification. Returns status string or None if uncertain."""
    text = f"{subject or ''}\n{body or ''}".lower()
    for status, patterns in STATUS_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return status
    return None


def classify_email_ai(
    subject: str,
    body: str,
    sender: str = "",
    ai_client: GeminiClient | None = None,
) -> dict[str, Any]:
    """Use Gemini to extract company, role, and status from an email."""
    client = ai_client or GeminiClient()
    prompt = f"""Classify this job-application-related email. Extract:
- company_name: The hiring company name (empty string if unknown)
- role_title: The job role being discussed (empty string if unknown)
- status: One of ["applied", "interview", "rejected", "offer", "unknown"]

Sender: {sender}
Email subject: {subject}
Email body (truncated): {(body or '')[:1500]}

Respond ONLY with valid JSON:
{{"company_name": "...", "role_title": "...", "status": "..."}}"""

    try:
        result = client.generate_json(prompt)
        status = str(result.get("status", "unknown")).lower()
        if status not in {"applied", "interview", "rejected", "offer", "unknown"}:
            status = "unknown"
        return {
            "company_name": str(result.get("company_name", "")).strip(),
            "role_title": str(result.get("role_title", "")).strip(),
            "status": status,
        }
    except Exception as exc:
        logger.warning("AI email classification failed: %s", exc)
        return {
            "company_name": extract_company_from_sender(sender),
            "role_title": "",
            "status": "unknown",
        }


def classify_email(
    email_data: dict[str, Any],
    ai_client: GeminiClient | None = None,
    use_ai_fallback: bool = True,
) -> dict[str, Any]:
    """Hybrid classifier: fast regex first, AI fallback for company/role or uncertain status."""
    subject = email_data.get("subject", "")
    body = email_data.get("body", "") or email_data.get("snippet", "")
    sender = email_data.get("from", "")

    fast_status = classify_email_fast(subject, body)
    company_guess = extract_company_from_sender(sender)

    if fast_status and company_guess:
        return {
            "company_name": company_guess,
            "role_title": "",
            "status": fast_status,
        }

    if use_ai_fallback:
        try:
            ai_res = classify_email_ai(subject, body, sender=sender, ai_client=ai_client)
            if fast_status and ai_res.get("status") == "unknown":
                ai_res["status"] = fast_status
            if not ai_res.get("company_name") and company_guess:
                ai_res["company_name"] = company_guess
            return ai_res
        except Exception as exc:
            logger.debug("Skipping AI email fallback: %s", exc)

    return {
        "company_name": company_guess,
        "role_title": "",
        "status": fast_status or "unknown",
    }
