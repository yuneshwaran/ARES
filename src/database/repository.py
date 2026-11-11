"""Database engine, session factory, and CRUD repository helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from rapidfuzz import fuzz
from sqlalchemy import create_engine, func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..utils.config import DATA_DIR
from .models import Base, EmailRecord, Job, JobStatus, RunLog

DEFAULT_DB_PATH = DATA_DIR / "ares.db"


def get_engine(db_path: Path | str | None = None) -> Engine:
    """Create a SQLAlchemy engine for the SQLite database."""
    target = Path(db_path) if db_path else DEFAULT_DB_PATH
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{target.as_posix()}"
    else:
        url = "sqlite:///:memory:"
    engine = create_engine(url, echo=False, future=True)
    Base.metadata.create_all(engine)
    return engine


def get_session(db_path: Path | str | None = None) -> Session:
    """Create and return a new SQLAlchemy Session (auto-initializing schema)."""
    engine = get_engine(db_path)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def get_existing_external_ids(session: Session) -> set[str]:
    """Return all external_ids currently stored in the jobs table."""
    rows = session.query(Job.external_id).all()
    return {row[0] for row in rows if row[0]}


def get_daily_application_count(session: Session) -> int:
    """Count how many jobs have been applied to today (UTC)."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        session.query(func.count(Job.id))
        .filter(Job.date_applied >= today_start)
        .filter(Job.status.in_([JobStatus.APPLIED, JobStatus.INTERVIEW, JobStatus.OFFER, JobStatus.REJECTED]))
        .scalar()
        or 0
    )


def find_matching_job(
    session: Session,
    company: str,
    role_title: str = "",
    min_score: int = 70,
) -> Job | None:
    """Find the best matching job in DB by fuzzy company + optional role match."""
    if not company:
        return None

    company_clean = company.strip().lower()
    role_clean = role_title.strip().lower()

    candidates: Iterable[Job] = (
        session.query(Job)
        .filter(Job.status != JobStatus.SKIPPED)
        .order_by(Job.date_applied.desc().nullslast(), Job.date_discovered.desc())
        .all()
    )

    best_job: Job | None = None
    best_combined = 0.0

    for job in candidates:
        comp_score = fuzz.partial_ratio(company_clean, (job.company or "").lower())
        if comp_score < min_score:
            continue
        if role_clean:
            role_score = fuzz.token_set_ratio(role_clean, (job.title or "").lower())
            combined = 0.65 * comp_score + 0.35 * role_score
        else:
            combined = float(comp_score)

        # Prefer jobs that were already applied to
        if job.status in (JobStatus.APPLIED, JobStatus.INTERVIEW, JobStatus.OFFER):
            combined += 5.0

        if combined > best_combined:
            best_combined = combined
            best_job = job

    return best_job


def start_run_log(session: Session, run_type: str) -> RunLog:
    """Create and persist a RunLog entry."""
    log = RunLog(run_type=run_type, status="running")
    session.add(log)
    session.commit()
    return log


def finish_run_log(
    session: Session,
    log: RunLog,
    jobs_found: int = 0,
    jobs_applied: int = 0,
    errors: str = "",
    status: str = "completed",
) -> RunLog:
    """Update a RunLog entry when finished."""
    log.finished_at = datetime.now(timezone.utc)
    log.jobs_found = jobs_found
    log.jobs_applied = jobs_applied
    log.errors = errors
    log.status = status
    session.commit()
    return log


def record_email_if_new(session: Session, email_data: dict, job: Job | None, status: JobStatus | None) -> bool:
    """Store an email record if gmail_id isn't already recorded. Returns True if newly added."""
    gmail_id = email_data.get("id", "")
    if not gmail_id:
        return False
    exists = session.query(EmailRecord.id).filter(EmailRecord.gmail_id == gmail_id).first()
    if exists:
        return False

    rec = EmailRecord(
        gmail_id=gmail_id,
        job_id=job.id if job else None,
        sender=email_data.get("from", ""),
        subject=email_data.get("subject", ""),
        snippet=email_data.get("snippet", ""),
        date_received=email_data.get("parsed_date"),
        classified_status=status,
        raw_body=email_data.get("body", ""),
    )
    session.add(rec)
    session.commit()
    return True
