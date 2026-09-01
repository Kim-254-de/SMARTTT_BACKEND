"""
timetable/parsers/pdf_grid_parser.py

Parser for Tharaka University "Directorate of Examinations and Timetabling"
master teaching timetable PDFs (e.g. "MAY-AUGUST 2026 TEACHING TIMETABLE").

Layout (IMPORTANT: header blocks do NOT repeat on every PDF page -- they
recur roughly every ~8-10 cohort rows, wherever the source document
inserted a fresh "Monday..Friday" band, which can land mid-page. A PDF
page therefore often contains a table that is pure cohort data with NO
header at all, relying on the header parsed from an earlier table.
Column position -> (day, hour) meaning must be carried as state across
tables/pages, not re-derived per page):

  - pdfplumber detects one or more tables per page. Processed in
    document (page, then top-to-bottom) order:
      * A table whose row 0 contains a day name ("Monday" etc.) is a
        HEADER table: row 0 = day bands (each spanning 12 hourly
        columns, 7-8 .. 18-19), row 1 = hourly slot labels. Any
        remaining rows (2+) are cohort data rows using this header.
      * A table whose row 0 does NOT contain a day name is a pure
        DATA table: every row is a cohort row, using the most
        recently seen header state.
  - Each cohort data row: column 0 holds the cohort label
    ("<PROGRAMME> <YEAR><SEM>", e.g. "BSC.CRIMINOLOGY Y2S2"); the
    remaining columns line up with the current header's day/hour grid.
  - Each populated cell holds a class: unit code (often line-wrapped
    unevenly, e.g. "CR\\nSS\\n021 0") followed by a venue code + room
    number (e.g. "UTC 12"). A class spanning >1 hour is a merged cell;
    pdfplumber represents the spanned columns as `None`.

This mirrors the existing Excel "2D grid" parser's contract: it emits
plain dicts shaped like TimetableSlot fields so the same
validation / bulk-upsert / unit-code-normalisation code path can consume
either source. See `to_timetable_slot_dicts()`.

Dependencies: pdfplumber (`pip install pdfplumber`).
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

# Known venue-block prefixes used by TUN timetables. Longest-prefix-first
# so "UTC" isn't swallowed by a spurious "TC" partial match.
VENUE_CODES = ["UTC", "STB", "TC", "ED", "BS"]

# Matches: <unit code letters/digits, ragged>  <venue letters>  <room digits>
# applied AFTER stripping all whitespace from the joined cell text.
_VENUE_RE = re.compile(r"^(?P<unit>.*?)(?P<venue>" + "|".join(VENUE_CODES) + r")(?P<room>\d{1,3})$")

# A bare unit code with no trailing venue (seen for a handful of rows,
# e.g. clinical/nursing rows: "NURS 133", "CCM 3136").
_UNIT_ONLY_RE = re.compile(r"^[A-Z]{2,6}\d{3,6}$")

# Unit code = leading letters + trailing digits, once whitespace is
# stripped, e.g. "CRSS0200" -> letters "CRSS", digits "0200".
_UNIT_SPLIT_RE = re.compile(r"^([A-Z]+)(\d+)$")


@dataclass
class RawSlot:
    """One parsed class occurrence, pre-normalisation."""

    cohort_label: str
    day: str
    start_time: str          # "HH-HH" left edge, e.g. "9"
    end_time: str             # right edge, e.g. "11"
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
    """Collapse a ragged, line-wrapped cell into a single space-joined string."""
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def _split_unit_and_venue(despaced: str) -> tuple[str, str | None, str | None]:
    """Given whitespace-stripped cell text, return (unit_code, venue, room)."""
    m = _VENUE_RE.match(despaced)
    if m:
        return m.group("unit"), m.group("venue"), m.group("room")
    if _UNIT_ONLY_RE.match(despaced):
        return despaced, None, None
    # Fallback: no recognisable venue suffix -> keep whole string as the
    # unit code and flag it for manual review downstream.
    return despaced, None, None


def normalise_unit_code(raw_unit: str) -> str:
    """
    Mirrors the existing normalisation rule used by the Excel parser:
    master-timetable codes are stored WITHOUT internal spaces
    (e.g. "COSC328", not "COSC 328"). The PDF's ragged line-wrapping
    means the raw fragment already arrives despaced by the time this is
    called; this function additionally uppercases and strips stray
    non-alphanumeric noise so downstream matching against
    department allocation sheets (which use "COSC 328") works once
    THEIR spaces are stripped too.
    """
    code = re.sub(r"[^A-Z0-9]", "", raw_unit.upper())
    return code


def _build_column_maps(header_day_row: list, header_hour_row: list) -> tuple[dict, dict]:
    """
    Returns:
      col_to_day: {col_index: "Monday"}
      col_to_hour_label: {col_index: "7-8"}
    Day header cells are merged (None-filled) across their 12-hour block,
    so we forward-fill the last seen day label.
    """
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
    """'9-10' -> ('9', '10')."""
    start, end = label.split("-")
    return start.strip(), end.strip()


def _is_header_row(row: list) -> bool:
    return any(cell and cell.strip() in DAYS for cell in row)


def parse_pdf(path: str) -> ParseResult:
    """
    Parse a TUN master-timetable PDF into RawSlot rows.

    Header (day/hour) state is carried across tables and pages: only
    tables that actually start with a day-name row update the column
    mapping, everything else is treated as cohort data using whatever
    header was last seen. See module docstring.
    
    IMPORTANT: For large PDFs, use parse_pdf_streaming() instead for
    memory efficiency.
    """
    result = ParseResult()
    col_to_day: dict[int, str] = {}
    col_to_hour_label: dict[int, str] = {}

    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if not tables:
                continue

            # Ensure top-to-bottom reading order within the page.
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
                            # continuation of a merged cell handled when we
                            # first encountered its left edge; skip.
                            col += 1
                            continue

                        text = _clean_cell_text(cell) if cell else ""
                        if not text:
                            col += 1
                            continue

                        # Determine merge span: consecutive following
                        # columns that are None AND still within the same
                        # day block belong to this class.
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
                        # Heuristic patch for the rare case where the room
                        # number lands in its own stray cell (e.g. "...BS"
                        # then a lone "1" cell): peek one column ahead.
                        venue_unit, venue, room = _split_unit_and_venue(despaced)
                        if venue is None and span_end + 1 < n_cols:
                            peek = row[span_end + 1]
                            if peek and re.fullmatch(r"\d{1,3}", peek.strip()):
                                despaced2 = despaced + peek.strip()
                                venue_unit2, venue2, room2 = _split_unit_and_venue(despaced2)
                                if venue2:
                                    venue_unit, venue, room = venue_unit2, venue2, room2
                                    span_end += 1  # consume the stray cell

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
    """
    Parse a TUN master-timetable PDF into RawSlot rows using a streaming/chunking
    approach. This is MUCH more memory-efficient for large PDFs.
    
    Args:
        path: Path to PDF file
        chunk_callback: Optional callback function(slots: list[RawSlot], page: int, table: int) 
                       called for each batch of slots. If provided, allows processing
                       slots without keeping all in memory.
        chunk_size: Number of slots to accumulate before calling callback (default 50)
        
    Yields:
        Tuple of (RawSlot list, page index, table index) if no callback provided
        Returns full ParseResult with warnings if callback is provided
    """
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

                        # Flush batch if reached chunk_size
                        if len(slots) >= chunk_size:
                            if chunk_callback:
                                chunk_callback(slots[:], page_index, table_counter)
                            else:
                                yield slots[:], page_index, table_counter
                            slots = []

    # Final flush
    if slots:
        if chunk_callback:
            chunk_callback(slots, page_index, table_counter)
        else:
            yield slots, page_index, table_counter

    # Return warnings via callback or as generator final message
    if chunk_callback:
        return ParseResult(slots=[], warnings=warnings)
    else:
        yield [], -1, -1  # Sentinel to indicate end
        return ParseResult(slots=[], warnings=warnings)


def to_timetable_slot_dicts(result: ParseResult) -> list[dict]:
    """
    Convert RawSlot rows into plain dicts matching TimetableSlot's shape,
    ready for the same bulk-upsert / normalisation path the Excel 2D-grid
    parser feeds into. `lecturer_name_text` is not present in this PDF
    format, so it is left blank (existing lecturer auto-link logic simply
    no-ops on blank names).
    """
    out = []
    for s in result.slots:
        out.append(
            {
                "cohort_label": s.cohort_label,
                "day": s.day,
                "start_time": f"{s.start_time}:00",
                "end_time": f"{s.end_time}:00",
                "unit_code": normalise_unit_code(s.unit_code_raw),
                "venue": f"{s.venue} {s.room}" if s.venue else None,
                "lecturer_name_text": "",
                "source_page": s.page,
            }
        )
    return out


if __name__ == "__main__":
    import sys
    import json

    target = sys.argv[1]
    res = parse_pdf(target)
    slots = to_timetable_slot_dicts(res)
    print(f"Parsed {len(slots)} slots from {target}")
    print(f"Warnings: {len(res.warnings)}")
    for w in res.warnings[:20]:
        print(" -", w)
    with open("parsed_slots.json", "w") as f:
        json.dump(slots, f, indent=2)
