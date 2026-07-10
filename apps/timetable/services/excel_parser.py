"""
Parse an Excel/CSV timetable uploaded by admin.

Expected flat columns (case-insensitive, spaces/underscores interchangeable):
  unit_code | unit_name | program | year_of_study | day | start_time | end_time
  | room | lecturer | academic_year | semester

Also handles 2-D grid format where rows = cohorts and columns = day/time slots.
Cell content is either "UNIT CODE" or "UNIT CODE\nROOM CODE".
"""
from __future__ import annotations

import re
import pandas as pd

REQUIRED_FLAT_COLS = {"unit_code", "day", "start_time", "end_time"}

DAY_MAP = {
    "mon": "MON", "monday": "MON",
    "tue": "TUE", "tues": "TUE", "tuesday": "TUE",
    "wed": "WED", "wednesday": "WED",
    "thu": "THU", "thursday": "THU",
    "fri": "FRI", "friday": "FRI",
    "sat": "SAT", "saturday": "SAT",
}

COMBINED_PATTERN = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat)[a-z]*\b[\s\S]*?\b(\d+)\s*[-:]\s*(\d+)\b",
    re.IGNORECASE,
)
COHORT_PATTERN = re.compile(r"\bY(\d)(?:S(\d))?\b", re.IGNORECASE)
TIME_RANGE_PATTERN = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*[-:]\s*(\d{1,2})(?::(\d{2}))?$")


def _normalise_col(col: str) -> str:
    return re.sub(r"[\s_]+", "_", str(col).strip().lower())


def _fmt_time(hour: int, minute: int = 0) -> str:
    return f"{hour:02d}:{minute:02d}"


def _detect_grid(df: pd.DataFrame) -> bool:
    """Return True if the sheet looks like a 2-D grid timetable."""
    for idx in range(min(10, len(df))):
        row_vals = [str(x) for x in df.iloc[idx].values]
        hits = sum(1 for v in row_vals if COMBINED_PATTERN.search(v))
        if hits >= 3:
            return True
    return False


def _parse_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Convert 2-D grid to flat rows."""
    # ── locate the header row ────────────────────────────────────────────────
    header_row_idx = None
    col_map: dict[int, dict] = {}

    for idx in range(min(15, len(df))):
        row_vals = [str(x) for x in df.iloc[idx].values]
        hits = sum(1 for v in row_vals if COMBINED_PATTERN.search(v))
        if hits >= 3:
            header_row_idx = idx
            break

    if header_row_idx is None:
        return df  # fall back to flat

    current_day = "MON"
    for col_idx in range(1, len(df.columns)):
        cell = str(df.iloc[header_row_idx, col_idx]).strip()
        m = COMBINED_PATTERN.search(cell)
        if m:
            current_day = DAY_MAP.get(m.group(1).lower()[:3], "MON")
            sh, eh = int(m.group(2)), int(m.group(3))
            col_map[col_idx] = {"day": current_day, "start_time": _fmt_time(sh), "end_time": _fmt_time(eh)}
        else:
            tm = re.search(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b", cell)
            if tm:
                sh, eh = int(tm.group(1)), int(tm.group(2))
                col_map[col_idx] = {"day": current_day, "start_time": _fmt_time(sh), "end_time": _fmt_time(eh)}

    # ── extract academic year / semester from top rows ───────────────────────
    academic_year, semester = "2025/2026", 1
    for idx in range(min(header_row_idx + 1, 10)):
        text = " ".join(str(x) for x in df.iloc[idx].values if pd.notna(x))
        ym = re.search(r"\b(20\d{2})\b", text)
        if ym:
            y = int(ym.group(1))
            academic_year = f"{y}/{y+1}"
        if any(t in text.lower() for t in ["semester 2", "second semester"]):
            semester = 2

    # ── iterate data rows ────────────────────────────────────────────────────
    flat_rows = []
    for row_idx in range(header_row_idx + 1, len(df)):
        cohort_val = df.iloc[row_idx, 0]
        if pd.isna(cohort_val) or not str(cohort_val).strip():
            continue
        cohort_str = str(cohort_val).strip()
        cm = COHORT_PATTERN.search(cohort_str)
        study_year = int(cm.group(1)) if cm else 1
        row_sem = int(cm.group(2)) if cm and cm.group(2) else semester
        program_name = cohort_str[: cm.start()].strip().rstrip(".").strip() if cm else cohort_str

        for col_idx, slot in col_map.items():
            cell = df.iloc[row_idx, col_idx]
            if pd.isna(cell) or not str(cell).strip():
                continue
            lines = [ln.strip() for ln in str(cell).split("\n") if ln.strip()]
            unit_code = lines[0] if lines else None
            room_code = lines[1] if len(lines) > 1 else "TBA"
            if not unit_code:
                continue
            flat_rows.append({
                "unit_code": unit_code.strip(),
                "unit_name": unit_code.strip(),
                "program": program_name,
                "year_of_study": study_year,
                "semester": row_sem,
                "academic_year": academic_year,
                "day": slot["day"],
                "start_time": slot["start_time"],
                "end_time": slot["end_time"],
                "room": room_code,
                "lecturer": "",
            })
    return pd.DataFrame(flat_rows)


def parse_excel(file) -> list[dict]:
    """
    Main entry point.
    Returns a list of normalised dicts ready for the mapping service.
    Raises ValueError if the file structure is unreadable.
    """
    try:
        df = pd.read_excel(file, sheet_name=0, dtype=object, engine="openpyxl")
    except Exception as exc:
        raise ValueError(f"Cannot read Excel file: {exc}") from exc

    df = df.dropna(how="all").reset_index(drop=True)

    if _detect_grid(df):
        df = _parse_grid(df)
    else:
        df.columns = [_normalise_col(c) for c in df.columns]
        missing = REQUIRED_FLAT_COLS - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

    rows = []
    for _, row in df.iterrows():
        raw = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}

        # normalise day
        day_raw = str(raw.get("day", "")).strip().lower()[:3]
        raw["day"] = DAY_MAP.get(day_raw, day_raw.upper())

        # normalise times — accept "08:00", "8", "8-10" etc.
        for field in ("start_time", "end_time"):
            val = str(raw.get(field, "")).strip()
            # pure integer like "8"
            if re.match(r"^\d{1,2}$", val):
                raw[field] = _fmt_time(int(val))
            # already HH:MM
            elif re.match(r"^\d{1,2}:\d{2}$", val):
                raw[field] = val
        rows.append(raw)
    return rows
