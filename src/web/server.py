"""Lightweight HTTP server and JSON API for the AresJobSearch web monitoring console."""
from __future__ import annotations

import json
import logging
import mimetypes
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import or_

from ..database.models import EmailRecord, Job, JobStatus, RunLog
from ..database.repository import get_daily_application_count, get_session
from ..tracker.excel_writer import ExcelTracker
from ..utils.config import LOGS_DIR, PROJECT_ROOT, load_settings
from ..utils.config_check import inspect_local_config, run_live_integration_tests

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_ACTIONS = {"search", "score", "tailor", "check-email", "sync-tracker"}


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


def _serialize_job(job: Job, include_description: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": job.id,
        "external_id": job.external_id,
        "title": job.title,
        "company": job.company,
        "location": job.location or "",
        "url": job.apply_url or job.url or "",
        "source": job.source or "",
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "job_type": job.job_type or "",
        "match_score": job.match_score,
        "score_reasoning": job.score_reasoning or "",
        "status": job.status.value,
        "date_posted": _iso(job.date_posted),
        "date_discovered": _iso(job.date_discovered),
        "date_applied": _iso(job.date_applied),
        "tailored_resume_path": job.tailored_resume_path or "",
        "cover_letter_path": job.cover_letter_path or "",
        "last_email_date": _iso(job.last_email_date),
        "last_email_subject": job.last_email_subject or "",
        "notes": job.notes or "",
    }
    if include_description:
        data["description"] = job.description or ""
    return data


def _serialize_email(rec: EmailRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "gmail_id": rec.gmail_id,
        "job_id": rec.job_id,
        "sender": rec.sender or "",
        "subject": rec.subject or "",
        "snippet": rec.snippet or "",
        "date_received": _iso(rec.date_received),
        "classified_status": rec.classified_status.value if rec.classified_status else "unknown",
    }


def _serialize_run(log: RunLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "run_type": log.run_type,
        "started_at": _iso(log.started_at),
        "finished_at": _iso(log.finished_at),
        "jobs_found": log.jobs_found or 0,
        "jobs_applied": log.jobs_applied or 0,
        "errors": log.errors or "",
        "status": log.status,
    }


def _tail_log_file(log_path: Path, max_lines: int = 120) -> list[str]:
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


class TaskRunner:
    """Runs CLI pipeline commands in a background subprocess without blocking the HTTP server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "action": "",
            "started_at": "",
            "finished_at": "",
            "exit_code": None,
            "output": "",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self, action: str) -> tuple[bool, str]:
        if action not in ALLOWED_ACTIONS:
            return False, f"Unsupported action: {action}"

        with self._lock:
            if self._state["running"]:
                return False, f"Action '{self._state['action']}' is already running."
            self._state = {
                "running": True,
                "action": action,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": "",
                "exit_code": None,
                "output": f"Starting `main.py {action}`...",
            }

        thread = threading.Thread(target=self._run_worker, args=(action,), daemon=True)
        thread.start()
        return True, f"Started `{action}` in background."

    def _run_worker(self, action: str) -> None:
        cmd = [sys.executable, str(PROJECT_ROOT / "main.py"), action]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=600,
            )
            combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            code = proc.returncode
        except Exception as exc:
            combined = str(exc)
            code = 1

        with self._lock:
            self._state["running"] = False
            self._state["finished_at"] = datetime.now().isoformat(timespec="seconds")
            self._state["exit_code"] = code
            self._state["output"] = combined[-4000:]


class WebConsoleHandler(BaseHTTPRequestHandler):
    """HTTP handler serving the HTML/CSS/JS console and JSON monitoring API."""

    def __init__(
        self,
        *args: Any,
        db_path: Path | str | None = None,
        excel_path: Path | str | None = None,
        task_runner: TaskRunner | None = None,
        **kwargs: Any,
    ) -> None:
        self.db_path = db_path
        self.excel_path = excel_path
        self.task_runner = task_runner or TaskRunner()
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("WebConsole: " + format, *args)

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        mime, _ = mimetypes.guess_type(str(file_path))
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._send_file(STATIC_DIR / "index.html")
            return

        if path.startswith("/static/"):
            rel = path.removeprefix("/static/").lstrip("/")
            candidate = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in candidate.parents:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            self._send_file(candidate)
            return

        if path == "/api/overview":
            self._handle_overview()
            return

        if path == "/api/jobs":
            self._handle_jobs(qs)
            return

        if path.startswith("/api/jobs/"):
            job_id_str = path.removeprefix("/api/jobs/")
            if job_id_str.isdigit():
                self._handle_job_detail(int(job_id_str))
                return

        if path == "/api/emails":
            limit = int((qs.get("limit") or ["40"])[0])
            session = get_session(self.db_path)
            try:
                rows = (
                    session.query(EmailRecord)
                    .order_by(EmailRecord.date_received.desc().nullslast(), EmailRecord.id.desc())
                    .limit(limit)
                    .all()
                )
                self._send_json({"emails": [_serialize_email(r) for r in rows]})
            finally:
                session.close()
            return

        if path == "/api/runs":
            limit = int((qs.get("limit") or ["30"])[0])
            session = get_session(self.db_path)
            try:
                rows = session.query(RunLog).order_by(RunLog.id.desc()).limit(limit).all()
                self._send_json({"runs": [_serialize_run(r) for r in rows]})
            finally:
                session.close()
            return

        if path == "/api/logs":
            lines = int((qs.get("lines") or ["120"])[0])
            self._send_json({"lines": _tail_log_file(LOGS_DIR / "ares.log", max_lines=lines)})
            return

        if path == "/api/config-health":
            self._send_json(inspect_local_config())
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/jobs/status":
            self._handle_update_job_status()
            return

        if path == "/api/test-config":
            body = self._read_json_body()
            results = run_live_integration_tests(
                test_gemini=bool(body.get("gemini", True)),
                test_discord=bool(body.get("discord", True)),
            )
            self._send_json({"results": results})
            return

        if path.startswith("/api/actions/"):
            action = path.removeprefix("/api/actions/")
            ok, msg = self.task_runner.start(action)
            status = HTTPStatus.ACCEPTED if ok else HTTPStatus.BAD_REQUEST
            self._send_json({"ok": ok, "message": msg, "task": self.task_runner.status()}, status=status)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def _handle_overview(self) -> None:
        settings = load_settings()
        apply_cfg = settings.get("apply", {})
        session = get_session(self.db_path)
        try:
            counts = {
                s.value: session.query(Job).filter(Job.status == s).count()
                for s in JobStatus
            }
            total = sum(counts.values())
            daily_applied = get_daily_application_count(session)
            max_daily = int(apply_cfg.get("max_daily_applications", 25))
            latest_runs = session.query(RunLog).order_by(RunLog.id.desc()).limit(5).all()
            self._send_json(
                {
                    "total_jobs": total,
                    "counts": counts,
                    "daily_applied": daily_applied,
                    "max_daily_applications": max_daily,
                    "apply_mode": apply_cfg.get("mode", "review"),
                    "apply_enabled": bool(apply_cfg.get("enabled", False)),
                    "recent_runs": [_serialize_run(r) for r in latest_runs],
                    "task": self.task_runner.status(),
                }
            )
        finally:
            session.close()

    def _handle_jobs(self, qs: dict[str, list[str]]) -> None:
        status_filter = (qs.get("status") or ["all"])[0].lower()
        q = (qs.get("q") or [""])[0].strip()
        min_score_raw = (qs.get("min_score") or [""])[0].strip()
        limit = int((qs.get("limit") or ["150"])[0])

        session = get_session(self.db_path)
        try:
            query = session.query(Job)
            if status_filter and status_filter != "all":
                try:
                    query = query.filter(Job.status == JobStatus(status_filter))
                except ValueError:
                    self._send_json({"error": f"Invalid status: {status_filter}"}, status=HTTPStatus.BAD_REQUEST)
                    return

            if min_score_raw:
                try:
                    min_score = float(min_score_raw)
                    if min_score > 0:
                        query = query.filter(Job.match_score >= min_score)
                except ValueError:
                    pass

            if q:
                like_pat = f"%{q}%"
                query = query.filter(
                    or_(
                        Job.title.ilike(like_pat),
                        Job.company.ilike(like_pat),
                        Job.location.ilike(like_pat),
                        Job.source.ilike(like_pat),
                    )
                )

            jobs = (
                query.order_by(Job.match_score.desc().nullslast(), Job.id.desc())
                .limit(limit)
                .all()
            )
            self._send_json({"jobs": [_serialize_job(j) for j in jobs]})
        finally:
            session.close()

    def _handle_job_detail(self, job_id: int) -> None:
        session = get_session(self.db_path)
        try:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                self._send_json({"error": "Job not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"job": _serialize_job(job, include_description=True)})
        finally:
            session.close()

    def _handle_update_job_status(self) -> None:
        body = self._read_json_body()
        job_id = body.get("id")
        new_status_raw = str(body.get("status", "")).lower()

        try:
            new_status = JobStatus(new_status_raw)
        except ValueError:
            self._send_json({"error": f"Invalid status: {new_status_raw}"}, status=HTTPStatus.BAD_REQUEST)
            return

        session = get_session(self.db_path)
        try:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                self._send_json({"error": "Job not found"}, status=HTTPStatus.NOT_FOUND)
                return

            job.status = new_status
            if new_status == JobStatus.APPLIED and not job.date_applied:
                job.date_applied = datetime.now()
            session.commit()

            settings = load_settings()
            target_excel = self.excel_path or settings.get("tracker", {}).get("excel_path", "data/tracker.xlsx")
            tracker = ExcelTracker(target_excel)
            tracker.add_application(
                {
                    "date_applied": job.date_applied or job.date_discovered,
                    "company": job.company,
                    "title": job.title,
                    "location": job.location,
                    "source": job.source,
                    "match_score": job.match_score,
                    "status": job.status.value,
                    "url": job.apply_url or job.url,
                    "resume_path": job.tailored_resume_path,
                }
            )
            self._send_json({"ok": True, "job": _serialize_job(job)})
        finally:
            session.close()


def create_server(
    host: str = "127.0.0.1",
    port: int = 8501,
    db_path: Path | str | None = None,
    excel_path: Path | str | None = None,
) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer configured for the web console."""
    runner = TaskRunner()
    handler = partial(WebConsoleHandler, db_path=db_path, excel_path=excel_path, task_runner=runner)
    return ThreadingHTTPServer((host, port), handler)


def run_web_console(
    host: str = "127.0.0.1",
    port: int = 8501,
    open_browser: bool = True,
    db_path: Path | str | None = None,
) -> None:
    """Start the web console server and block until Ctrl+C."""
    server = create_server(host=host, port=port, db_path=db_path)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"
    logger.info("AresJobSearch Web Console running at %s", url)
    print(f"AresJobSearch Web Console running at {url} (Press Ctrl+C to stop)")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web console...")
    finally:
        server.server_close()
