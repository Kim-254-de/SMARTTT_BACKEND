from __future__ import annotations

import os
import re
from docx import Document


def _get_unique_cells(row):
    """Filters out python-docx duplicate references to merged cells."""
    unique = []
    for cell in row.cells:
        if not unique or cell._tc != unique[-1]._tc:
            unique.append(cell)
    return unique


def parse_allocation_docx(file_path: str) -> list[dict]:
    """
    Parses departmental allocation Word document (.docx).
    Works reliably across tables with merged cells and varying columns.
    """
    doc = Document(file_path)
    allocations = []

    for table in doc.tables:
        header_row_idx = None
        code_idx = None
        title_idx = None
        lecturer_idx = None

        # 1. Locate table header using unique cells
        for row_idx, row in enumerate(table.rows[:6]):
            cells = _get_unique_cells(row)
            texts = [c.text.strip().lower() for c in cells]

            c_idx = None
            t_idx = None
            l_idx = None

            for idx, text in enumerate(texts):
                if "code" in text:
                    c_idx = idx
                elif "title" in text:
                    t_idx = idx
                elif "lecturer" in text or "instructor" in text:
                    l_idx = idx

            if c_idx is not None and l_idx is not None:
                header_row_idx = row_idx
                code_idx = c_idx
                title_idx = t_idx
                lecturer_idx = l_idx
                break

        if header_row_idx is None:
            continue

        # 2. Extract rows using the detected unique cell indices
        for row in table.rows[header_row_idx + 1:]:
            cells = _get_unique_cells(row)
            if len(cells) <= max(code_idx, lecturer_idx):
                continue

            raw_code = cells[code_idx].text.strip()
            compact_code = re.sub(r"[^A-Z0-9]", "", raw_code.upper())

            # Only process valid course codes (e.g., COSC 434, DIIT 0241)
            if not re.match(r"^[A-Z]{3,4}\d{3,5}", compact_code):
                continue

            raw_title = cells[title_idx].text.strip() if title_idx is not None and len(cells) > title_idx else ""
            raw_lecturer = cells[lecturer_idx].text.strip()

            # Guard: If raw_lecturer is a phone number, search all cells in the row for the lecturer's name
            phone_pattern = r"^(07\d{8}|01\d{8}|\+254\d+|254\d+)$"
            if re.match(phone_pattern, raw_lecturer.replace(" ", "")) or raw_lecturer.lower() == raw_title.lower():
                found_name = None
                for c in cells:
                    txt = c.text.strip()
                    # Skip code, title, numbers, credits
                    if txt == raw_code or txt == raw_title or re.match(r"^[\d\.\s\/]+$", txt):
                        continue
                    if re.match(phone_pattern, txt.replace(" ", "")):
                        continue
                    if re.search(r"\b(ft|pt|dr|prof|mr|mrs|ms)\b", txt, re.IGNORECASE) or any(
                        part in txt.lower() for part in ["mwema", "gogo", "kwenga", "mutisya", "wambui", "korir", "tuei", "karega"]
                    ):
                        found_name = txt
                        break
                if found_name:
                    raw_lecturer = found_name

            # Skip coordinators, empty entries, or invalid headers
            if not raw_lecturer or "co-ordination" in raw_lecturer.lower() or "total" in raw_code.lower():
                continue

            # Strip trailing phone numbers that might be appended to the lecturer name
            clean_lecturer = re.sub(r"07\d{8}|01\d{8}|\+254\d+", "", raw_lecturer).strip()

            allocations.append({
                "unit_code": compact_code,
                "raw_unit_code": raw_code,
                "unit_title": raw_title,
                "lecturer_name": clean_lecturer,
            })

    return allocations


def parse_allocation_pdf(file_obj) -> list[dict]:
    """PDF parser fallback if a PDF allocation file is uploaded."""
    import pypdf

    reader = pypdf.PdfReader(file_obj)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""

    rows = []
    lines = text.split("\n")
    for line in lines:
        match = re.search(r"([A-Z]{3,4}\s*\d{3,5})\s+(.+?)\s+([A-Z][a-zA-Z\s\.\(\)\/]+?)\s+(07\d{8}|01\d{8})?", line)
        if match:
            raw_code, raw_title, raw_lecturer = match.group(1), match.group(2), match.group(3)
            compact = re.sub(r"[^A-Z0-9]", "", raw_code.upper())
            if not any(k in raw_lecturer.lower() for k in ["total", "co-ordination"]):
                rows.append({
                    "unit_code": compact,
                    "raw_unit_code": raw_code.strip(),
                    "unit_title": raw_title.strip(),
                    "lecturer_name": raw_lecturer.strip(),
                })
    return rows
