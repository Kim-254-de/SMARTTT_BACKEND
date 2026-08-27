"""
Parses the department unit allocation DOCX file.

Document structure:
  - Multiple tables, each representing a program/year group
  - Table columns: Course code | Course Title | L | P | CF | LECTURER | PHONE NO.
  - Lecturer field format: "Name (FT)" or "Dr. Name (PT)"
  - We extract: unit_code, lecturer_name (cleaned), phone

Normalisation:
  - Unit codes: remove all spaces → "COSC 325" → "COSC325"
  - Lecturer names: strip titles (Dr., Mr., Mrs., Prof.), strip (FT)/(PT)
"""
from __future__ import annotations
import re


def _clean_lecturer_name(raw: str) -> str:
    """
    'Dr. Ann Wambui (FT)' → 'Ann Wambui'
    'Muriithi Njoroge (FT)' → 'Muriithi Njoroge'
    'Dr.Kwenga (FT)' → 'Kwenga'
    """
    name = re.sub(r'\(FT\)|\(PT\)|\(ft\)|\(pt\)', '', raw, flags=re.IGNORECASE)
    name = re.sub(r'\b(Dr\.?|Mr\.?|Mrs\.?|Ms\.?|Prof\.?)\s*', '', name, flags=re.IGNORECASE)
    return name.strip()


def _clean_phone(raw: str) -> str:
    """Normalise phone: '0720 694935' → '0720694935'"""
    return re.sub(r'\s+', '', str(raw).strip()) if raw else ''


def _normalise_code(code: str) -> str:
    """Remove spaces for matching: 'COSC 325' → 'COSC325'"""
    return re.sub(r'\s+', '', code.upper().strip())


def _is_header_row(cells: list[str]) -> bool:
    """Detect table header rows like 'Course code', 'Course Title' etc."""
    joined = ' '.join(cells).lower()
    return 'course code' in joined or 'course title' in joined


def _is_total_row(cells: list[str]) -> bool:
    return cells[0].strip().upper() == 'TOTAL'


def _process_allocation_table_rows(table_rows: list[list[str]]) -> list[dict]:
    """
    Shared row-processing logic for both DOCX and PDF allocation tables.
    Each item in table_rows is a list of cell strings for one table row.
    """
    results = []
    seen = set()  # (normalised_unit_code, lecturer_name) pairs

    for cells in table_rows:
        cells = [c.strip() if c else "" for c in cells]
        if not cells or not cells[0]:
            continue
        if _is_header_row(cells) or _is_total_row(cells):
            continue

        # Expect at least 6 columns: code, title, L, P, CF, lecturer
        if len(cells) < 6:
            continue

        raw_code = cells[0].strip()
        raw_lecturer = cells[5].strip() if len(cells) > 5 else ''
        raw_phone = cells[6].strip() if len(cells) > 6 else ''

        # Skip rows where code doesn't look like a unit code
        if not raw_code or not re.match(r'^[A-Z]{2,6}\s*\d', raw_code, re.IGNORECASE):
            continue

        # Skip rows with no lecturer
        if not raw_lecturer:
            continue

        unit_code_norm = _normalise_code(raw_code)
        lecturer_name = _clean_lecturer_name(raw_lecturer)
        phone = _clean_phone(raw_phone)

        key = (unit_code_norm, lecturer_name)
        if key in seen:
            continue
        seen.add(key)

        results.append({
            "unit_code": unit_code_norm,
            "unit_code_raw": raw_code,
            "lecturer_name": lecturer_name,
            "phone": phone,
        })

    return results


def parse_allocation_docx(file_path: str) -> list[dict]:
    """
    Parse the allocation DOCX and return a list of:
    {
        "unit_code": "COSC325",          # normalised, no spaces
        "unit_code_raw": "COSC 325",     # as it appears in doc
        "lecturer_name": "Muriithi Njoroge",
        "phone": "0720694935",
    }
    """
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx is required: pip install python-docx")

    doc = Document(file_path)
    table_rows = [
        [cell.text for cell in row.cells]
        for table in doc.tables
        for row in table.rows
    ]
    return _process_allocation_table_rows(table_rows)


def parse_allocation_pdf(file) -> list[dict]:
    """
    Parse the allocation PDF (same document structure as the DOCX version,
    extracted via table detection) and return the same row shape as
    parse_allocation_docx.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber is required: pip install pdfplumber")

    table_rows = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    table_rows.append([cell or "" for cell in row])

    if not table_rows:
        raise ValueError(
            "No tables could be extracted from the PDF. "
            "Scanned/image PDFs are not supported because they have no text layer."
        )

    return _process_allocation_table_rows(table_rows)
