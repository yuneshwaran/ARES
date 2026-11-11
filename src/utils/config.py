"""Configuration and environment loading utilities."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Resolve project root reliably regardless of working directory (Task Scheduler safe)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

_env_loaded = False


def ensure_env_loaded(env_path: Path | None = None) -> None:
    """Load environment variables from config/.env once (or from a custom path)."""
    global _env_loaded
    if env_path is not None:
        load_dotenv(dotenv_path=env_path, override=True)
        _env_loaded = True
        return
    if not _env_loaded:
        default_env = CONFIG_DIR / ".env"
        if default_env.exists():
            load_dotenv(dotenv_path=default_env, override=False)
        _env_loaded = True


def load_env(key: str, default: str | None = None) -> str | None:
    """Load an environment variable after ensuring config/.env is loaded."""
    ensure_env_loaded()
    return os.getenv(key, default)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return a dict (empty dict if file is empty)."""
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def load_settings(path: Path | str | None = None) -> dict[str, Any]:
    """Load application settings from config/settings.yaml."""
    target = Path(path) if path else CONFIG_DIR / "settings.yaml"
    return load_yaml(target)


def load_profile(path: Path | str | None = None) -> dict[str, Any]:
    """Load candidate profile from config/profile.yaml."""
    target = Path(path) if path else CONFIG_DIR / "profile.yaml"
    return load_yaml(target)


def resolve_project_path(relative_or_abs: str | Path) -> Path:
    """Resolve a relative path against PROJECT_ROOT, leaving absolute paths untouched."""
    p = Path(relative_or_abs)
    return p if p.is_absolute() else PROJECT_ROOT / p
