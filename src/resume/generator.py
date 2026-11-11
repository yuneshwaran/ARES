"""Generate ATS-friendly PDF resumes and cover letters from tailored structured data."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_html(data: dict[str, Any], template_name: str = "modern.html") -> str:
    """Render structured resume or cover letter data to HTML using Jinja2."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template(template_name)
    return template.render(**data)


def _html_to_pdf_weasyprint(html_content: str, output_path: Path) -> None:
    from weasyprint import HTML  # type: ignore

    HTML(string=html_content).write_pdf(str(output_path))


def _html_to_pdf_playwright(html_content: str, output_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html_content, wait_until="load")
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={"top": "0.4in", "bottom": "0.4in", "left": "0.45in", "right": "0.45in"},
            )
        finally:
            browser.close()


def _html_to_pdf_fitz(data: dict[str, Any], output_path: Path) -> None:
    """Zero-browser pure-PyMuPDF fallback PDF renderer if neither WeasyPrint nor Chromium is available."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 in points
    lines: list[str] = [
        str(data.get("name", "")),
        str(data.get("contact_line", "")),
        "",
    ]
    if data.get("summary"):
        lines += ["PROFESSIONAL SUMMARY", str(data["summary"]), ""]
    if data.get("skills"):
        lines += ["SKILLS", ", ".join(str(s) for s in data["skills"]), ""]
    for exp in data.get("experience", []):
        lines.append(f"{exp.get('title', '')} - {exp.get('company', '')} ({exp.get('dates', '')})")
        for b in exp.get("bullets", []):
            lines.append(f"  * {b}")
        lines.append("")
    for para in data.get("paragraphs", []):
        lines += [str(para), ""]

    text = "\n".join(line for line in lines if line is not None)
    rect = pymupdf.Rect(42, 42, 553, 800)
    page.insert_textbox(rect, text, fontsize=10, fontname="helv")
    doc.save(str(output_path))
    doc.close()


def generate_pdf(
    data: dict[str, Any],
    output_path: str | Path,
    template_name: str = "modern.html",
) -> Path:
    """Render structured data into a PDF file using best available Windows-friendly backend."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    html_content = render_html(data, template_name=template_name)

    # Try WeasyPrint first (works if GTK is present), then Playwright Chromium, then PyMuPDF fallback
    for backend_name, runner in (
        ("weasyprint", lambda: _html_to_pdf_weasyprint(html_content, out)),
        ("playwright", lambda: _html_to_pdf_playwright(html_content, out)),
        ("pymupdf", lambda: _html_to_pdf_fitz(data, out)),
    ):
        try:
            runner()
            logger.info("Generated PDF via %s: %s", backend_name, out)
            return out
        except Exception as exc:
            logger.debug("PDF backend '%s' unavailable/failed (%s), trying next", backend_name, exc)

    raise RuntimeError(f"All PDF generation backends failed for {out}")
