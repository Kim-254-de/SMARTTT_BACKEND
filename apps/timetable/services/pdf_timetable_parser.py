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

# ---------------------------------------------------------------------------
# Venue detection — TUN timetable room codes
# ---------------------------------------------------------------------------
# Each entry is (compiled_regex, room_code_template).
# The regex captures two named groups:
#   "prefix" — everything before the venue (unit code + optional group label)
#   "room"   — the room identifier (digits or letter+digit suffix)
# Patterns are tried in order; the FIRST match wins, so list most-specific first.
#
# TUN room families:
#   UTC-AE4, UTC-AC2, UTC-AB3 … (Academic Complex, letter+digit code)
#   UTC5, UTC12                  (plain digit UTC rooms, e.g. "UTC 5")
#   ASB1, ASB2, ASB3             (Applied Science Buildings)
#   STB1 … STB8                  (Science/Technology Buildings)
#   TC1 … TC12                   (Tuition Centres)
#   ED3, ED4, ED5                (Engineering Drawing rooms)
#   BS1 … BS5                    (Biology/Science labs)
#   G1 … G39                     (General lecture rooms numbered 1-39)
# ---------------------------------------------------------------------------
_VENUE_SPECS: list[tuple] = [
    # UTC with letter code: "UTC-AE4", "UTC-AC2" (hyphen preserved by despacer)
    (re.compile(r"^(?P<prefix>.+?)UTC-(?P<room>[A-Z]{1,3}\d{1,2})$"), "UTC-{room}"),
    # UTC with plain digits: "UTC5", "UTC12" (no hyphen, e.g. "UTC 5" → "UTC5")
    (re.compile(r"^(?P<prefix>.+?)UTC(?P<room>\d{1,3})$"), "UTC{room}"),
    # ASB — listed before BS/STB so "ASB2" isn't partially matched as "BS"
    (re.compile(r"^(?P<prefix>.+?)ASB(?P<room>\d{1,2})$"), "ASB{room}"),
    # STB — listed before TC/BS so "STB3" isn't partially matched as "TB"
    (re.compile(r"^(?P<prefix>.+?)STB(?P<room>\d{1,2})$"), "STB{room}"),
    # TC — listed after UTC/ASB/STB
    (re.compile(r"^(?P<prefix>.+?)TC(?P<room>\d{1,2})$"), "TC{room}"),
    # ED
    (re.compile(r"^(?P<prefix>.+?)ED(?P<room>\d{1,2})$"), "ED{room}"),
    # BS — listed after ASB/STB
    (re.compile(r"^(?P<prefix>.+?)BS(?P<room>\d{1,2})$"), "BS{room}"),
    # G-rooms: the character immediately before "G" must be a letter or digit
    # so a lone "G" prefix (if any ever appears) doesn't match.
    (re.compile(r"^(?P<prefix>.+[A-Z\d])G(?P<room>\d{1,2})$"), "G{room}"),
]

# ---------------------------------------------------------------------------
# Group label detection
# ---------------------------------------------------------------------------
# TUN embeds group labels between the unit code and the venue:
#   "MATH 124 GR K TC 8"  →  unit="MATH124", group="GR K", room="TC8"
#   "PHIL 210 GR X UTC-AE4" → unit="PHIL210", group="GR X", room="UTC-AE4"
# After venue extraction the prefix ends in GR[A-Z0-9] when a group is present.
# Observed labels: GR A, GR B, GR K, GR N, GR X, GR 1, GR F, GR M
_GROUP_SUFFIX_RE = re.compile(r"^(?P<unit>.+?)GR(?P<group>[A-Z0-9])$")

# ---------------------------------------------------------------------------
# Cohort label parsing
# ---------------------------------------------------------------------------
# Row labels follow the pattern  "<PROGRAMME> Y<year>S<semester>"
#   "BSC COMP SCI Y1S1"     → program="BSC COMP SCI", year=1, semester=1
#   "BSC.NURSING Y2S1"      → program="BSC NURSING",  year=2, semester=1
#   "CERT.COMP SCI Y1S2"    → program="CERT COMP SCI",year=1, semester=2
# Dots in the programme name are treated as spaces.
# The optional trailing (\d+) handles split/parallel sections like "Y3S1(1)" or "Y3S1(2)".
# Those section numbers are discarded — they just mean the same cohort was too large for
# one timetable block and was split across two; students share the same program/year/sem.
_COHORT_RE = re.compile(
    r"^(?P<program>.+?)\s*Y(?P<year>\d+)S(?P<semester>\d+)\s*(?:\(\d+\))?\s*$",
    re.IGNORECASE,
)


@dataclass
class RawSlot:
    """One parsed class occurrence, pre-normalisation."""

    cohort_label: str
    day: str
    start_time: str           # left edge hour, e.g. "9"
    end_time: str             # right edge hour, e.g. "11"
    unit_code_raw: str        # unit letters+digits ONLY — group already stripped
    room_code: str | None     # full room code e.g. "UTC-AE4", "TC8", "G30"
    group: str | None         # extracted group label e.g. "GR K", "GR A", or None
    page: int
    raw_cell_text: str
    # Legacy fields — kept so any existing consumers don't break; both are
    # derived from room_code and are deprecated.
    venue: str | None = None
    room: str | None = None


@dataclass
class ParseResult:
    slots: list[RawSlot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clean_cell_text(text: str) -> str:
    """Collapse a ragged, line-wrapped cell into a single space-joined string."""
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def _split_unit_venue_group(despaced: str) -> tuple[str, str | None, str | None]:
    """
    Parse whitespace-stripped cell text into (unit_code_raw, room_code, group_label).

    The function handles all TUN venue formats and extracts any embedded group
    label (GR K, GR A, GR X …) that sits between the unit code and the venue.

    Examples
    --------
    "MATH124GRKTC8"        → ("MATH124", "TC8",     "GR K")
    "PHIL210GRXUTC-AE4"    → ("PHIL210", "UTC-AE4", "GR X")
    "COSC160UTC-AC2"       → ("COSC160", "UTC-AC2", None)
    "LISK101TC5"           → ("LISK101", "TC5",     None)
    "NURS212ASB2"          → ("NURS212", "ASB2",    None)
    "ACMT212G30"           → ("ACMT212", "G30",     None)
    "MATH322GRBUTC5"       → ("MATH322", "UTC5",    "GR B")
    "CHEM436GRASTB1"       → ("CHEM436", "STB1",    "GR A")
    "NURS133"              → ("NURS133", None,      None)  # bare unit, no venue
    """
    prefix_part = despaced
    room_code: str | None = None

    # Try each venue pattern in specificity order
    for pattern, template in _VENUE_SPECS:
        m = pattern.match(despaced)
        if m:
            prefix_part = m.group("prefix")
            room_code = template.format(room=m.group("room"))
            break

    # Extract group label from the unit+group prefix (e.g. "MATH124GRK" → unit="MATH124", group="GR K")
    group_label: str | None = None
    unit_part = prefix_part
    gm = _GROUP_SUFFIX_RE.match(prefix_part)
    if gm:
        unit_part = gm.group("unit")
        group_label = f"GR {gm.group('group')}"  # normalise to "GR K" spacing

    return unit_part, room_code, group_label


def parse_cohort_label(label: str) -> tuple[str, int, int]:
    """
    Parse a TUN cohort row label into (program_name, year_of_study, semester).

    Examples
    --------
    "BSC COMP SCI Y1S1"     → ("BSC COMP SCI",  1, 1)
    "BSC.NURSING Y2S1"      → ("BSC NURSING",   2, 1)
    "CERT.COMP SCI Y1S2"    → ("CERT COMP SCI", 1, 2)
    "B.LAW Y1S1"            → ("B LAW",         1, 1)
    "BSC GENERAL Y4S1"      → ("BSC GENERAL",   4, 1)

    Falls back to (label, 1, 1) if the pattern is not recognised.
    """
    m = _COHORT_RE.match(label.strip())
    if not m:
        return label.strip(), 1, 1
    # Replace dots with spaces, collapse multiple spaces
    program = re.sub(r"\.", " ", m.group("program")).strip()
    program = re.sub(r"\s+", " ", program)
    year = int(m.group("year"))
    semester = int(m.group("semester"))
    return program, year, semester


def normalise_unit_code(raw_unit: str) -> str:
    """
    Strip everything except uppercase letters and digits.

    Master-timetable unit codes are stored WITHOUT internal spaces
    (e.g. "COSC328", not "COSC 328").  The PDF's ragged line-wrapping
    means the raw fragment already arrives without spaces by the time
    this is called; this function additionally uppercases and strips stray
    non-alphanumeric noise so downstream matching against portal codes
    (which use "COSC 328") works once their spaces are also stripped.

    NOTE: call this AFTER _split_unit_venue_group so that the group suffix
    (GR K etc.) has already been removed from raw_unit.
    """
    return re.sub(r"[^A-Z0-9]", "", raw_unit.upper())


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
                        # Extract unit code, room code, and group label.
                        # Heuristic: if no room was found, peek at the next
                        # cell — a lone digit there is often the room number
                        # split across cells (e.g. "...BS" + "1").
                        unit_raw, room_code, group = _split_unit_venue_group(despaced)
                        if room_code is None and span_end + 1 < n_cols:
                            peek = row[span_end + 1]
                            if peek and re.fullmatch(r"\d{1,3}", peek.strip()):
                                despaced2 = despaced + peek.strip()
                                unit_raw2, room_code2, group2 = _split_unit_venue_group(despaced2)
                                if room_code2:
                                    unit_raw, room_code, group = unit_raw2, room_code2, group2
                                    span_end += 1  # consume the stray digit cell

                        result.slots.append(
                            RawSlot(
                                cohort_label=cohort_label,
                                day=day,
                                start_time=start_time,
                                end_time=end_time,
                                unit_code_raw=unit_raw,
                                room_code=room_code,
                                group=group,
                                page=page_index,
                                raw_cell_text=text,
                            )
                        )
                        if room_code is None:
                            result.warnings.append(
                                f"page {page_index}: no room parsed for "
                                f"cohort={cohort_label!r} text={text!r} (unit only)"
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
                        unit_raw, room_code, group = _split_unit_venue_group(despaced)
                        if room_code is None and span_end + 1 < n_cols:
                            peek = row[span_end + 1]
                            if peek and re.fullmatch(r"\d{1,3}", peek.strip()):
                                despaced2 = despaced + peek.strip()
                                unit_raw2, room_code2, group2 = _split_unit_venue_group(despaced2)
                                if room_code2:
                                    unit_raw, room_code, group = unit_raw2, room_code2, group2
                                    span_end += 1

                        raw_slot = RawSlot(
                            cohort_label=cohort_label,
                            day=day,
                            start_time=start_time,
                            end_time=end_time,
                            unit_code_raw=unit_raw,
                            room_code=room_code,
                            group=group,
                            page=page_index,
                            raw_cell_text=text,
                        )
                        slots.append(raw_slot)

                        if room_code is None:
                            warnings.append(
                                f"page {page_index}: no room parsed for "
                                f"cohort={cohort_label!r} text={text!r} (unit only)"
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


def to_timetable_slot_dicts(result: ParseResult, academic_year: str = "2026/2027") -> list[dict]:
    """
    Convert RawSlot rows into plain dicts with keys matching what
    TimetablePersistenceService.save_rows() and the mapper layer expect.

    Key contract (mirrors the Excel flat-format columns):
        program_code        — parsed from cohort_label (e.g. "BSC COMP SCI")
        year_of_study       — parsed from cohort_label Y# (e.g. 1)
        semester            — parsed from cohort_label S# (e.g. 1)
        academic_year       — passed in (e.g. "2026/2027")
        unit_code           — clean unit code, group suffix already removed
        room_code           — full room code (e.g. "UTC-AE4", "TC8", "G30")
        class_group         — group label ("GR K", "GR A") or "MAIN"
        day_of_week         — full day name ("Monday" …); persistence truncates to 3
        start_time          — "HH:00"
        end_time            — "HH:00"
        lecturer_university_id — blank (PDF format carries no lecturer data)
        cohort_label        — raw label, kept for debugging
        source_page         — PDF page number, kept for debugging
    """
    out = []
    for s in result.slots:
        program_name, year, semester = parse_cohort_label(s.cohort_label)
        out.append(
            {
                # ── identity / scheduling ──────────────────────────────
                "program_code": program_name,
                "year_of_study": year,
                "semester": semester,
                "academic_year": academic_year,
                "unit_code": normalise_unit_code(s.unit_code_raw),
                "room_code": s.room_code or "",
                "class_group": s.group or "MAIN",
                "day_of_week": s.day,          # "Monday" etc.
                "start_time": f"{s.start_time}:00",
                "end_time": f"{s.end_time}:00",
                "lecturer_university_id": "",
                # ── debug metadata ─────────────────────────────────────
                "cohort_label": s.cohort_label,
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
