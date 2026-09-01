"""
timetable/services/file_dispatcher.py

Routes timetable files (.xlsx, .xls, .csv, .pdf, .docx) to their respective parsers.
"""

import os
from typing import List, Dict, Any

from apps.timetable.services.excel_parser import parse_excel
from apps.timetable.services.pdf_timetable_parser import parse_pdf, to_timetable_slot_dicts
from apps.timetable.services.docx_timetable_parser import parse_docx
from apps.timetable.utils import ExcelParsingException


def parse_timetable_file(file_path: str, academic_year: str = "2026/2027") -> List[Dict[str, Any]]:
    """
    Parse any supported timetable file format into normalized dictionary rows.
    """
    if not os.path.exists(file_path):
        raise ExcelParsingException(f"File not found: {file_path}")

    _, ext = os.path.splitext(file_path.lower())

    try:
        if ext in (".xlsx", ".xls", ".csv"):
            with open(file_path, "rb") as f:
                return parse_excel(f)

        elif ext == ".pdf":
            parsed_result = parse_pdf(file_path)
            return to_timetable_slot_dicts(parsed_result, academic_year=academic_year)

        elif ext == ".docx":
            return parse_docx(file_path)

        else:
            raise ExcelParsingException(
                f"Unsupported file extension: {ext}. "
                "Supported formats are .xlsx, .xls, .csv, .pdf, and .docx."
            )
    except ExcelParsingException:
        raise
    except Exception as e:
        raise ExcelParsingException(f"Failed to parse timetable file ({ext}): {str(e)}")
