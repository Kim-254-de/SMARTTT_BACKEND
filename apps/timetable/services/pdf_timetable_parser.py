"""
timetable/services/pdf_timetable_parser.py

Parser for Tharaka University Master Teaching Timetable.
Handles:
  - Unit code normalisation (normalise_unit_code)
  - Disentangling stacked units and venues per cell
  - Parsing unit groups (e.g., MATH 124 GR.M, PHYS 121 GRA, EDCI 104 GRJ)
  - Pairing separate venues to separate units
  - Lowercase day-of-week codes (mon, tue, wed, thu, fri)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

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
# Unanchored at the end, used only as a fallback when the whole line isn't a
# clean venue - see _extract_venue_prefix.
_VENUE_PREFIX_RE = re.compile(r"^(" + "|".join(VENUE_PREFIXES) + r")", re.IGNORECASE)

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


def normalise_unit_code(raw_unit: str) -> str:
    """
    Exported helper expected across the upload pipeline.
    Strips non-alphanumeric characters and group noise.
    """
    if not raw_unit:
        return ""
    cleaned = re.sub(GROUP_RE, "", raw_unit)
    return re.sub(r"[^A-Z0-9]", "", cleaned.upper())


def parse_unit_and_group(text: str) -> tuple[str, str]:
    """
    Extracts the normalized unit code and specific group from text.
    Example:
      'MATH 124 GR.M' -> ('MATH124', 'GR_M')
      'PHYS 121 GRA'   -> ('PHYS121', 'GR_A')
      'COSC 103'       -> ('COSC103', 'MAIN')
    """
    cleaned = text.strip()
    group = "MAIN"

    m = GROUP_RE.search(cleaned)
    if m:
        extracted = (m.group(1) or m.group(2) or "").upper()
        group = f"GR_{extracted}"
        cleaned = cleaned[:m.start()] + cleaned[m.end():]

    unit_code = re.sub(r"[^A-Z0-9]", "", cleaned.upper())
    return unit_code, group


def _is_likely_venue(text: str) -> bool:
    cleaned = text.strip().upper()
    # VENUE_REGEX is already anchored (^...$) and covers every real venue
    # format (UTC 6, UTC-AC4, ASB 2, TC 11, ED 3, STB 7, ADM 1, G 30, ...).
    # An earlier version additionally used an unanchored .startswith() check
    # against these same prefixes as a fallback - that's what caused unit
    # codes like "EDCI 312"/"EDCI 311" (any BEd course starting with "ED")
    # to be misclassified as room codes and silently dropped, since
    # "EDCI 312".startswith("ED") is True even though it's nothing like an
    # actual "ED 3"-style room code. VENUE_REGEX alone is sufficient and
    # correct - it requires the digits/code that make a string a venue.
    return bool(VENUE_REGEX.match(cleaned)) or bool(re.match(r"^G\s*\d{1,3}$", cleaned))


def _extract_venue_prefix(text: str) -> str | None:
    """
    Fallback for cells (seen on the certificate-programme pages) where the
    venue line carries stray trailing noise from a table-extraction glitch,
    e.g. "G 12 1" instead of "G 12". Only trusted when what's left after the
    venue prefix is short digit/space noise, not real unit or group text -
    otherwise a line that never was a venue (e.g. "GR 12A") could be
    misread as one.
    """
    cleaned = text.strip().upper()
    m = _VENUE_PREFIX_RE.match(cleaned)
    if not m:
        return None
    remainder = cleaned[m.end():].strip()
    if remainder and not re.fullmatch(r"[\d\s]{1,3}", remainder):
        return None
    return m.group(1).strip()


def _is_header_row(row: list) -> bool:
    """A day-band row, e.g. ['', 'Monday', None, ..., 'Tuesday', ...]."""
    return any(cell and str(cell).strip() in DAYS for cell in row)


def _build_column_maps(day_row: list, hour_row: list) -> tuple[dict[int, str], dict[int, str]]:
    """
    Turn the two header rows into column -> day and column -> hour-label maps.
    Day cells are merged (None-filled) across their 12-hour block in the
    source PDF, so forward-fill the last seen day label; the hour row has
    one real label per column ("7-\\n8", "8-\\n9", ...), no fill needed.
    """
    col_to_day: dict[int, str] = {}
    current_day: str | None = None
    for idx, cell in enumerate(day_row):
        if idx == LABEL_COL:
            continue
        txt = _clean(cell)
        if txt:
            current_day = txt
        if current_day:
            col_to_day[idx] = current_day

    col_to_hour_label: dict[int, str] = {}
    for idx, cell in enumerate(hour_row):
        if idx == LABEL_COL:
            continue
        txt = _clean(cell)
        if txt:
            col_to_hour_label[idx] = txt

    return col_to_day, col_to_hour_label


def _hour_bounds(label: str) -> tuple[str, str]:
    """'7-\\n8' -> ('7', '8'); the source PDF wraps the label at the hyphen."""
    flat = re.sub(r"\s+", "", label)
    start, end = flat.split("-", 1)
    return start.strip(), end.strip()


def _split_cell_lines(cell_val: str | None) -> list[str]:
    if not cell_val:
        return []
    lines = [l.strip() for l in str(cell_val).split("\n") if l.strip()]
    return lines


_ALPHA_ONLY_RE = re.compile(r"^[A-Z]{2,6}$", re.IGNORECASE)
_STARTS_WITH_DIGIT_RE = re.compile(r"^\d")


def _merge_split_unit_code_lines(lines: list[str]) -> list[str]:
    """
    A common cell-wrap pattern splits the unit code's letters onto their own
    line, e.g. ["GEOG", "144 GR D", "UTC 7"] or ["CHTM", "0020", "G 12"]
    instead of ["GEOG 144 GR D", "UTC 7"]. Detect a bare-letters line
    directly followed by a line that starts with the code's digits (which
    may carry a trailing " GR X" group marker) and join the two - otherwise
    the letters and digits each get treated as their own bogus "unit".
    """
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            _ALPHA_ONLY_RE.match(line)
            and i + 1 < len(lines)
            and _STARTS_WITH_DIGIT_RE.match(lines[i + 1])
        ):
            merged.append(f"{line}{lines[i + 1]}")
            i += 2
        else:
            merged.append(line)
            i += 1
    return merged


# Matches a line ending in a bare "GR"/"GR."/"GROUP" marker with nothing
# captured after it - see _merge_split_group_lines.
_TRAILING_GR_RE = re.compile(r"\b(?:GR\.?|GROUP)\s*$", re.IGNORECASE)


def _merge_split_group_lines(lines: list[str]) -> list[str]:
    """
    Most cells wrap as three clean lines, e.g. ["EDCI 312", "GR J", "UTC 6"].
    But some wrap the group annotation differently, e.g.
    ["EPSC 311 GR", "J", "UTC-AC4"] - the "GR" sticks to the unit-code line
    and only the bare letter ends up on its own line. parse_unit_and_group
    can't find "GR" followed by a letter on the same line in that case, so
    it silently fails to extract anything, garbling the unit code (e.g.
    "EPSC311GR") and losing the real group letter entirely. Detect a line
    ending in a bare GR marker and merge it with the next line before
    parsing, so it reads the same as the normal case.
    """
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            _TRAILING_GR_RE.search(line)
            and i + 1 < len(lines)
            and re.match(r"^[A-Z0-9]{1,3}$", lines[i + 1].strip(), re.IGNORECASE)
        ):
            merged.append(f"{line} {lines[i + 1].strip()}")
            i += 2
        else:
            merged.append(line)
            i += 1
    return merged


def parse_pdf(path: str) -> ParseResult:
    result = ParseResult()
    col_to_day: dict[int, str] = {}
    col_to_hour_label: dict[int, str] = {}

    with pdfplumber.open(path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            if not tables:
                continue

            tables = sorted(tables, key=lambda t: t.bbox[1])

            for table in tables:
                data = table.extract()
                if not data:
                    continue

                r = 0
                num_rows = len(data)

                while r < num_rows:
                    row_data = data[r]
                    if not row_data or not any(row_data):
                        r += 1
                        continue

                    # A day-band header can recur mid-table (see module
                    # docstring) - re-derive the column maps every time one
                    # is seen rather than only trusting the table's row 0,
                    # and consume its hour-label row right along with it so
                    # neither is ever mistaken for a cohort/venue row below.
                    if _is_header_row(row_data):
                        hour_row = data[r + 1] if r + 1 < num_rows else []
                        col_to_day, col_to_hour_label = _build_column_maps(row_data, hour_row)
                        r += 2 if r + 1 < num_rows else 1
                        continue

                    if not col_to_day:
                        r += 1
                        continue

                    raw_label = row_data[0]
                    cohort_lines = _split_cell_lines(raw_label)
                    if not cohort_lines:
                        r += 1
                        continue
                    # Almost always a single line; the rare PDF line-wrap
                    # ("BSC REN.ENER TECH & MNT" / "Y1S1" on two lines)
                    # still needs both halves to match _COHORT_RE below.
                    cohort_label = " ".join(cohort_lines)

                    n_cols = len(row_data)
                    c = 1
                    while c < n_cols:
                        cell_raw = row_data[c]
                        if not cell_raw:
                            c += 1
                            continue

                        # A class spanning >1 hour is a merged cell -
                        # pdfplumber represents the spanned columns as None.
                        # Stop the span at a day boundary too, in case a
                        # cell is ever merged right up against one.
                        span_end = c
                        day = col_to_day.get(c)
                        while (
                            span_end + 1 < n_cols
                            and row_data[span_end + 1] is None
                            and col_to_day.get(span_end + 1) == day
                        ):
                            span_end += 1

                        start_label = col_to_hour_label.get(c)
                        end_label = col_to_hour_label.get(span_end)
                        if not (day and start_label and end_label):
                            c = span_end + 1
                            continue

                        start_time, _ = _hour_bounds(start_label)
                        _, end_time = _hour_bounds(end_label)

                        unit_lines = _merge_split_group_lines(
                            _merge_split_unit_code_lines(_split_cell_lines(cell_raw))
                        )
                        venue_item = "TBA"
                        if unit_lines and _is_likely_venue(unit_lines[-1]):
                            venue_item = unit_lines.pop()
                        elif unit_lines:
                            loose_venue = _extract_venue_prefix(unit_lines[-1])
                            if loose_venue:
                                venue_item = loose_venue
                                unit_lines.pop()

                        for u_text in unit_lines:
                            if not u_text or _is_likely_venue(u_text):
                                continue

                            clean_unit, group = parse_unit_and_group(u_text)
                            if not clean_unit or len(clean_unit) < 3:
                                continue

                            result.slots.append(
                                RawSlot(
                                    cohort_label=cohort_label,
                                    day=day,
                                    start_time=start_time,
                                    end_time=end_time,
                                    unit_code_raw=clean_unit,
                                    group=group,
                                    venue=venue_item,
                                    room=venue_item,
                                    page=page_idx,
                                    raw_cell_text=f"{clean_unit} [{group}] at {venue_item}",
                                )
                            )

                        c = span_end + 1

                    r += 1

    return result


def to_timetable_slot_dicts(result: ParseResult, academic_year: str = "2026/2027") -> list[dict]:
    out = []
    for s in result.slots:
        program_code = s.cohort_label
        year_of_study = 1
        semester = 1
        class_group = s.group
        stream = ""

        m = _COHORT_RE.match(s.cohort_label.strip())
        if m:
            program_code = m.group("program").strip()
            year_of_study = int(m.group("year"))
            semester = int(m.group("sem"))
            # The row's own sub-stream number, e.g. the "1" in "...Y3S1(1)".
            # Captured independently of class_group: a unit's own GR-letter
            # (parsed from its cell text) only distinguishes that unit's
            # specific pool-group, not which physical row/class it came from
            # - different unit pools in the same stream carry different
            # letters (see TimetableSlot.stream docstring), so this must not
            # be overwritten or skipped just because class_group already has
            # a value.
            #
            # class_group is deliberately left as "MAIN" here even when the
            # cohort has a numbered stream: a unit taught to the whole
            # stream with no further elective split (e.g. MATH301 under
            # ...Y3S1(1)) is genuinely ungrouped - relabelling it to
            # "GR_<stream>" would make it indistinguishable from a unit that
            # really is split into per-elective groups (e.g. CHEM323's
            # "GR_B"), which breaks class_group's MAIN/grouped semantics for
            # every stream-split program and defeats anything that keys off
            # it (e.g. AssignLecturersAPIView's group-hint matching). The
            # student's own stream is already carried on `stream` above, so
            # nothing is lost by leaving class_group alone.
            if m.group("cohort_sub"):
                stream = m.group("cohort_sub")

        unit_code = normalise_unit_code(s.unit_code_raw)
        # Every real Tharaka unit code is a letters+digits pair (COSC103,
        # GEOG144, CHTM0020, ...). A handful of source-PDF cells suffer
        # character-level extraction corruption pdfplumber can't recover
        # from (e.g. "OSC\nC 312" for "COSC 312") - a code that's come out
        # as letters-only or digits-only is that corruption, not a unit.
        if not unit_code or len(unit_code) < 3:
            continue
        if unit_code.isalpha() or unit_code.isdigit():
            result.warnings.append(
                f"page {s.page}: dropped unparseable unit code {unit_code!r} "
                f"for cohort {s.cohort_label!r} (likely PDF text-extraction corruption)"
            )
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
            "stream": stream[:10],
            "day_of_week": code_day,
            "start_time": start_str,
            "end_time": end_str,
            "room_code": room_str,
            "lecturer_university_id": "",
            "lecturer_name_text": "",
        })
    return out
