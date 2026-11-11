"""Extract text from PDF resumes."""
from __future__ import annotations

from pathlib import Path

from ..utils.config import resolve_project_path


def extract_resume_text(pdf_path: str | Path) -> str:
    """Extract plain text from a PDF resume using PyMuPDF (fitz)."""
    resolved = resolve_project_path(pdf_path)
    if not resolved.exists():
        raise FileNotFoundError(
            f"Resume PDF not found at '{resolved}'. "
            "Place your master resume PDF at config/resume.pdf."
        )

    import pymupdf

    pages: list[str] = []
    with pymupdf.open(str(resolved)) as doc:
        for page in doc:
            text = page.get_text("text")
            if text:
                pages.append(text.strip())

    combined = "\n\n".join(pages).strip()
    if not combined:
        raise ValueError(f"No selectable text could be extracted from '{resolved}'.")
    return combined
