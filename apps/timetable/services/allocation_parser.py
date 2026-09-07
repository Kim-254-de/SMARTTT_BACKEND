import re
import docx
import pdfplumber

UNIT_CODE_REGEX = re.compile(r'^[A-Z]{2,5}\s*\d{3,5}', re.IGNORECASE)

def clean_unit_code(raw_code: str) -> str:
    """Removes spaces and converts to uppercase: 'COSC 00104' -> 'COSC00104'."""
    return re.sub(r'[^A-Z0-9]', '', raw_code.upper())

def clean_lecturer_name(raw_name: str) -> str:
    """Strips (FT), (PT), slashes, phone numbers, and titles."""
    name = re.sub(r'\(.*?\)', '', raw_name)
    name = re.sub(r'\b(dr|prof|mr|mrs|ms)\b\.?', '', name, flags=re.IGNORECASE)
    if '/' in name:
        name = name.split('/')[0]
    return " ".join(name.split()).strip()

def parse_allocation_docx(file_path: str):
    """Parses course allocation tables from a .docx document."""
    doc = docx.Document(file_path)
    allocation_rows = []

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) < 2:
                continue

            first_cell = cells[0].strip()

            # Ignore non-unit code headers, section titles, or banner lines
            if not UNIT_CODE_REGEX.match(first_cell):
                continue

            # Identify lecturer column (usually index 5 or near the end)
            lecturer = ""
            for idx in [5, 4, 3, -2]:
                if len(cells) > idx and cells[idx].strip():
                    val = cells[idx].strip()
                    if not re.match(r'^\d+(\.\d+)?$', val) and val.upper() not in ["L", "P", "CF", "TOTAL"]:
                        lecturer = val
                        break

            if not lecturer:
                continue

            unit_code = clean_unit_code(first_cell)
            clean_lecturer = clean_lecturer_name(lecturer)

            if unit_code and clean_lecturer:
                allocation_rows.append({
                    "raw_unit_code": first_cell,
                    "unit_code": unit_code,
                    "lecturer_name": clean_lecturer,
                })

    return allocation_rows

def parse_allocation_pdf(file_obj):
    """Parses course allocation tables from a .pdf document."""
    allocation_rows = []

    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 2:
                        continue

                    first_cell = (row[0] or "").strip()
                    if not UNIT_CODE_REGEX.match(first_cell):
                        continue

                    lecturer = ""
                    for idx in [5, 4, 3, -2]:
                        if len(row) > idx and row[idx]:
                            val = row[idx].strip()
                            if not re.match(r'^\d+(\.\d+)?$', val) and val.upper() not in ["L", "P", "CF", "TOTAL"]:
                                lecturer = val
                                break

                    if not lecturer:
                        continue

                    unit_code = clean_unit_code(first_cell)
                    clean_lecturer = clean_lecturer_name(lecturer)

                    if unit_code and clean_lecturer:
                        allocation_rows.append({
                            "raw_unit_code": first_cell,
                            "unit_code": unit_code,
                            "lecturer_name": clean_lecturer,
                        })

    return allocation_rows
