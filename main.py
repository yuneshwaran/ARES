"""AresJobSearch — AI-Powered Job Search Automation CLI."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from src.database.models import Job, JobStatus
from src.database.repository import (
    find_matching_job,
    finish_run_log,
    get_daily_application_count,
    get_existing_external_ids,
    get_session,
    record_email_if_new,
    start_run_log,
)
from src.utils.config import DATA_DIR, load_profile, load_settings, resolve_project_path
from src.utils.logging_setup import setup_logging

console = Console()
logger = logging.getLogger(__name__)


def _safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", (text or "").strip()).strip("_")[:50] or "job"


def _parse_date(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    text = str(val).strip()
    if not text or text.lower() in ("nan", "nat", "none"):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except Exception:
        return None


def _to_float_or_none(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        num = float(val)
        return None if num != num else num  # NaN check
    except (TypeError, ValueError):
        return None


def _sync_sheets_if_enabled(settings: dict[str, Any], tracker: Any) -> None:
    tracker_cfg = settings.get("tracker", {})
    if tracker_cfg.get("sheets_sync") and tracker_cfg.get("sheets_id"):
        from src.tracker.sheets_sync import sync_excel_to_sheets

        sync_excel_to_sheets(
            tracker,
            sheet_id=tracker_cfg["sheets_id"],
            worksheet_name=tracker_cfg.get("sheets_worksheet", "Applications"),
        )


@click.group()
def cli() -> None:
    """AresJobSearch — AI-Powered Job Search Automation."""
    setup_logging()


@cli.command()
@click.option("--dry-run", is_flag=True, help="Scrape and filter without saving to database.")
@click.option("--limit", type=int, default=0, help="Limit number of new jobs processed (0 = all).")
def search(dry_run: bool, limit: int) -> None:
    """Discover new jobs across configured boards and APIs."""
    from src.analysis.filters import passes_hard_filters
    from src.discovery.api_scraper import fetch_all_api_jobs
    from src.discovery.deduplicator import deduplicate_jobs, generate_job_id
    from src.discovery.jobspy_scraper import scrape_all_boards

    settings = load_settings()
    session = get_session()
    run_log = None if dry_run else start_run_log(session, "discovery")

    try:
        existing_ids = get_existing_external_ids(session)
        console.print("[bold blue]Scraping job boards...[/]")

        raw_jobs = scrape_all_boards(settings, limit=limit) + fetch_all_api_jobs(settings)
        if not raw_jobs:
            console.print("[yellow]No jobs found. Try adjusting your search criteria.[/]")
            if run_log:
                finish_run_log(session, run_log, jobs_found=0)
            return

        jobs = deduplicate_jobs(raw_jobs, existing_ids)
        if limit > 0:
            jobs = jobs[:limit]

        added = 0
        filtered_out = 0
        for row in jobs:
            job_dict = {
                "title": str(row.get("title", "")),
                "company": str(row.get("company", "")),
                "location": str(row.get("location", "")),
                "description": str(row.get("description", "")),
                "salary_max": row.get("max_amount"),
            }
            accepted, reason = passes_hard_filters(job_dict, settings)
            if not accepted:
                filtered_out += 1
                logger.debug("Filtered out %s @ %s: %s", job_dict["title"], job_dict["company"], reason)
                continue

            if not dry_run:
                job = Job(
                    external_id=str(
                        row.get("external_id")
                        or generate_job_id(job_dict["title"], job_dict["company"])
                    ),
                    title=job_dict["title"],
                    company=job_dict["company"],
                    location=job_dict["location"],
                    description=job_dict["description"],
                    url=str(row.get("job_url", "") or ""),
                    apply_url=str(row.get("job_url_direct", "") or row.get("job_url", "") or ""),
                    source=str(row.get("site", "") or ""),
                    salary_min=_to_float_or_none(row.get("min_amount")),
                    salary_max=_to_float_or_none(row.get("max_amount")),
                    job_type=str(row.get("job_type", "") or ""),
                    date_posted=_parse_date(row.get("date_posted")),
                )
                session.add(job)
            added += 1

        if not dry_run:
            session.commit()
            if run_log:
                finish_run_log(session, run_log, jobs_found=added)

        prefix = "[DRY RUN] " if dry_run else ""
        console.print(
            f"[green]{prefix}Discovered {added} matching new jobs ({filtered_out} filtered out).[/]"
        )
    except Exception as exc:
        logger.exception("Search failed")
        if run_log:
            finish_run_log(session, run_log, errors=str(exc), status="failed")
        raise click.ClickException(str(exc)) from exc
    finally:
        session.close()


@cli.command()
@click.option("--limit", type=int, default=0, help="Max unscored jobs to evaluate (0 = all).")
@click.option("--resume", default="config/resume.pdf", help="Path to master resume PDF.")
def score(limit: int, resume: str) -> None:
    """Score newly discovered jobs against your resume using Gemini AI."""
    from src.analysis.scorer import JobScorer
    from src.notifications.notifier import notify
    from src.resume.parser import extract_resume_text

    settings = load_settings()
    scoring_cfg = settings.get("scoring", {})
    min_score = float(scoring_cfg.get("min_match_score", 60))
    model_name = scoring_cfg.get("gemini_model", "gemini-2.0-flash")

    resume_text = extract_resume_text(resume)
    session = get_session()
    try:
        query = session.query(Job).filter(Job.status == JobStatus.NEW).order_by(Job.id.asc())
        if limit > 0:
            query = query.limit(limit)
        unscored = query.all()

        if not unscored:
            console.print("[yellow]No new unscored jobs in database.[/]")
            return

        scorer = JobScorer(model_name=model_name)
        console.print(f"[blue]Scoring {len(unscored)} jobs with {model_name}...[/]")

        high_matches: list[str] = []
        for job in unscored:
            result = scorer.score_job(
                resume_text,
                {
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "description": job.description,
                },
            )
            job.match_score = float(result.get("score", 0))
            job.score_reasoning = str(result.get("reasoning", ""))
            job.status = JobStatus.SCORED if job.match_score >= min_score else JobStatus.SKIPPED

            tag = "HIGH" if job.match_score >= 80 else "OK" if job.match_score >= min_score else "LOW"
            console.print(f"  [{tag}] {job.match_score:.0f}% — {job.title} @ {job.company}")
            if job.match_score >= 80:
                high_matches.append(f"{job.title} @ {job.company} ({job.match_score:.0f}%)")

        session.commit()
        console.print("[green]Scoring complete.[/]")
        if high_matches:
            notify(
                settings,
                f"AresJobSearch: {len(high_matches)} High-Match Jobs",
                "\n".join(high_matches[:5]),
            )
    finally:
        session.close()


@cli.command()
@click.option("--limit", type=int, default=10, help="Max scored jobs to tailor resumes for.")
@click.option("--resume", default="config/resume.pdf", help="Path to master resume PDF.")
def tailor(limit: int, resume: str) -> None:
    """Generate tailored PDF resumes (and optional cover letters) for top-scored jobs."""
    from src.resume.generator import generate_pdf
    from src.resume.parser import extract_resume_text
    from src.resume.tailor import ResumeTailor

    settings = load_settings()
    scoring_cfg = settings.get("scoring", {})
    apply_cfg = settings.get("apply", {})
    min_score = float(scoring_cfg.get("min_match_score", 60))
    model_name = scoring_cfg.get("gemini_model", "gemini-2.0-flash")

    resume_text = extract_resume_text(resume)
    tailor_ai = ResumeTailor(model_name=model_name)
    resumes_dir = DATA_DIR / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)

    session = get_session()
    try:
        jobs = (
            session.query(Job)
            .filter(Job.status == JobStatus.SCORED)
            .filter(Job.match_score >= min_score)
            .order_by(Job.match_score.desc())
            .limit(limit)
            .all()
        )
        if not jobs:
            console.print("[yellow]No scored jobs ready for resume tailoring.[/]")
            return

        for job in jobs:
            slug = f"{job.id}_{_safe_filename(job.company)}_{_safe_filename(job.title)}"
            job_dict = {
                "title": job.title,
                "company": job.company,
                "description": job.description,
            }
            tailored_data = tailor_ai.tailor(resume_text, job_dict)
            resume_out = resumes_dir / f"{slug}_resume.pdf"
            generate_pdf(tailored_data, resume_out, template_name="modern.html")
            job.tailored_resume_path = str(resume_out)

            if apply_cfg.get("generate_cover_letter", True):
                cl_data = tailor_ai.generate_cover_letter(resume_text, job_dict)
                cl_out = resumes_dir / f"{slug}_cover_letter.pdf"
                generate_pdf(cl_data, cl_out, template_name="cover_letter.html")
                job.cover_letter_path = str(cl_out)

            job.status = JobStatus.READY_TO_APPLY
            console.print(f"[green]Tailored resume generated: {resume_out.name}[/]")

        session.commit()
    finally:
        session.close()


@cli.command("apply")
@click.option("--limit", type=int, default=5, help="Max jobs to apply to in this run.")
@click.option(
    "--mode",
    type=click.Choice(["review", "semi_auto", "full_auto"]),
    default=None,
    help="Override apply.mode from settings.yaml.",
)
def apply_cmd(limit: int, mode: str | None) -> None:
    """Auto-fill (and optionally submit) applications using Playwright."""
    from src.applier.browser_agent import ApplicationAgent
    from src.tracker.excel_writer import ExcelTracker

    settings = load_settings()
    profile = load_profile()
    apply_cfg = settings.get("apply", {})
    scoring_cfg = settings.get("scoring", {})

    effective_mode = mode or apply_cfg.get("mode", "review")
    max_daily = int(apply_cfg.get("max_daily_applications", 25))
    delay_cfg = apply_cfg.get("delay_between_actions_sec", [2, 5])
    delay_range = (float(delay_cfg[0]), float(delay_cfg[1]))

    session = get_session()
    tracker = ExcelTracker(settings.get("tracker", {}).get("excel_path", "data/tracker.xlsx"))
    run_log = start_run_log(session, "apply")

    try:
        applied_today = get_daily_application_count(session)
        remaining = max(0, max_daily - applied_today)
        if remaining == 0:
            console.print(f"[yellow]Daily application limit ({max_daily}) reached.[/]")
            finish_run_log(session, run_log, jobs_applied=0)
            return

        target_statuses = [JobStatus.READY_TO_APPLY, JobStatus.SCORED]
        query = (
            session.query(Job)
            .filter(Job.status.in_(target_statuses))
            .order_by(Job.match_score.desc().nullslast())
        )
        if effective_mode == "semi_auto":
            threshold = float(scoring_cfg.get("auto_apply_threshold", 85))
            query = query.filter(Job.match_score >= threshold)

        candidates = query.limit(min(limit, remaining)).all()
        if not candidates:
            console.print("[yellow]No eligible jobs ready to apply.[/]")
            finish_run_log(session, run_log, jobs_applied=0)
            return

        agent = ApplicationAgent(
            profile=profile,
            headless=bool(apply_cfg.get("headless", False)),
            delay_range=delay_range,
        )

        applied_count = 0
        default_resume = resolve_project_path("config/resume.pdf")

        for job in candidates:
            resume_to_use = job.tailored_resume_path or (
                str(default_resume) if default_resume.exists() else ""
            )
            target_url = job.apply_url or job.url
            console.print(f"[blue]Opening application: {job.title} @ {job.company}[/]")

            success = asyncio.run(
                agent.apply_to_job(
                    job_url=target_url,
                    resume_path=resume_to_use,
                    mode=effective_mode,
                    job_context={"title": job.title, "company": job.company},
                )
            )
            if success:
                now = datetime.now(timezone.utc)
                job.status = JobStatus.APPLIED
                job.date_applied = now
                tracker.add_application(
                    {
                        "date_applied": now.strftime("%Y-%m-%d"),
                        "company": job.company,
                        "title": job.title,
                        "location": job.location,
                        "source": job.source,
                        "match_score": job.match_score,
                        "status": "applied",
                        "url": target_url,
                        "resume_path": resume_to_use,
                    }
                )
                applied_count += 1

        session.commit()
        _sync_sheets_if_enabled(settings, tracker)
        finish_run_log(session, run_log, jobs_applied=applied_count)
        console.print(f"[green]Completed: {applied_count} applications recorded.[/]")
    except Exception as exc:
        logger.exception("Apply command failed")
        finish_run_log(session, run_log, errors=str(exc), status="failed")
        raise click.ClickException(str(exc)) from exc
    finally:
        session.close()


@cli.command("check-email")
def check_email() -> None:
    """Check Gmail for recruiter responses and update SQLite + Excel tracker."""
    from src.notifications.notifier import notify
    from src.tracker.classifier import classify_email
    from src.tracker.excel_writer import ExcelTracker
    from src.tracker.gmail_client import GmailClient

    settings = load_settings()
    email_cfg = settings.get("email", {})
    tracker = ExcelTracker(settings.get("tracker", {}).get("excel_path", "data/tracker.xlsx"))
    session = get_session()
    run_log = start_run_log(session, "email_check")

    try:
        gmail = GmailClient()
        query = email_cfg.get("search_query", "in:inbox")
        max_results = int(email_cfg.get("max_results", 30))

        console.print("[blue]Checking Gmail for recruiter updates...[/]")
        emails = gmail.search_emails(query=query, max_results=max_results)
        console.print(f"[green]Fetched {len(emails)} matching emails.[/]")

        updated = 0
        important_alerts: list[str] = []

        for email_data in emails:
            classification = classify_email(email_data)
            status_str = classification.get("status", "unknown")
            company = classification.get("company_name", "")
            role = classification.get("role_title", "")

            status_enum = None
            if status_str in ("applied", "interview", "rejected", "offer"):
                status_enum = JobStatus(status_str)

            matched_job = find_matching_job(session, company, role) if company else None
            is_new_email = record_email_if_new(session, email_data, matched_job, status_enum)
            if not is_new_email:
                continue

            if status_enum is not None:
                date_str = (
                    email_data["parsed_date"].strftime("%Y-%m-%d")
                    if email_data.get("parsed_date")
                    else datetime.now().strftime("%Y-%m-%d")
                )
                if matched_job is not None:
                    matched_job.status = status_enum
                    matched_job.last_email_date = email_data.get("parsed_date") or datetime.now(
                        timezone.utc
                    )
                    matched_job.last_email_subject = email_data.get("subject", "")

                if company:
                    tracker.update_status(
                        company=company,
                        role=role,
                        new_status=status_str,
                        email_date=date_str,
                        email_subject=email_data.get("subject", ""),
                    )

                updated += 1
                console.print(
                    f"  [{status_str.upper()}] {company or email_data['from']} — {email_data['subject']}"
                )
                if status_str in ("interview", "offer"):
                    important_alerts.append(f"{status_str.upper()}: {company} ({email_data['subject']})")

        session.commit()
        _sync_sheets_if_enabled(settings, tracker)
        finish_run_log(session, run_log, jobs_found=updated)
        console.print(f"[green]Processed {updated} new status updates.[/]")

        if important_alerts:
            notify(
                settings,
                "AresJobSearch: Recruiter Response!",
                "\n".join(important_alerts[:5]),
            )
    except Exception as exc:
        logger.exception("Email check failed")
        finish_run_log(session, run_log, errors=str(exc), status="failed")
        raise click.ClickException(str(exc)) from exc
    finally:
        session.close()


@cli.command("sync-tracker")
def sync_tracker() -> None:
    """Sync all tracked jobs from SQLite into Excel (and Google Sheets if enabled)."""
    from src.tracker.excel_writer import ExcelTracker

    settings = load_settings()
    tracker = ExcelTracker(settings.get("tracker", {}).get("excel_path", "data/tracker.xlsx"))
    session = get_session()
    try:
        jobs = (
            session.query(Job)
            .filter(Job.status != JobStatus.SKIPPED)
            .order_by(Job.match_score.desc().nullslast())
            .all()
        )
        for job in jobs:
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
                    "last_email_date": job.last_email_date.strftime("%Y-%m-%d")
                    if job.last_email_date
                    else "",
                    "last_email_subject": job.last_email_subject,
                    "notes": job.notes,
                }
            )
        _sync_sheets_if_enabled(settings, tracker)
        console.print(f"[green]Synced {len(jobs)} jobs to {tracker.path}[/]")
    finally:
        session.close()


@cli.command()
def dashboard() -> None:
    """Display job search status summary and top matches."""
    session = get_session()
    try:
        table = Table(title="AresJobSearch Status Summary")
        table.add_column("Status", style="bold cyan")
        table.add_column("Count", justify="right")

        total = 0
        for status in JobStatus:
            count = session.query(Job).filter(Job.status == status).count()
            total += count
            if count > 0:
                table.add_row(status.value.replace("_", " ").title(), str(count))
        table.add_row("Total", str(total), style="bold")
        console.print(table)

        top_jobs = (
            session.query(Job)
            .filter(Job.match_score.isnot(None))
            .order_by(Job.match_score.desc())
            .limit(10)
            .all()
        )
        if top_jobs:
            top_table = Table(title="Top Scored Jobs")
            top_table.add_column("Score", justify="right", style="green")
            top_table.add_column("Role", style="bold")
            top_table.add_column("Company")
            top_table.add_column("Status")
            for j in top_jobs:
                top_table.add_row(
                    f"{j.match_score:.0f}%",
                    j.title,
                    j.company,
                    j.status.value,
                )
            console.print(top_table)
    finally:
        session.close()


@cli.command()
@click.argument("mode", default="all")
@click.option("--dry-run", is_flag=True, help="Run discovery in dry-run mode without DB writes.")
def run(mode: str, dry_run: bool) -> None:
    """Run the end-to-end pipeline: search -> score -> tailor -> apply -> check-email."""
    ctx = click.get_current_context()
    settings = load_settings()

    if mode in ("all", "search"):
        ctx.invoke(search, dry_run=dry_run, limit=0)
    if dry_run:
        console.print("[yellow]Dry run finished after search.[/]")
        return

    if mode in ("all", "score"):
        resume_file = resolve_project_path("config/resume.pdf")
        if resume_file.exists():
            ctx.invoke(score, limit=0, resume=str(resume_file))
        else:
            console.print("[yellow]Skipping score/tailor: config/resume.pdf not found yet.[/]")

    if mode in ("all", "tailor"):
        resume_file = resolve_project_path("config/resume.pdf")
        if resume_file.exists():
            ctx.invoke(tailor, limit=5, resume=str(resume_file))

    if mode in ("all", "apply") and settings.get("apply", {}).get("enabled", False):
        ctx.invoke(apply_cmd, limit=5, mode=None)

    if mode in ("all", "email"):
        creds_file = resolve_project_path("config/credentials.json")
        if creds_file.exists():
            ctx.invoke(check_email)
        else:
            console.print("[yellow]Skipping check-email: config/credentials.json not found yet.[/]")

    ctx.invoke(dashboard)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host for web console.")
@click.option("--port", default=8501, type=int, show_default=True, help="Bind port for web console.")
@click.option("--no-browser", is_flag=True, help="Do not open the browser automatically.")
def web(host: str, port: int, no_browser: bool) -> None:
    """Launch the HTML/CSS web monitoring console."""
    from src.web.server import run_web_console

    run_web_console(host=host, port=port, open_browser=not no_browser)


@cli.command("test-config")
@click.option("--live", is_flag=True, help="Also send live test requests to Gemini API and Discord webhook.")
def test_config(live: bool) -> None:
    """Inspect local configs/credentials and optionally test live integrations."""
    from src.utils.config_check import inspect_local_config, run_live_integration_tests

    report = inspect_local_config()
    table = Table(title="AresJobSearch Configuration Health")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    for item in report["checks"]:
        status_txt = "[green]OK[/]" if item["ok"] else "[yellow]MISSING / CHECK[/]"
        table.add_row(item["name"], status_txt, item["detail"])
    console.print(table)

    if live:
        console.print("[blue]Running live integration tests (Gemini + Discord)...[/]")
        live_res = run_live_integration_tests(test_gemini=True, test_discord=True)
        for name, res in live_res.items():
            badge = "[green]PASS[/]" if res["ok"] else "[red]FAIL[/]"
            console.print(f"  {badge} {name.upper()}: {res['detail']}")


if __name__ == "__main__":
    cli()
