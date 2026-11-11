"""Tests for resume HTML rendering, PDF generation, and PDF text extraction."""
from __future__ import annotations

from pathlib import Path

from src.resume.generator import generate_pdf, render_html
from src.resume.parser import extract_resume_text
from src.resume.tailor import ResumeTailor


class _FakeTailorAI:
    def generate_json(self, prompt: str) -> dict:
        if "cover letter" in prompt.lower():
            return {
                "name": "Alex Rivera",
                "contact_line": "alex@example.com | +91-9999999999",
                "company": "Acme Corp",
                "role": "Backend Engineer",
                "paragraphs": ["Excited to apply for Backend Engineer at Acme Corp."],
            }
        return {
            "name": "Alex Rivera",
            "contact_line": "alex@example.com | github.com/alex",
            "summary": "Backend Engineer experienced with Python, SQL, and FastAPI.",
            "experience": [
                {
                    "title": "Software Engineer",
                    "company": "Beta Tech",
                    "dates": "2023 - Present",
                    "location": "Remote",
                    "bullets": ["Built scalable Python REST APIs serving 50k requests/day."],
                }
            ],
            "projects": [],
            "skills": ["Python", "SQL", "FastAPI"],
            "education": [{"degree": "B.Tech CS", "school": "State University", "year": "2023"}],
        }


def test_render_html_and_generate_and_parse_pdf(tmp_path: Path):
    tailor = ResumeTailor(ai_client=_FakeTailorAI())
    data = tailor.tailor("Original resume text", {"title": "Backend Engineer", "company": "Acme"})

    html = render_html(data, "modern.html")
    assert "Alex Rivera" in html
    assert "FastAPI" in html

    pdf_path = tmp_path / "tailored_resume.pdf"
    generated = generate_pdf(data, pdf_path, template_name="modern.html")
    assert generated.exists()
    assert generated.stat().st_size > 500

    extracted = extract_resume_text(generated)
    assert "Alex Rivera" in extracted
    assert "Python" in extracted

    cl_data = tailor.generate_cover_letter("Original resume", {"title": "Backend Engineer", "company": "Acme"})
    cl_pdf = tmp_path / "cover_letter.pdf"
    generate_pdf(cl_data, cl_pdf, template_name="cover_letter.html")
    assert cl_pdf.exists()
    assert "Acme Corp" in extract_resume_text(cl_pdf)
