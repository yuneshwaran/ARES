"""Tests for CLI commands and form mapper."""
from __future__ import annotations

from click.testing import CliRunner

import main
from src.applier.browser_agent import select_ats_handler
from src.applier.form_mapper import answer_custom_question, build_field_mapping


def test_form_mapper_and_ats_selector():
    profile = {
        "personal": {
            "first_name": "Yunes",
            "last_name": "Doe",
            "email": "yunes@example.com",
            "phone": "1234567890",
        },
        "custom_answers": {
            "When can you start?": "Immediately",
        },
    }
    mappings = build_field_mapping(profile)
    assert any(val == "yunes@example.com" for _, val in mappings)
    assert answer_custom_question("When can you start?", profile) == "Immediately"
    assert select_ats_handler("https://boards.greenhouse.io/acme/jobs/1").__name__ == "fill_greenhouse_form"
    assert select_ats_handler("https://jobs.lever.co/acme/1").__name__ == "fill_lever_form"
    assert select_ats_handler("https://careers.acme.com/apply").__name__ == "fill_generic_form"


def test_cli_help_and_dashboard(tmp_path, monkeypatch):
    runner = CliRunner()
    res = runner.invoke(main.cli, ["--help"])
    assert res.exit_code == 0
    assert "search" in res.output
    assert "check-email" in res.output
    assert "dashboard" in res.output

    # Point get_session to temp DB for dashboard test
    from src.database.repository import get_session

    monkeypatch.setattr(main, "get_session", lambda: get_session(tmp_path / "cli_test.db"))
    dash_res = runner.invoke(main.cli, ["dashboard"])
    assert dash_res.exit_code == 0
    normalized_out = " ".join(dash_res.output.split())
    assert "AresJobSearch Status Summary" in normalized_out
