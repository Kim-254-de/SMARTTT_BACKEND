"""Parse text-based PDF timetable tables into shared timetable rows."""

from __future__ import annotations

import pandas as pd

from apps.timetable.services.excel_parser import normalise_dataframe


def parse_pdf(file) -> list[dict]:
    """Extract and normalize timetable tables from every page of a PDF."""
    import pdfplumber

    frames = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                if len(table) > 1:
                    frames.append(pd.DataFrame(table[1:], columns=table[0]))

    if not frames:
        raise ValueError(
            "No tables could be extracted from the PDF. "
            "Scanned/image PDFs are not supported because they have no text layer."
        )

    return normalise_dataframe(pd.concat(frames, ignore_index=True))