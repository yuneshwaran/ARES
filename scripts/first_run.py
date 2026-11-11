"""Interactive setup & diagnostics wizard for AresJobSearch."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def main() -> None:
    print("=== AresJobSearch Setup Checklist ===\n")

    env_file = CONFIG_DIR / ".env"
    env_example = CONFIG_DIR / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        print(f"[CREATED] {env_file} (copied from .env.example)")

    checks = [
        ("Master Resume PDF", CONFIG_DIR / "resume.pdf", "Place your resume PDF at config/resume.pdf"),
        ("Google OAuth Credentials", CONFIG_DIR / "credentials.json", "Download Desktop App credentials.json from Google Cloud Console"),
        ("Environment File (.env)", env_file, "Add GEMINI_API_KEY in config/.env"),
        ("Search Settings", CONFIG_DIR / "settings.yaml", "Review job titles, locations, and boards"),
        ("Candidate Profile", CONFIG_DIR / "profile.yaml", "Fill in personal info for form auto-fill"),
    ]

    all_ready = True
    for label, path, hint in checks:
        exists = path.exists()
        status = "OK" if exists else "MISSING"
        print(f"[{status:7}] {label}: {path}")
        if not exists:
            print(f"          -> {hint}")
            all_ready = False

    print("\n=== Next Steps ===")
    if not all_ready:
        print("1. Complete any MISSING items above.")
    print("2. Run a dry-run search test: .\\venv\\Scripts\\python.exe main.py search --dry-run --limit 5")
    print("3. Run dashboard: .\\venv\\Scripts\\python.exe main.py dashboard")
    print("4. Register Windows schedule: powershell -ExecutionPolicy Bypass -File scripts\\setup_scheduler.ps1")


if __name__ == "__main__":
    sys.exit(main() or 0)
