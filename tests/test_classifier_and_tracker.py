"""Tests for email classification, Gmail payload extraction, DB matching, and Excel tracker."""
from __future__ import annotations

import base64
from pathlib import Path

from src.database.models import Job, JobStatus
from src.database.repository import find_matching_job, get_session
from src.tracker.classifier import (
    classify_email,
    classify_email_fast,
    extract_company_from_sender,
)
from src.tracker.excel_writer import ExcelTracker
from src.tracker.gmail_client import _extract_body_from_payload


def test_fast_email_classification():
    assert classify_email_fast("Thank you for applying", "We have received your application.") == "applied"
    assert (
        classify_email_fast(
            "Next steps with Stripe",
            "We would love to schedule a call for an interview next week.",
        )
        == "interview"
    )
    assert (
        classify_email_fast(
            "Update on your application",
            "Unfortunately, we are not moving forward with your candidacy.",
        )
        == "rejected"
    )
    assert (
        classify_email_fast(
            "Exciting news!",
            "Congratulations! We are pleased to offer you the Software Engineer role.",
        )
        == "offer"
    )


def test_extract_company_from_sender():
    assert extract_company_from_sender("Stripe Recruiting <recruiting@stripe.com>") == "Stripe"
    assert extract_company_from_sender("Acme Careers <no-reply@greenhouse.io>") == "Acme"


def test_hybrid_classify_email_without_ai():
    result = classify_email(
        {
            "from": "Stripe Recruiting <jobs@stripe.com>",
            "subject": "Interview invitation",
            "body": "Let's schedule an interview for your Backend Engineer application.",
        },
        use_ai_fallback=False,
    )
    assert result["company_name"] == "Stripe"
    assert result["status"] == "interview"


def test_gmail_payload_extraction():
    encoded = base64.urlsafe_b64encode(b"Hello candidate, let's schedule an interview.").decode()
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": encoded}},
        ],
    }
    assert "schedule an interview" in _extract_body_from_payload(payload)


def test_excel_tracker_and_db_matching(tmp_path: Path):
    db_path = tmp_path / "test.db"
    session = get_session(db_path)
    job = Job(
        external_id="abc123",
        title="Backend Software Engineer",
        company="Stripe",
        status=JobStatus.APPLIED,
    )
    session.add(job)
    session.commit()

    matched = find_matching_job(session, "Stripe", "Backend Engineer")
    assert matched is not None
    assert matched.id == job.id
    session.close()

    xlsx_path = tmp_path / "tracker.xlsx"
    tracker = ExcelTracker(xlsx_path)
    tracker.add_application(
        {
            "date_applied": "2026-11-10",
            "company": "Stripe",
            "title": "Backend Software Engineer",
            "location": "Remote",
            "source": "linkedin",
            "match_score": 91,
            "status": "applied",
            "url": "https://stripe.com/jobs/1",
        }
    )
    # Deduplicated update on re-add
    tracker.add_application(
        {
            "company": "Stripe",
            "title": "Backend Software Engineer",
            "status": "applied",
            "url": "https://stripe.com/jobs/1",
        }
    )
    rows = tracker.read_all_rows()
    assert len(rows) == 2  # Header + 1 row

    updated = tracker.update_status(
        company="Stripe",
        role="Backend Engineer",
        new_status="interview",
        email_date="2026-11-11",
        email_subject="Interview Invitation",
    )
    assert updated is True
    rows_after = tracker.read_all_rows()
    assert rows_after[1][6] == "interview"
    assert rows_after[1][9] == "2026-11-11"
    assert rows_after[1][10] == "Interview Invitation"
