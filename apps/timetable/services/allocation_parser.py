import re
import docx

UNIT_CODE_REGEX = re.compile(r'^[A-Z]{2,5}\s*\d{3,5}', re.IGNORECASE)

def clean_unit_code(raw_code: str) -> str:
    """Removes spaces and converts to uppercase: 'COSC 00104' -> 'COSC00104'."""
    return re.sub(r'[^A-Z0-9]', '', raw_code.upper())

def clean_lecturer_name(raw_name: str) -> str:
    """Strips (FT), (PT), slashes, phone numbers, and titles."""
    name = re.sub(r'\(.*?\)', '', raw_name)  # Remove (FT), (PT), etc.
    name = re.sub(r'Dr\.|Prof\.|Mr\.|Mrs\.|Ms\.', '', name, flags=re.IGNORECASE)
    # If multiple lecturers exist separated by slash, take the primary
    if '/' in name:
        name = name.split('/')[0]
    return " ".join(name.split()).strip()

def parse_allocation_docx(file_path: str):
    doc = docx.Document(file_path)
    allocation_rows = []

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) < 2:
                continue

            first_cell = cells[0].strip()

            # Ignore headers, banner lines, or non-unit codes
            if not UNIT_CODE_REGEX.match(first_cell):
                continue

            # Detect lecturer column (usually column index 5 or near the end)
            # In your docx format: [Code, Title, L, P, CF, LECTURER, PHONE]
            lecturer = ""
            for idx in [5, 4, 3, -2]:
                if len(cells) > idx and cells[idx].strip():
                    val = cells[idx].strip()
                    # Skip if it's a numeric/CF column
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
