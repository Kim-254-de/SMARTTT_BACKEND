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

def parse_allocation_docx(file_path: str):
    doc = docx.Document(file_path)
    allocation_rows = []

    for table in doc.tables:
        header_map = {}
        
        # Scan header row to identify column mappings dynamically
        for r_idx, row in enumerate(table.rows[:3]):
            row_texts = [c.text.strip().upper() for c in row.cells]
            for col_idx, text in enumerate(row_texts):
                if "LECTURER" in text:
                    header_map["lecturer_col"] = col_idx
                elif "COURSE CODE" in text or "CODE" in text:
                    header_map["code_col"] = col_idx
                elif "TITLE" in text:
                    header_map["title_col"] = col_idx

        # If no explicit header detected, default standard positions
        lecturer_col = header_map.get("lecturer_col", -2)

        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if len(cells) < 2:
                continue

            first_cell = cells[0].strip()
            match = UNIT_CODE_REGEX.search(first_cell)
            if not match:
                continue

            dept, num = match.groups()
            normalized_code = f"{dept.upper()}{num}"
            raw_code = f"{dept.upper()} {num}"

            # Group hint if present (e.g., 'COSC 103 Group A')
            group_hint = ""
            grp_search = re.search(r'(Group\s+[A-Za-z0-9]+|GRP\s+[A-Za-z0-9]+)', first_cell, re.I)
            if grp_search:
                group_hint = grp_search.group(1).upper()

            # Find lecturer text
            raw_lecturer = ""
            if isinstance(lecturer_col, int) and len(cells) > lecturer_col:
                raw_lecturer = cells[lecturer_col]

            # If header index failed or grabbed title/blank, find cell with lecturer text
            if not raw_lecturer or raw_lecturer.upper() in ["L", "P", "CF", "TOTAL"]:
                for cell in reversed(cells):
                    ctext = cell.strip()
                    if not ctext or re.match(r'^\d+(\.\d+)?$', ctext) or "TOTAL" in ctext.upper():
                        continue
                    # Ignore phone number cell
                    if re.match(r'^(07|01|\+254|\d{9,})', ctext):
                        continue
                    # Ignore course title (if cell matches known title)
                    if len(cells) > 1 and ctext == cells[1].strip():
                        continue
                    raw_lecturer = ctext
                    break

            cleaned_lecturer = clean_lecturer_name(raw_lecturer)

            # Extra guard: Never accept the unit title or 'CO-ORDINATION' as lecturer name
            if len(cells) > 1 and cleaned_lecturer.lower() == clean_lecturer_name(cells[1]).lower():
                continue
            if "co-ordination" in cleaned_lecturer.lower() or not cleaned_lecturer:
                continue

            allocation_rows.append({
                "unit_code": normalized_code,
                "raw_unit_code": raw_code,
                "group": group_hint,
                "lecturer_name": cleaned_lecturer,
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
