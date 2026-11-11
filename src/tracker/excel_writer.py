"""Write and update the Excel (.xlsx) job application tracker."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from rapidfuzz import fuzz

from ..utils.config import resolve_project_path

STATUS_COLORS: dict[str, str] = {
    "new": "FFFFFF",
    "scored": "E3F2FD",
    "ready_to_apply": "E8EAF6",
    "applied": "FFF9C4",
    "interview": "C8E6C9",
    "rejected": "FFCDD2",
    "offer": "A5D6A7",
    "withdrawn": "CFD8DC",
}

COLUMNS: list[str] = [
    "Date Applied",
    "Company",
    "Role",
    "Location",
    "Source",
    "Match Score",
    "Status",
    "Application URL",
    "Resume Used",
    "Last Email Date",
    "Last Email Subject",
    "Notes",
]

COLUMN_WIDTHS: list[int] = [14, 22, 28, 20, 14, 13, 16, 36, 28, 18, 34, 30]


class ExcelTracker:
    """Manages the local Excel job application tracker."""

    def __init__(self, path: str | Path = "data/tracker.xlsx"):
        self.path = resolve_project_path(path)
        self._ensure_workbook()

    def _ensure_workbook(self) -> None:
        if self.path.exists():
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "Applications"

        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_fill = PatternFill(start_color="1565C0", end_color="1565C0", fill_type="solid")

        for col_idx, name in enumerate(COLUMNS, 1):
            cell = ws.cell(row=1, column=col_idx, value=name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.column_dimensions[get_column_letter(col_idx)].width = COLUMN_WIDTHS[col_idx - 1]

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}1"
        wb.save(str(self.path))

    def add_application(self, job_data: dict[str, Any]) -> int:
        """Append a new application row (or update if URL/company+role already tracked). Returns row index."""
        wb = load_workbook(str(self.path))
        ws = wb["Applications"]

        company = str(job_data.get("company", ""))
        title = str(job_data.get("title", ""))
        url = str(job_data.get("url", ""))
        status = str(job_data.get("status", "applied")).lower()

        # Prevent duplicate rows for same URL or exact company+role
        for row_idx in range(2, ws.max_row + 1):
            existing_company = str(ws.cell(row=row_idx, column=2).value or "")
            existing_role = str(ws.cell(row=row_idx, column=3).value or "")
            existing_url = str(ws.cell(row=row_idx, column=8).value or "")
            if (url and existing_url == url) or (
                existing_company.lower() == company.lower()
                and existing_role.lower() == title.lower()
            ):
                ws.cell(row=row_idx, column=7).value = status
                self._style_status_cell(ws.cell(row=row_idx, column=7), status)
                wb.save(str(self.path))
                return row_idx

        date_applied = job_data.get("date_applied") or datetime.now().strftime("%Y-%m-%d")
        if isinstance(date_applied, datetime):
            date_applied = date_applied.strftime("%Y-%m-%d")

        row_values = [
            date_applied,
            company,
            title,
            str(job_data.get("location", "")),
            str(job_data.get("source", "")),
            job_data.get("match_score", ""),
            status,
            url,
            str(job_data.get("resume_path", "")),
            str(job_data.get("last_email_date", "")),
            str(job_data.get("last_email_subject", "")),
            str(job_data.get("notes", "")),
        ]
        ws.append(row_values)
        row_num = ws.max_row
        self._style_status_cell(ws.cell(row=row_num, column=7), status)
        wb.save(str(self.path))
        return row_num

    def update_status(
        self,
        company: str,
        role: str = "",
        new_status: str = "applied",
        email_date: str = "",
        email_subject: str = "",
    ) -> bool:
        """Update status of the best-matching application row. Returns True if matched."""
        if not company:
            return False

        wb = load_workbook(str(self.path))
        ws = wb["Applications"]
        new_status_clean = new_status.lower()

        best_row_idx: int | None = None
        best_score = 0.0

        for row_idx in range(2, ws.max_row + 1):
            row_company = str(ws.cell(row=row_idx, column=2).value or "")
            row_role = str(ws.cell(row=row_idx, column=3).value or "")
            if not row_company:
                continue

            comp_score = fuzz.partial_ratio(company.lower(), row_company.lower())
            if comp_score < 75:
                continue

            if role:
                role_score = fuzz.token_set_ratio(role.lower(), row_role.lower())
                score = 0.65 * comp_score + 0.35 * role_score
            else:
                score = float(comp_score)

            if score > best_score:
                best_score = score
                best_row_idx = row_idx

        if best_row_idx is None:
            return False

        status_cell = ws.cell(row=best_row_idx, column=7)
        status_cell.value = new_status_clean
        self._style_status_cell(status_cell, new_status_clean)
        if email_date:
            ws.cell(row=best_row_idx, column=10).value = email_date
        if email_subject:
            ws.cell(row=best_row_idx, column=11).value = email_subject

        wb.save(str(self.path))
        return True

    def read_all_rows(self) -> list[list[Any]]:
        """Read header + all data rows from the Applications sheet."""
        wb = load_workbook(str(self.path), read_only=True)
        ws = wb["Applications"]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows

    @staticmethod
    def _style_status_cell(cell: Any, status: str) -> None:
        color = STATUS_COLORS.get(status.lower(), "FFFFFF")
        cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        cell.alignment = Alignment(horizontal="center")
