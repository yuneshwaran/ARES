# AresJobSearch

AI-powered job search, resume tailoring, application tracking, and optional auto-apply automation for Windows (100% free-tier compatible).

## Features

1. **Multi-Board Discovery** (`python-jobspy` + The Muse + optional Adzuna/JSearch) with fuzzy deduplication across LinkedIn, Indeed, Glassdoor, ZipRecruiter, and Google Jobs.
2. **Gemini AI Match Scoring** — scores discovered jobs (0–100) against your master `config/resume.pdf` and filters out low matches.
3. **Resume & Cover Letter Tailoring** — rewrites summary and bullets truthfully per job description using Jinja2 HTML templates rendered to ATS-friendly PDFs.
4. **Gmail Status Tracking & Excel Tracker** — polls Gmail for recruiter emails, classifies status (`applied`, `interview`, `rejected`, `offer`) via regex + Gemini AI, and updates `data/tracker.xlsx` (plus optional Google Sheets sync).
5. **Playwright Auto-Apply** — supports Greenhouse, Lever, and generic ATS forms with a default **review-before-submit** safety gate and daily rate limits.
6. **Windows Task Scheduler** — PowerShell setup script to run discovery and email tracking automatically on a schedule.

## Setup

### 1. Install Dependencies

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m playwright install chromium
```

### 2. Provide Your Resources

Run the checklist helper:

```powershell
.\venv\Scripts\python.exe scripts\first_run.py
```

Required / optional files in `config/`:
- `config/resume.pdf` *(mandatory for scoring & tailoring)* — your master resume PDF.
- `config/.env` — copy from `config/.env.example` and add your free `GEMINI_API_KEY` from Google AI Studio.
- `config/credentials.json` *(needed for Gmail / Google Sheets)* — OAuth 2.0 Desktop App client secrets from Google Cloud Console.
- `config/settings.yaml` — customize `search.titles`, `search.locations`, `boards`, `scoring`, `apply`, and `tracker`.
- `config/profile.yaml` — fill in your personal info and custom answers before using `apply`.

## Usage

```powershell
# Discover new jobs
.\venv\Scripts\python.exe main.py search

# Score new jobs against config/resume.pdf
.\venv\Scripts\python.exe main.py score

# Generate tailored resumes & cover letters for top jobs
.\venv\Scripts\python.exe main.py tailor

# Open pre-filled applications in review mode
.\venv\Scripts\python.exe main.py apply --mode review

# Check Gmail for recruiter replies and update Excel tracker
.\venv\Scripts\python.exe main.py check-email

# Export/sync SQLite jobs to data/tracker.xlsx (and Google Sheets if enabled)
.\venv\Scripts\python.exe main.py sync-tracker

# View terminal dashboard
.\venv\Scripts\python.exe main.py dashboard

# Launch HTML/CSS Web Monitoring Console (opens http://127.0.0.1:8501)
.\venv\Scripts\python.exe main.py web

# Inspect configuration and test Gemini + Discord webhook
.\venv\Scripts\python.exe main.py test-config --live

# Run full pipeline
.\venv\Scripts\python.exe main.py run all
```

## Windows Scheduling

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
```

## Testing

```powershell
.\venv\Scripts\python.exe -m pytest tests -v
```
