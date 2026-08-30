"""Parse text-based PDF timetable tables into shared timetable rows."""

from __future__ import annotations

import pandas as pd

from apps.timetable.services.excel_parser import normalise_dataframe


def _clean_headers(header_row: list) -> list[str]:
    """
    Turn a raw pdfplumber header row into unique, non-blank column names.
    pdfplumber commonly emits None/blank cells for merged headers and
    repeated labels for spacer columns — both break pandas' column
    reindexing during concat, so we normalise them here before the
    DataFrame is ever built.
    """
    cleaned = []
    seen: dict[str, int] = {}
    for idx, col in enumerate(header_row):
        name = str(col).strip() if col is not None and str(col).strip() else f"col_{idx}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        cleaned.append(name)
    return cleaned


def parse_pdf(file) -> list[dict]:
    """Extract and normalize timetable tables from every page of a PDF."""
    import pdfplumber

    frames = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if len(table) > 1:
                    headers = _clean_headers(table[0])
                    frames.append(pd.DataFrame(table[1:], columns=headers))

    if not frames:
        raise ValueError(
            "No tables could be extracted from the PDF. "
            "Scanned/image PDFs are not supported because they have no text layer."
        )

    try:
        combined = pd.concat(frames, ignore_index=True, sort=False)
    except Exception as exc:
        raise ValueError(
            f"Could not merge extracted PDF tables — inconsistent table structure "
            f"across pages: {exc}"
        ) from exc

    return normalise_dataframe(combined)