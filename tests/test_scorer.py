"""Tests for Gemini AI JSON parsing and JobScorer."""
from __future__ import annotations

from src.analysis.scorer import JobScorer
from src.utils.ai_client import extract_json_payload


class _FakeAI:
    def __init__(self, response: dict | Exception):
        self._response = response

    def generate_json(self, prompt: str) -> dict:
        if isinstance(self._response, Exception):
            raise self._response
        return dict(self._response)


def test_extract_json_payload_with_markdown_fences():
    raw = '```json\n{"score": 88, "reasoning": "Strong Python fit"}\n```'
    parsed = extract_json_payload(raw)
    assert parsed["score"] == 88
    assert parsed["reasoning"] == "Strong Python fit"


def test_extract_json_payload_with_surrounding_prose():
    raw = 'Here is the analysis:\n{"score": 72, "reasoning": "Good match"}\nHope this helps!'
    parsed = extract_json_payload(raw)
    assert parsed["score"] == 72


def test_job_scorer_clamps_and_handles_errors():
    scorer = JobScorer(ai_client=_FakeAI({"score": 120, "reasoning": "Exact fit"}))
    res = scorer.score_job("Python developer resume", {"title": "Python Dev", "company": "Acme"})
    assert res["score"] == 100.0
    assert res["reasoning"] == "Exact fit"

    failing_scorer = JobScorer(ai_client=_FakeAI(RuntimeError("API quota")))
    res_fail = failing_scorer.score_job("Resume", {"title": "Dev", "company": "Acme"})
    assert res_fail["score"] == 50.0
    assert "Scoring failed" in res_fail["reasoning"]
