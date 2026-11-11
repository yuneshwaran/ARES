"""Tests for web monitoring console HTTP API and configuration diagnostics."""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from click.testing import CliRunner

import main
from src.database.models import EmailRecord, Job, JobStatus, RunLog
from src.database.repository import get_session
from src.utils.config_check import inspect_local_config
from src.web.server import create_server


def _http_json(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_web_console_serves_html_css_and_api(tmp_path: Path):
    db_path = tmp_path / "web_test.db"
    excel_path = tmp_path / "web_tracker.xlsx"

    session = get_session(db_path)
    job = Job(
        external_id="web1",
        title="Backend Python Developer",
        company="Acme AI",
        location="Remote",
        source="remotive",
        match_score=91.0,
        score_reasoning="Strong Python and API match.",
        description="Build fast APIs with Python.",
        status=JobStatus.SCORED,
        url="https://example.com/jobs/1",
    )
    session.add(job)
    session.flush()
    session.add(
        EmailRecord(
            gmail_id="gm1",
            job_id=job.id,
            sender="jobs@acme.ai",
            subject="Application received",
            snippet="Thank you for applying",
            classified_status=JobStatus.APPLIED,
        )
    )
    session.add(RunLog(run_type="discovery", jobs_found=1, status="completed"))
    session.commit()
    job_id = job.id
    session.close()

    server = create_server(host="127.0.0.1", port=0, db_path=db_path, excel_path=excel_path)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(f"{base}/", timeout=5) as r:
            html = r.read().decode("utf-8")
            assert r.status == 200
            assert "AresJobSearch Console" in html

        with urllib.request.urlopen(f"{base}/static/styles.css", timeout=5) as r:
            css = r.read().decode("utf-8")
            assert r.status == 200
            assert "--bg:" in css

        status, overview = _http_json(f"{base}/api/overview")
        assert status == 200
        assert overview["total_jobs"] == 1
        assert overview["counts"]["scored"] == 1

        status, jobs_res = _http_json(f"{base}/api/jobs?status=scored&min_score=80&q=Acme")
        assert status == 200
        assert len(jobs_res["jobs"]) == 1
        assert jobs_res["jobs"][0]["company"] == "Acme AI"

        status, detail_res = _http_json(f"{base}/api/jobs/{job_id}")
        assert status == 200
        assert "Build fast APIs" in detail_res["job"]["description"]

        status, upd_res = _http_json(
            f"{base}/api/jobs/status",
            method="POST",
            body={"id": job_id, "status": "interview"},
        )
        assert status == 200
        assert upd_res["job"]["status"] == "interview"
        assert excel_path.exists()

        status, emails_res = _http_json(f"{base}/api/emails")
        assert status == 200
        assert len(emails_res["emails"]) == 1

        status, runs_res = _http_json(f"{base}/api/runs")
        assert status == 200
        assert len(runs_res["runs"]) == 1

        status, health_res = _http_json(f"{base}/api/config-health")
        assert status == 200
        assert "checks" in health_res
    finally:
        server.shutdown()
        server.server_close()


def test_config_check_and_cli_commands():
    report = inspect_local_config()
    ids = {c["id"] for c in report["checks"]}
    assert {"settings", "profile", "resume", "gemini_key", "discord", "credentials", "gmail_token", "storage"} <= ids

    runner = CliRunner()
    res = runner.invoke(main.cli, ["test-config"])
    assert res.exit_code == 0
    assert "AresJobSearch" in res.output

    web_help = runner.invoke(main.cli, ["web", "--help"])
    assert web_help.exit_code == 0
    assert "--port" in web_help.output
