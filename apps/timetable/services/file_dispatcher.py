"""
Dispatches a timetable upload to the right format-specific parser based on
file extension, and normalises exceptions into ExcelParsingException so the
pipeline's existing error handling covers every format uniformly.
"""
from __future__ import annotations

import os

from apps.timetable.utils import ExcelParsingException


def parse_timetable_file(file_path: str) -> list[dict]:
    """
    Parse a timetable file (.xlsx, .xls, .csv, .pdf, .docx) into a list of
    normalised row dicts using canonical column names (program_code,
    room_code, lecturer_university_id, day_of_week, etc).
    """
    _, ext = os.path.splitext(file_path.lower())

    try:
        if ext in (".xlsx", ".xls"):
            from apps.timetable.services.excel_parser import parse_excel
            with open(file_path, "rb") as f:
                return parse_excel(f)

        if ext == ".csv":
            from apps.timetable.services.excel_parser import parse_csv
            with open(file_path, "rb") as f:
                return parse_csv(f)

        if ext == ".pdf":
            from apps.timetable.services.pdf_timetable_parser import parse_pdf
            with open(file_path, "rb") as f:
                return parse_pdf(f)

        if ext == ".docx":
            from apps.timetable.services.docx_timetable_parser import parse_docx
            return parse_docx(file_path)

        raise ExcelParsingException(f"Unsupported file extension: {ext}")

    except ExcelParsingException:
        raise
    except Exception as exc:
        raise ExcelParsingException(str(exc)) from exc
