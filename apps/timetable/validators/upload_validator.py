import re
import os
from datetime import datetime, time
from typing import List, Dict, Any, Tuple

from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.timetable.utils import (
    REQUIRED_TIMETABLE_COLUMNS,
    VALID_DAYS,
)


class ExcelFileValidator:
    """Validates uploaded timetable file extension and size."""
    
    VALID_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf", ".docx"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    @staticmethod
    def validate_file_extension(file_name: str) -> None:
        import os
        _, ext = os.path.splitext(file_name.lower())
        
        if ext not in ExcelFileValidator.VALID_EXTENSIONS:
            raise DRFValidationError({
                "file": f"Only Excel, CSV, PDF, or Word files (.xlsx, .xls, .csv, .pdf, .docx) are supported. Got: {ext}"
            })
    
    @staticmethod
    def validate_file_size(file_size: int) -> None:
        """
        Validate file size does not exceed limit.
        
        Args:
            file_size: Size of file in bytes
            
        Raises:
            DRFValidationError: If file exceeds size limit
        """
        if file_size > ExcelFileValidator.MAX_FILE_SIZE:
            max_mb = ExcelFileValidator.MAX_FILE_SIZE / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            raise DRFValidationError({
                "file": f"File size exceeds {max_mb}MB limit. Got: {actual_mb:.2f}MB"
            })


class TimetableUploadValidator:
    """Validates timetable Excel data structure and content."""
    
    @staticmethod
    def _parse_time_string(value: str):
        """Parse 'HH:MM' or 'HH:MM:SS' strings into a datetime.time, or None."""
        value = value.strip()
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
        return None
    
    @staticmethod
    def validate_columns(columns: List[str]) -> None:
        column_set = set(col.strip().lower() for col in columns)
        missing = REQUIRED_TIMETABLE_COLUMNS - column_set
        
        if missing:
            raise DRFValidationError({
                "columns": f"Missing required columns: {', '.join(sorted(missing))}"
            })
    
    @staticmethod
    def validate_row(row: Dict[str, Any], row_number: int) -> Tuple[bool, List[str]]:
        errors = []
        
        # Check for empty required fields
        for field in REQUIRED_TIMETABLE_COLUMNS:
            value = row.get(field)
            if value is None or (isinstance(value, str) and value.strip() == ""):
                errors.append(f"Row {row_number}: Missing required field '{field}'")
        
        if errors:
            return False, errors
        
        # Validate academic_year format (e.g., "2023-2024" or "2023")
        academic_year = str(row.get("academic_year", "")).strip()
        if not re.match(r"^\d{4}([-/]\d{4})?$", academic_year):
            errors.append(f"Row {row_number}: Invalid academic_year format '{academic_year}'")
        
        # Validate semester is numeric and reasonable
        try:
            semester = int(row.get("semester"))
            if semester not in (1, 2, 3):  # Most universities have 2-3 semesters
                errors.append(f"Row {row_number}: Invalid semester value '{semester}' (expected 1-3)")
        except (ValueError, TypeError):
            errors.append(f"Row {row_number}: Semester must be a number")
        
        # Validate year_of_study
        try:
            year_of_study = int(row.get("year_of_study"))
            if year_of_study < 1 or year_of_study > 10:
                errors.append(f"Row {row_number}: Invalid year_of_study '{year_of_study}'")
        except (ValueError, TypeError):
            errors.append(f"Row {row_number}: Year of study must be a number")
        
        # Validate day_of_week
        day_abbr = str(row.get("day_of_week", "")).strip().lower()[:3]
        if day_abbr not in VALID_DAYS:
            errors.append(f"Row {row_number}: Invalid day_of_week '{day_abbr}'")
        
        # Validate times
        try:
            start_time = row.get("start_time")
            end_time = row.get("end_time")
            
            # Handle pandas Timestamp or datetime Time objects
            if hasattr(start_time, "time"):
                start_time = start_time.time()
            if hasattr(end_time, "time"):
                end_time = end_time.time()
            
            # Handle "HH:MM" / "HH:MM:SS" string times (parsers emit strings)
            if isinstance(start_time, str):
                start_time = TimetableUploadValidator._parse_time_string(start_time)
            if isinstance(end_time, str):
                end_time = TimetableUploadValidator._parse_time_string(end_time)
            
            if not isinstance(start_time, time):
                errors.append(f"Row {row_number}: start_time must be a valid time")
            if not isinstance(end_time, time):
                errors.append(f"Row {row_number}: end_time must be a valid time")
            
            if isinstance(start_time, time) and isinstance(end_time, time):
                if start_time >= end_time:
                    errors.append(
                        f"Row {row_number}: start_time ({start_time}) must be before "
                        f"end_time ({end_time})"
                    )
        except (ValueError, TypeError) as e:
            errors.append(f"Row {row_number}: Invalid time format - {str(e)}")
        
        # Validate string fields length and format
        program_code = str(row.get("program_code", "")).strip()
        if not program_code or len(program_code) > 20:
            errors.append(f"Row {row_number}: Invalid program_code '{program_code}'")
        
        unit_code = str(row.get("unit_code", "")).strip()
        if not unit_code or len(unit_code) > 20:
            errors.append(f"Row {row_number}: Invalid unit_code '{unit_code}'")
        
        room_code = str(row.get("room_code", "")).strip()
        if not room_code or len(room_code) > 20:
            errors.append(f"Row {row_number}: Invalid room_code '{room_code}'")
        
        lecturer_id = str(row.get("lecturer_university_id", "")).strip()
        if lecturer_id and len(lecturer_id) > 20:
            errors.append(f"Row {row_number}: Invalid lecturer_university_id '{lecturer_id}'")
        
        # Validate class_group (optional)
        class_group = str(row.get("class_group", "MAIN")).strip()
        if len(class_group) > 50:
            errors.append(f"Row {row_number}: class_group too long (max 50 chars)")
        
        return len(errors) == 0, errors


class TimetableDataConsistencyValidator:
    """Validates consistency of timetable data."""
    
    @staticmethod
    def validate_no_duplicate_sessions(
        rows: List[Dict[str, Any]]
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        seen = {}
        duplicates = []
        
        for idx, row in enumerate(rows):
            # Create a unique key for each session
            key = (
                row["academic_year"],
                row["semester"],
                row["program_code"],
                row["unit_code"],
                row["year_of_study"],
                row["day_of_week"],
                row["start_time"],
                row["end_time"],
                row["room_code"],
            )
            
            if key in seen:
                duplicates.append({
                    "first_occurrence": seen[key],
                    "duplicate_at_row": idx + 2,  # +2 for header and 1-based indexing
                    "data": row,
                })
            else:
                seen[key] = idx + 2
        
        return len(duplicates) == 0, duplicates


class ConflictValidationRules:
    """Rules for detecting potential timetable conflicts."""
    
    # Minimum gap between consecutive sessions (in minutes)
    MIN_GAP_BETWEEN_SESSIONS = 0
    
    @staticmethod
    def would_cause_lecturer_conflict(
        new_start: time,
        new_end: time,
        existing_start: time,
        existing_end: time,
    ) -> bool:
        # Sessions overlap if: new_start < existing_end AND existing_start < new_end
        return new_start < existing_end and existing_start < new_end
    
    @staticmethod
    def would_cause_room_conflict(
        new_start: time,
        new_end: time,
        existing_start: time,
        existing_end: time,
    ) -> bool:
        return new_start < existing_end and existing_start < new_end

