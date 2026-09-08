from __future__ import annotations

import os
import re
from docx import Document


def parse_allocation_docx(file_path: str) -> list[dict]:
    """
    Parses departmental allocation Word document (.docx).
    Dynamically finds the 'LECTURER' and 'CODE' columns in each table
    regardless of merged cells or formatting differences.
    """
    doc = Document(file_path)
    allocations = []

    for table in doc.tables:
        header_map = {}
        header_row_idx = None

        # 1. Detect the table header row
        for row_idx, row in enumerate(table.rows[:5]):
            row_texts = [cell.text.strip().lower() for cell in row.cells]
            for col_idx, text in enumerate(row_texts):
                if "code" in text:
                    header_map["code"] = col_idx
                elif "title" in text:
                    header_map["title"] = col_idx
                elif "lecturer" in text or "instructor" in text:
                    header_map["lecturer"] = col_idx

            if "code" in header_map and "lecturer" in header_map:
                header_row_idx = row_idx
                break

        # If no explicit header was found, skip this table
        if header_row_idx is None:
            continue

        code_col = header_map["code"]
        title_col = header_map.get("title")
        lecturer_col = header_map["lecturer"]

        # 2. Extract rows using distinct cell boundaries
        for row in table.rows[header_row_idx + 1:]:
            cells = row.cells
            # Filter out duplicate merged cell references in python-docx
            unique_cells = []
            for cell in cells:
                if not unique_cells or cell._tc != unique_cells[-1]._tc:
                    unique_cells.append(cell)

            if len(unique_cells) <= max(code_col, lecturer_col):
                continue

            raw_code = unique_cells[code_col].text.strip()
            raw_lecturer = unique_cells[lecturer_col].text.strip()
            raw_title = (
                unique_cells[title_col].text.strip()
                if title_col is not None and len(unique_cells) > title_col
                else ""
            )

            # Check if this row has a valid course code format (e.g. COSC 434)
            compact_code = re.sub(r"[^A-Z0-9]", "", raw_code.upper())
            if not re.match(r"^[A-Z]{3,4}\d{3,5}", compact_code):
                continue

            # If the extracted lecturer text accidentally equals the course title,
            # search across cells for teacher indicators like (FT), (PT), Dr., etc.
            if raw_title and raw_lecturer.strip().lower() == raw_title.strip().lower():
                for c in unique_cells:
                    t = c.text.strip()
                    if re.search(r"\(FT\)|\(PT\)|Dr\.|Prof\.|Mr\.|Mrs\.", t, re.IGNORECASE):
                        raw_lecturer = t
                        break

            # Ignore non-lecturer headers or co-ordination placeholders
            if not raw_lecturer or "co-ordination" in raw_lecturer.lower() or "total" in raw_code.lower():
                continue

            allocations.append({
                "unit_code": compact_code,
                "raw_unit_code": raw_code,
                "unit_title": raw_title,
                "lecturer_name": raw_lecturer,
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
