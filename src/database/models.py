"""SQLAlchemy ORM models for AresJobSearch."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class JobStatus(enum.Enum):
    NEW = "new"
    SCORED = "scored"
    SKIPPED = "skipped"
    RESUME_TAILORED = "resume_tailored"
    READY_TO_APPLY = "ready_to_apply"
    APPLIED = "applied"
    REJECTED = "rejected"
    INTERVIEW = "interview"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    company = Column(String, nullable=False)
    location = Column(String, default="")
    description = Column(Text, default="")
    url = Column(String, default="")
    apply_url = Column(String, default="")
    source = Column(String, default="")
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    job_type = Column(String, default="")
    date_posted = Column(DateTime, nullable=True)
    date_discovered = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Scoring
    match_score = Column(Float, nullable=True)
    score_reasoning = Column(Text, default="")

    # Application tracking
    status = Column(SAEnum(JobStatus), default=JobStatus.NEW, nullable=False, index=True)
    date_applied = Column(DateTime, nullable=True)
    tailored_resume_path = Column(String, default="")
    cover_letter_path = Column(String, default="")

    # Email tracking
    last_email_date = Column(DateTime, nullable=True)
    last_email_subject = Column(String, default="")

    notes = Column(Text, default="")

    emails = relationship("EmailRecord", back_populates="job", cascade="all, delete-orphan")


class EmailRecord(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True)
    gmail_id = Column(String, unique=True, nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    sender = Column(String, default="")
    subject = Column(String, default="")
    snippet = Column(Text, default="")
    date_received = Column(DateTime, nullable=True)
    classified_status = Column(SAEnum(JobStatus), nullable=True)
    raw_body = Column(Text, default="")

    job = relationship("Job", back_populates="emails")


class RunLog(Base):
    __tablename__ = "run_logs"

    id = Column(Integer, primary_key=True)
    run_type = Column(String, nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)
    jobs_found = Column(Integer, default=0)
    jobs_applied = Column(Integer, default=0)
    errors = Column(Text, default="")
    status = Column(String, default="running")
