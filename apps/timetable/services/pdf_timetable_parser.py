"""
timetable/services/pdf_timetable_parser.py

Parser for Tharaka University "Directorate of Examinations and Timetabling"
master teaching timetable PDFs.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Iterable

import pdfplumber

logger = logging.getLogger(__name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
HOURS_PER_DAY = 12  # columns 7-8 .. 18-19
COLS_PER_DAY = HOURS_PER_DAY
LABEL_COL = 0

VENUE_CODES = ["UTC", "STB", "TC", "ED", "BS"]

_VENUE_RE = re.compile(r"^(?P<unit>.*?)(?P<venue>" + "|".join(VENUE_CODES) + r")(?P<room>\d{1,3})$")
_UNIT_ONLY_RE = re.compile(r"^[A-Z]{2,6}\d{3,6}$")
_UNIT_SPLIT_RE = re.compile(r"^([A-Z]+)(\d+)$")
_COHORT_RE = re.compile(r"^(?P<program>.+?)\s+Y(?P<year>\d+)S(?P<sem>\d+)$", re.IGNORECASE)


@dataclass
class RawSlot:
    """One parsed class occurrence, pre-normalisation."""
    cohort_label: str
    day: str
    start_time: str
    end_time: str
    unit_code_raw: str
    venue: str | None
    room: str | None
    page: int
    raw_cell_text: str


@dataclass
class ParseResult:
    slots: list[RawSlot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clean_cell_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def _split_unit_and_venue(despaced: str) -> tuple[str, str | None, str | None]:
    m = _VENUE_RE.match(despaced)
    if m:
        return m.group("unit"), m.group("venue"), m.group("room")
    if _UNIT_ONLY_RE.match(despaced):
        return despaced, None, None
    return despaced, None, None


def normalise_unit_code(raw_unit: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", raw_unit.upper())


def _build_column_maps(header_day_row: list, header_hour_row: list) -> tuple[dict, dict]:
    col_to_day: dict[int, str] = {}
    current_day = None
    for idx, val in enumerate(header_day_row):
        if idx == LABEL_COL:
            continue
        if val:
            current_day = val.strip()
        if current_day:
            col_to_day[idx] = current_day

    col_to_hour_label: dict[int, str] = {}
    for idx, val in enumerate(header_hour_row):
        if idx == LABEL_COL:
            continue
        if val:
            col_to_hour_label[idx] = val.strip()

    return col_to_day, col_to_hour_label


def _hour_bounds(label: str) -> tuple[str, str]:
    start, end = label.split("-")
    return start.strip(), end.strip()


def _is_header_row(row: list) -> bool:
    return any(cell and cell.strip() in DAYS for cell in row)


def parse_pdf(path: str) -> ParseResult:
    result = ParseResult()
    col_to_day: dict[int, str] = {}
    col_to_hour_label: dict[int, str] = {}

    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if not tables:
                continue

            tables = sorted(tables, key=lambda t: t.bbox[1])

            for table in tables:
                data = table.extract()
                if not data:
                    continue

                if _is_header_row(data[0]):
                    if len(data) < 2:
                        result.warnings.append(
                            f"page {page_index}: header table with no hour-label row"
                        )
                        continue
                    header_day_row, header_hour_row = data[0], data[1]
                    col_to_day, col_to_hour_label = _build_column_maps(header_day_row, header_hour_row)
                    data_rows = data[2:]
                else:
                    data_rows = data

                if not col_to_day:
                    result.warnings.append(
                        f"page {page_index}: cohort data encountered before any header "
                        f"was parsed; skipping table"
                    )
                    continue

                for row in data_rows:
                    if not row or not row[0]:
                        continue
                    cohort_label = _clean_cell_text(row[0])
                    if not cohort_label:
                        continue

                    col = 1
                    n_cols = len(row)
                    while col < n_cols:
                        cell = row[col]

                        if cell is None:
                            col += 1
                            continue

                        text = _clean_cell_text(cell) if cell else ""
                        if not text:
                            col += 1
                            continue

                        span_end = col
                        day = col_to_day.get(col)
                        while (
                            span_end + 1 < n_cols
                            and row[span_end + 1] is None
                            and col_to_day.get(span_end + 1) == day
                        ):
                            span_end += 1

                        start_label = col_to_hour_label.get(col)
                        end_label = col_to_hour_label.get(span_end)
                        if not (day and start_label and end_label):
                            result.warnings.append(
                                f"page {page_index}: could not resolve day/time for "
                                f"cohort={cohort_label!r} col={col} text={text!r}"
                            )
                            col = span_end + 1
                            continue

                        start_time, _ = _hour_bounds(start_label)
                        _, end_time = _hour_bounds(end_label)

                        despaced = re.sub(r"\s+", "", text)
                        venue_unit, venue, room = _split_unit_and_venue(despaced)
                        if venue is None and span_end + 1 < n_cols:
                            peek = row[span_end + 1]
                            if peek and re.fullmatch(r"\d{1,3}", peek.strip()):
                                despaced2 = despaced + peek.strip()
                                venue_unit2, venue2, room2 = _split_unit_and_venue(despaced2)
                                if venue2:
                                    venue_unit, venue, room = venue_unit2, venue2, room2
                                    span_end += 1

                        result.slots.append(
                            RawSlot(
                                cohort_label=cohort_label,
                                day=day,
                                start_time=start_time,
                                end_time=end_time,
                                unit_code_raw=venue_unit,
                                venue=venue,
                                room=room,
                                page=page_index,
                                raw_cell_text=text,
                            )
                        )
                        if venue is None:
                            result.warnings.append(
                                f"page {page_index}: no venue parsed for "
                                f"cohort={cohort_label!r} text={text!r} (kept unit_code only)"
                            )

                        col = span_end + 1

    return result


def parse_pdf_streaming(path: str, chunk_callback=None, chunk_size: int = 50):
    slots = []
    warnings = []
    col_to_day: dict[int, str] = {}
    col_to_hour_label: dict[int, str] = {}
    table_counter = 0

    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if not tables:
                continue

            tables = sorted(tables, key=lambda t: t.bbox[1])

            for table in tables:
                table_counter += 1
                data = table.extract()
                if not data:
                    continue

                if _is_header_row(data[0]):
                    if len(data) < 2:
                        warnings.append(
                            f"page {page_index}: header table #{table_counter} "
                            f"with no hour-label row"
                        )
                        continue
                    header_day_row, header_hour_row = data[0], data[1]
                    col_to_day, col_to_hour_label = _build_column_maps(
                        header_day_row, header_hour_row
                    )
                    data_rows = data[2:]
                else:
                    data_rows = data

                if not col_to_day:
                    warnings.append(
                        f"page {page_index}: cohort data encountered before any header "
                        f"was parsed; skipping table #{table_counter}"
                    )
                    continue

                for row in data_rows:
                    if not row or not row[0]:
                        continue
                    cohort_label = _clean_cell_text(row[0])
                    if not cohort_label:
                        continue

                    col = 1
                    n_cols = len(row)
                    while col < n_cols:
                        cell = row[col]

                        if cell is None:
                            col += 1
                            continue

                        text = _clean_cell_text(cell) if cell else ""
                        if not text:
                            col += 1
                            continue

                        span_end = col
                        day = col_to_day.get(col)
                        while (
                            span_end + 1 < n_cols
                            and row[span_end + 1] is None
                            and col_to_day.get(span_end + 1) == day
                        ):
                            span_end += 1

                        start_label = col_to_hour_label.get(col)
                        end_label = col_to_hour_label.get(span_end)
                        if not (day and start_label and end_label):
                            warnings.append(
                                f"page {page_index}: could not resolve day/time for "
                                f"cohort={cohort_label!r} col={col} text={text!r}"
                            )
                            col = span_end + 1
                            continue

                        start_time, _ = _hour_bounds(start_label)
                        _, end_time = _hour_bounds(end_label)

                        despaced = re.sub(r"\s+", "", text)
                        venue_unit, venue, room = _split_unit_and_venue(despaced)
                        if venue is None and span_end + 1 < n_cols:
                            peek = row[span_end + 1]
                            if peek and re.fullmatch(r"\d{1,3}", peek.strip()):
                                despaced2 = despaced + peek.strip()
                                venue_unit2, venue2, room2 = _split_unit_and_venue(despaced2)
                                if venue2:
                                    venue_unit, venue, room = venue_unit2, venue2, room2
                                    span_end += 1

                        raw_slot = RawSlot(
                            cohort_label=cohort_label,
                            day=day,
                            start_time=start_time,
                            end_time=end_time,
                            unit_code_raw=venue_unit,
                            venue=venue,
                            room=room,
                            page=page_index,
                            raw_cell_text=text,
                        )
                        slots.append(raw_slot)

                        if venue is None:
                            warnings.append(
                                f"page {page_index}: no venue parsed for "
                                f"cohort={cohort_label!r} text={text!r} (kept unit_code only)"
                            )

                        col = span_end + 1

                        if len(slots) >= chunk_size:
                            if chunk_callback:
                                chunk_callback(slots[:], page_index, table_counter)
                            else:
                                yield slots[:], page_index, table_counter
                            slots = []

    if slots:
        if chunk_callback:
            chunk_callback(slots, page_index, table_counter)
        else:
            yield slots, page_index, table_counter

    if chunk_callback:
        return ParseResult(slots=[], warnings=warnings)
    else:
        yield [], -1, -1
        return ParseResult(slots=[], warnings=warnings)


def to_timetable_slot_dicts(result: ParseResult, academic_year: str = "2026/2027") -> list[dict]:
    """
    Transform raw parsed PDF slots into the normalized dictionary schema
    required by TimetableUploadValidator and TimetableUploadPipelineService.
    """
    out = []
    for s in result.slots:
        program_code = s.cohort_label
        year_of_study = 1
        semester = 1

        match = _COHORT_RE.match(s.cohort_label.strip())
        if match:
            program_code = match.group("program").strip()
            year_of_study = int(match.group("year"))
            semester = int(match.group("sem"))

        venue_part = s.venue or ""
        room_part = s.room or ""
        room_code = f"{venue_part} {room_part}".strip() or "TBA"

        try:
            st_int = int(s.start_time)
            et_int = int(s.end_time)
            start_time_str = f"{st_int:02d}:00"
            end_time_str = f"{et_int:02d}:00"
        except (ValueError, TypeError):
            start_time_str = "07:00"
            end_time_str = "08:00"

        out.append({
            "academic_year": academic_year,
            "semester": semester,
            "year_of_study": year_of_study,
            "program_code": program_code[:64],
            "unit_code": normalise_unit_code(s.unit_code_raw),
            "class_group": "MAIN",
            "day_of_week": s.day.strip().lower()[:3],
            "start_time": start_time_str,
            "end_time": end_time_str,
            "room_code": room_code[:20],
            "lecturer_university_id": "",
            "lecturer_name_text": "",
        })
    return out
