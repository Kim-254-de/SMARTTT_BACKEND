"""
timetable/services/pdf_timetable_parser.py

Parser for Tharaka University September-December 2026 Master Teaching Timetable.
Handles:
  - 2-row cohort pairs (Unit row + Venue row)
  - Stacked multi-cohort groups
  - Expanded venue codes: ASB, ADM, G, UTC annexes, ED, BS, TC, STB
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

# Comprehensive known venue codes for Tharaka University
VENUE_PREFIXES = [
    r"UTC-[A-Z0-9]+",  # UTC-AB3, UTC-AA1, UTC-AC4, etc.
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

_COHORT_RE = re.compile(r"^(?P<program>.+?)\s+Y(?P<year>\d+)S(?P<sem>\d+)(\s*\((?P<group>\d+)\))?$", re.IGNORECASE)

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
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def normalise_unit_code(raw_unit: str) -> str:
    # Strip spaces and punctuation: e.g. "LAWP 103" -> "LAWP103"
    cleaned = re.sub(r"[^A-Z0-9]", "", raw_unit.upper())
    return cleaned


def _is_venue_text(text: str) -> bool:
    cleaned = text.strip().upper()
    return bool(VENUE_REGEX.match(cleaned)) or any(cleaned.startswith(p) for p in ["UTC", "ASB", "TC", "ED", "BS", "STB", "G", "ADM"])


def _extract_day_col_map(header_row: list) -> dict[int, str]:
    """Map column indices to Days of week."""
    col_to_day = {}
    current_day = "Monday"
    
    # Calculate column proportions if merged or forward fill
    for idx, cell in enumerate(header_row):
        txt = _clean(cell).capitalize()
        for d in DAYS:
            if d.lower() in txt.lower():
                current_day = d
                break
        col_to_day[idx] = current_day
    return col_to_day


def _approx_time_for_col(col_idx: int, total_cols: int) -> tuple[str, str]:
    """
    Fallback time estimator across the 7:00 to 19:00 window 
    if the PDF header hour bands are merged into composite strings.
    """
    # 12 hourly columns per day (7-8 through 18-19)
    # Col index offset relative to day bands
    step = (col_idx % 12)
    start_h = 7 + step
    end_h = start_h + 2  # Default university class duration is usually 2 or 3 hrs
    if end_h > 19:
        end_h = 19
    return f"{start_h:02d}:00", f"{end_h:02d}:00"


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

                # Check if this table has the DAY header
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

                    label = _clean(row_data[0])

                    # If label is empty, skip
                    if not label:
                        r += 1
                        continue

                    # Check if the next row is a complementary Venue row
                    venue_row = None
                    if r + 1 < num_rows and not _clean(data[r + 1][0]):
                        venue_row = data[r + 1]

                    n_cols = len(row_data)
                    for c in range(1, n_cols):
                        cell_val = _clean(row_data[c])
                        if not cell_val:
                            continue

                        # Extract venue
                        venue_val = "TBA"
                        if venue_row and c < len(venue_row) and _clean(venue_row[c]):
                            venue_val = _clean(venue_row[c])
                        elif "\n" in str(row_data[c]):
                            # Internal line break inside cell
                            parts = [p.strip() for p in str(row_data[c]).split("\n") if p.strip()]
                            if len(parts) >= 2 and _is_venue_text(parts[-1]):
                                cell_val = " ".join(parts[:-1])
                                venue_val = parts[-1]

                        day_str = current_day_map.get(c, "Monday")
                        st_time, end_time = _approx_time_for_col(c, n_cols)

                        # Handle stacked cohorts in label (e.g. BED MATH/PHYS (1)\nBED MATH/PHYS (2))
                        cohort_list = [cl.strip() for cl in label.split("\n") if cl.strip()]
                        if not cohort_list:
                            cohort_list = [label]

                        for cohort in cohort_list:
                            result.slots.append(
                                RawSlot(
                                    cohort_label=cohort,
                                    day=day_str,
                                    start_time=st_time.split(":")[0],
                                    end_time=end_time.split(":")[0],
                                    unit_code_raw=cell_val,
                                    venue=venue_val,
                                    room=venue_val,
                                    page=page_idx,
                                    raw_cell_text=f"{cell_val} in {venue_val}",
                                )
                            )

                    # If we used the next row as a venue row, advance by 2
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
        class_group = "MAIN"

        m = _COHORT_RE.match(s.cohort_label.strip())
        if m:
            program_code = m.group("program").strip()
            year_of_study = int(m.group("year"))
            semester = int(m.group("sem"))
            if m.group("group"):
                class_group = f"GR{m.group('group')}"

        # Clean unit code: strip trailing instructor/group tokens if present
        raw_unit = s.unit_code_raw.split()[0] if s.unit_code_raw else ""
        unit_code = normalise_unit_code(raw_unit)

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
