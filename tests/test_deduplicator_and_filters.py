"""Tests for job deduplication and hard criteria filtering."""
from __future__ import annotations

from src.analysis.filters import passes_hard_filters
from src.discovery.deduplicator import deduplicate_jobs, generate_job_id


def test_generate_job_id_deterministic():
    id1 = generate_job_id("Software Engineer!", "Acme Corp.")
    id2 = generate_job_id("software   engineer", "acme corp")
    assert id1 == id2
    assert len(id1) == 16


def test_deduplicate_removes_exact_fuzzy_and_existing():
    existing = {generate_job_id("Data Analyst", "OldCo")}
    jobs = [
        {"title": "Backend Engineer", "company": "Stripe", "site": "linkedin"},
        {"title": "Backend Engineer!", "company": "Stripe Inc", "site": "indeed"},
        {"title": "Backend Engineer", "company": "Stripe", "site": "glassdoor"},
        {"title": "Data Analyst", "company": "OldCo", "site": "linkedin"},
        {"title": "", "company": "EmptyTitleCo", "site": "indeed"},
    ]

    result = deduplicate_jobs(jobs, existing, fuzzy_threshold=85)
    assert len(result) == 1
    assert result[0]["company"] == "Stripe"


def test_hard_filters_exclude_and_require():
    settings = {
        "search": {
            "exclude_companies": ["Revature"],
            "exclude_keywords": ["clearance required"],
            "required_keywords": ["python"],
            "salary_min": 50000,
        }
    }

    ok, _ = passes_hard_filters(
        {
            "title": "Python Developer",
            "company": "GoodTech",
            "description": "Looking for Python and SQL skills.",
            "salary_max": 90000,
        },
        settings,
    )
    assert ok is True

    ok_comp, reason_comp = passes_hard_filters(
        {"title": "Python Dev", "company": "Revature LLC", "description": "Python"},
        settings,
    )
    assert ok_comp is False
    assert "Excluded company" in reason_comp

    ok_kw, _ = passes_hard_filters(
        {"title": "Python Dev", "company": "DefenseCo", "description": "Python, security clearance required"},
        settings,
    )
    assert ok_kw is False

    ok_req, _ = passes_hard_filters(
        {"title": "Java Dev", "company": "GoodTech", "description": "Java and Spring Boot only"},
        settings,
    )
    assert ok_req is False

    ok_sal, _ = passes_hard_filters(
        {"title": "Python Dev", "company": "LowPay", "description": "Python", "salary_max": 30000},
        settings,
    )
    assert ok_sal is False


def test_fetch_remotive_jobs_normalizes_payload(monkeypatch):
    from src.discovery.api_scraper import fetch_remotive_jobs

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "jobs": [
                    {
                        "title": "Python Engineer",
                        "company_name": "RemoteCo",
                        "candidate_required_location": "Worldwide",
                        "description": "<p>Build <b>APIs</b></p>",
                        "url": "https://remotive.com/jobs/1",
                        "publication_date": "2026-11-10T10:00:00",
                        "job_type": "full_time",
                    }
                ]
            }

    monkeypatch.setattr("src.discovery.api_scraper.requests.get", lambda *a, **kw: _FakeResp())
    jobs = fetch_remotive_jobs({"search": {"titles": ["Python"]}, "boards": {"remotive": {"enabled": True}}})
    assert len(jobs) == 1
    assert jobs[0]["company"] == "RemoteCo"
    assert jobs[0]["description"] == "Build  APIs"
    assert jobs[0]["site"] == "remotive"
