"""
timetable/services/pdf_timetable_parser.py

Parser for Tharaka University Master Teaching Timetable.
Handles:
  - Disentangling stacked units and venues per cell
  - Parsing unit groups (e.g. MATH 124 GR.M, PHYS 121 GRA, EDCI 104 GRJ)
  - Pairing separate venues to separate units
  - Accurate day-of-week parsing (mon, tue, wed, thu, fri)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple

import pdfplumber

logger = logging.getLogger(__name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
LABEL_COL = 0

# Match Group annotations: GR.M, GR M, GRA, GR A, GR 1, GROUP A
GROUP_RE = re.compile(
    r"(?:\b(?:GR\.?|GROUP)\s*([A-Z0-9]+)\b)|(?:\bGR([A-Z0-9]+)\b)", 
    re.IGNORECASE
)

# Known Venue matching regex
VENUE_PREFIXES = [
    r"UTC-[A-Z0-9]+",  # UTC-AB3, UTC-AA1, UTC-AC4
    r"UTC\s*\d+",      # UTC 12, UTC 6
    r"ASB\s*[A-Z0-9]+",# ASB 1, ASB 2, ASBJ
    r"ASH\s*[A-Z0-9]+",
    r"ADM\s*\d*",      # ADM 1
    r"STB\s*\d+",      # STB 4, STB 8
    r"TC\s*[A-Z0-9]+", # TC 1, TC 11, TCX, TCL
    r"ED\s*\d+",       # ED 3, ED 4, ED 5
    r"BS\s*\d+",       # BS 1, BS 2, BS 3
    r"G\s*\d+",        # G1, G2, G14, G30
]
VENUE_REGEX = re.compile(r"^(" + "|".join(VENUE_PREFIXES) + r")$", re.IGNORECASE)

_COHORT_RE = re.compile(
    r"^(?P<program>.+?)\s+Y(?P<year>\d+)S(?P<sem>\d+)(?:\s*\((?P<cohort_sub>\d+)\))?$", 
    re.IGNORECASE
)

DAY_MAP = {
    "mon": "mon", "monday": "mon",
    "tue": "tue", "tuesday": "tue",
    "wed": "wed", "wednesday": "wed",
    "thu": "thu", "thursday": "thu",
    "fri": "fri", "friday": "fri",
    "sat": "sat", "saturday": "sat",
    "sun": "sun", "sunday": "sun",
}


@dataclass
class RawSlot:
    cohort_label: str
    day: str
    start_time: str
    end_time: str
    unit_code_raw: str
    group: str
    venue: str
    room: str
    page: int
    raw_cell_text: str


@dataclass
class ParseResult:
    slots: list[RawSlot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[ \t]+", " ", str(text)).strip()


def parse_unit_and_group(text: str) -> tuple[str, str]:
    """
    Extracts the normalized unit code and specific group from text.
    Example:
      "MATH 124 GR.M" -> ("MATH124", "GR_M")
      "PHYS 121 GRA"   -> ("PHYS121", "GR_A")
      "COSC 103"       -> ("COSC103", "MAIN")
    """
    cleaned = text.strip()
    group = "MAIN"

    # Search for group match
    m = GROUP_RE.search(cleaned)
    if m:
        extracted = (m.group(1) or m.group(2) or "").upper()
        group = f"GR_{extracted}"
        # Remove group text from unit code string
        cleaned = cleaned[:m.start()] + cleaned[m.end():]

    # Clean the unit code (keep alphanumeric characters only)
    unit_code = re.sub(r"[^A-Z0-9]", "", cleaned.upper())
    return unit_code, group


def _is_likely_venue(text: str) -> bool:
    cleaned = text.strip().upper()
    return bool(VENUE_REGEX.match(cleaned)) or any(
        cleaned.startswith(p) for p in ["UTC", "ASB", "TC", "ED", "BS", "STB", "ADM"]
    ) or bool(re.match(r"^G\s*\d{1,3}$", cleaned))


def _extract_day_col_map(header_row: list) -> dict[int, str]:
    col_to_day = {}
    current_day = "Monday"
    for idx, cell in enumerate(header_row):
        txt = _clean(cell).capitalize()
        for d in DAYS:
            if d.lower() in txt.lower():
                current_day = d
                break
        col_to_day[idx] = current_day
    return col_to_day


def _approx_time_for_col(col_idx: int) -> tuple[str, str]:
    step = (col_idx % 12)
    start_h = 7 + step
    end_h = min(start_h + 2, 19)
    return f"{start_h:02d}:00", f"{end_h:02d}:00"


def _split_cell_lines(cell_val: str | None) -> list[str]:
    if not cell_val:
        return []
    lines = [l.strip() for l in str(cell_val).split("\n") if l.strip()]
    return lines


def parse_pdf(path: str) -> ParseResult:
    result = ParseResult()
    current_day_map = {}

    with pdfplumber.open(path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if not tables:
                continue

            tables = sorted(tables, key=lambda t: t.bbox[1])

            for table in tables:
                data = table.extract()
                if not data or len(data) < 2:
                    continue

                start_row = 0
                row0_str = " ".join([_clean(c) for c in data[0] if c])
                if any(d.lower() in row0_str.lower() for d in DAYS):
                    current_day_map = _extract_day_col_map(data[0])
                    start_row = 2 if len(data) > 2 else 1

                if not current_day_map:
                    continue

                r = start_row
                num_rows = len(data)

                while r < num_rows:
                    row_data = data[r]
                    if not row_data or not any(row_data):
                        r += 1
                        continue

                    raw_label = row_data[0]
                    cohort_lines = _split_cell_lines(raw_label)
                    if not cohort_lines:
                        r += 1
                        continue

                    # Look ahead to see if the row immediately below holds venues
                    venue_row = None
                    if r + 1 < num_rows:
                        next_row = data[r + 1]
                        next_row_label = _clean(next_row[0]) if next_row else ""
                        if not next_row_label:
                            venue_row = next_row

                    n_cols = len(row_data)
                    for c in range(1, n_cols):
                        cell_raw = row_data[c]
                        if not cell_raw:
                            continue

                        # Extract unit candidate lines and venue candidate lines
                        unit_lines = _split_cell_lines(cell_raw)
                        v_lines = _split_cell_lines(venue_row[c]) if (venue_row and c < len(venue_row)) else []

                        # If cell itself has unit + venue embedded across lines:
                        if not v_lines and len(unit_lines) >= 2:
                            if _is_likely_venue(unit_lines[-1]):
                                v_lines = [unit_lines.pop()]

                        day_str = current_day_map.get(c, "Monday")
                        st_time, end_time = _approx_time_for_col(c)

                        # Pair each unit with its corresponding venue and cohort
                        max_items = max(len(unit_lines), 1)
                        for i in range(max_items):
                            u_text = unit_lines[i] if i < len(unit_lines) else (unit_lines[0] if unit_lines else "")
                            if not u_text or _is_likely_venue(u_text):
                                continue

                            # Resolve venue for this item
                            venue_item = "TBA"
                            if i < len(v_lines):
                                venue_item = v_lines[i]
                            elif v_lines:
                                venue_item = v_lines[-1]

                            # Resolve cohort
                            cohort_item = cohort_lines[i] if i < len(cohort_lines) else cohort_lines[0]

                            clean_unit, group = parse_unit_and_group(u_text)
                            if not clean_unit or len(clean_unit) < 3:
                                continue

                            result.slots.append(
                                RawSlot(
                                    cohort_label=cohort_item,
                                    day=day_str,
                                    start_time=st_time.split(":")[0],
                                    end_time=end_time.split(":")[0],
                                    unit_code_raw=clean_unit,
                                    group=group,
                                    venue=venue_item,
                                    room=venue_item,
                                    page=page_idx,
                                    raw_cell_text=f"{clean_unit} [{group}] at {venue_item}",
                                )
                            )

                    # Advance by 2 if venue_row was consumed, else 1
                    if venue_row is not None:
                        r += 2
                    else:
                        r += 1

    return result


def to_timetable_slot_dicts(result: ParseResult, academic_year: str = "2026/2027") -> list[dict]:
    out = []
    for s in result.slots:
        program_code = s.cohort_label
        year_of_study = 1
        semester = 1
        class_group = s.group

        m = _COHORT_RE.match(s.cohort_label.strip())
        if m:
            program_code = m.group("program").strip()
            year_of_study = int(m.group("year"))
            semester = int(m.group("sem"))
            if class_group == "MAIN" and m.group("cohort_sub"):
                class_group = f"GR_{m.group('cohort_sub')}"

        unit_code = normalise_unit_code(s.unit_code_raw)
        if not unit_code or len(unit_code) < 3:
            continue

        raw_day = str(s.day or "").strip().lower()
        code_day = DAY_MAP.get(raw_day, raw_day[:3])

        try:
            st_int = int(s.start_time)
            et_int = int(s.end_time)
            start_str = f"{st_int:02d}:00"
            end_str = f"{et_int:02d}:00"
        except (ValueError, TypeError):
            start_str = "07:00"
            end_str = "09:00"

        room_str = s.venue[:20] if s.venue else "TBA"

        out.append({
            "academic_year": academic_year,
            "semester": semester,
            "year_of_study": year_of_study,
            "program_code": program_code[:64],
            "unit_code": unit_code[:20],
            "class_group": class_group,
            "day_of_week": code_day,
            "start_time": start_str,
            "end_time": end_str,
            "room_code": room_str,
            "lecturer_university_id": "",
            "lecturer_name_text": "",
        })
    return out
