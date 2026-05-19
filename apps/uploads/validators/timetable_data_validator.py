from __future__ import annotations

import re
from datetime import time

from apps.uploads.utils import clean_text, parse_time_value


class TimetableDataValidator:
    academic_year_pattern = re.compile(r"^\d{4}[/-]\d{4}$")

    @staticmethod
    def validate_row(row: dict, *, row_number: int, mappings: dict) -> list[str]:
        errors: list[str] = []
        if not mappings.get("department"):
            errors.append("Invalid department")
        if not mappings.get("program"):
            errors.append("Invalid program")
        if not mappings.get("unit"):
            errors.append("Invalid unit")
            
        lecturer_val = clean_text(row.get("lecturer"))
        if lecturer_val and not mappings.get("lecturer"):
            errors.append("Invalid lecturer")
            
        room_val = clean_text(row.get("room"))
        if room_val and room_val.upper() != "TBA" and not mappings.get("room"):
            errors.append("Invalid room")
            
        if not mappings.get("time_slot"):
            errors.append("Invalid time slot")

        semester = row.get("semester")
        if semester not in {1, 2}:
            errors.append("Invalid semester value")

        study_year = row.get("study_year")
        if not isinstance(study_year, int) or not (1 <= study_year <= 10):
            errors.append("Invalid study year")

        academic_year = clean_text(row.get("academic_year"))
        if not academic_year or not TimetableDataValidator.academic_year_pattern.match(academic_year):
            errors.append("Invalid academic year")

        start_time = parse_time_value(row.get("start_time"))
        end_time = parse_time_value(row.get("end_time"))
        if not isinstance(start_time, time) or not isinstance(end_time, time):
            errors.append("Invalid time format")
        elif start_time >= end_time:
            errors.append("Start time must be before end time")

        return errors