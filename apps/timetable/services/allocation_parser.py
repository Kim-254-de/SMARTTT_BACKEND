import re
import docx
import pdfplumber

UNIT_CODE_REGEX = re.compile(r'([A-Z]{2,5})\s*(\d{3,5})', re.IGNORECASE)

def clean_lecturer_name(raw_name: str) -> str:
    """Strips (FT), (PT), slashes, phone numbers, and academic titles."""
    name = re.sub(r'\(.*?\)', '', raw_name)
    name = re.sub(r'\b(dr|prof|mr|mrs|ms)\b\.?', '', name, flags=re.IGNORECASE)
    # If cell contains phone numbers, remove them
    name = re.sub(r'07\d{8}|01\d{8}|\+254\d+', '', name)
    if '/' in name:
        name = name.split('/')[0]
    return " ".join(name.split()).strip()

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
            raw_title = unique_cells[title_col].text.strip() if title_col and len(unique_cells) > title_col else ""

            # Check if this row is a valid course code
            compact_code = re.sub(r"[^A-Z0-9]", "", raw_code.upper())
            if not re.match(r"^[A-Z]{3,4}\d{3,5}", compact_code):
                continue

            # If the extracted lecturer text accidentally equals the course title,
            # find the first cell containing '(ft)', '(pt)', or person titles
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
