"""Shared Google Gemini AI helper with JSON extraction."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import load_env

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_payload(raw_text: str) -> dict[str, Any]:
    """Parse JSON from an LLM response, stripping markdown code fences if present."""
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Empty response from LLM")

    match = _JSON_FENCE_RE.search(text)
    if match:
        text = match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: locate outermost {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(text[start : end + 1])
        else:
            raise

    if not isinstance(parsed, dict):
        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
    return parsed


class GeminiClient:
    """Thin wrapper around Google Gemini SDK (`google-genai` with `google-generativeai` fallback)."""

    def __init__(self, model_name: str = "gemini-2.0-flash", api_key: str | None = None):
        self.model_name = model_name
        self.api_key = api_key or load_env("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to config/.env or your environment."
            )

        self._backend: str
        self._client: Any

        try:
            from google import genai  # type: ignore

            self._client = genai.Client(api_key=self.api_key)
            self._backend = "google-genai"
        except ImportError:
            import google.generativeai as legacy_genai  # type: ignore

            legacy_genai.configure(api_key=self.api_key)
            self._client = legacy_genai.GenerativeModel(self.model_name)
            self._backend = "google-generativeai"

    def generate_text(self, prompt: str) -> str:
        """Generate text from Gemini."""
        if self._backend == "google-genai":
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            return response.text or ""
        response = self._client.generate_content(prompt)
        return getattr(response, "text", "") or ""

    def generate_json(self, prompt: str) -> dict[str, Any]:
        """Generate and parse a JSON object response from Gemini."""
        raw = self.generate_text(prompt)
        return extract_json_payload(raw)
