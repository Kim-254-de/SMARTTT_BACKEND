from datetime import datetime, time
from typing import Dict, Any, List, Tuple

from apps.timetable.utils import DataValidationException, VALID_DAYS


class TimetableTransformService:
    def transform_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            start_time = self._parse_time(row.get("start_time"))
            end_time = self._parse_time(row.get("end_time"))
            
            # Validate time order
            if start_time >= end_time:
                raise DataValidationException(
                    f"start_time {start_time} must be before end_time {end_time}"
                )
            
            # Normalize day of week
            day_abbr = str(row.get("day_of_week", "")).strip().lower()[:3]
            if day_abbr not in VALID_DAYS:
                raise DataValidationException(f"Invalid day_of_week: '{day_abbr}'")
            
            return {
                "academic_year": str(row.get("academic_year", "")).strip(),
                "semester": int(row.get("semester", 0)),
                "program_code": str(row.get("program_code", "")).strip(),
                "unit_code": str(row.get("unit_code", "")).strip(),
                "year_of_study": int(row.get("year_of_study", 0)),
                "day_of_week": day_abbr,
                "start_time": start_time,
                "end_time": end_time,
                "room_code": str(row.get("room_code", "")).strip(),
                "lecturer_university_id": str(row.get("lecturer_university_id") or "").strip(),
                "class_group": str(row.get("class_group", "MAIN")).strip() or "MAIN",
                "notes": row.get("notes", ""),
                "venue_name": row.get("venue_name", ""),
                "session_type": row.get("session_type", "LECTURE"),
            }
            
        except (ValueError, TypeError) as e:
            raise DataValidationException(f"Error transforming row: {str(e)}")
    
    def transform_rows(self, rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        transformed = []
        errors = []
        
        for idx, row in enumerate(rows, 1):
            try:
                transformed_row = self.transform_row(row)
                transformed.append(transformed_row)
            except Exception as e:
                errors.append({
                    "row_number": idx,
                    "error": str(e),
                    "data": row,
                })
        
        return transformed, errors
    
    @staticmethod
    def _parse_time(time_value: Any) -> time:
        if time_value is None:
            raise ValueError("Time value is None")
        
        # Already a time object
        if isinstance(time_value, time):
            return time_value
        
        # Has a .time() method (datetime, Timestamp, etc.)
        if hasattr(time_value, "time"):
            return time_value.time()
        
        # String representation
        if isinstance(time_value, str):
            time_str = time_value.strip()
            
            # Try common time formats
            formats = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"]
            
            for fmt in formats:
                try:
                    parsed = datetime.strptime(time_str, fmt)
                    return parsed.time()
                except ValueError:
                    continue
            
            raise ValueError(f"Could not parse time '{time_str}'")
        
        raise ValueError(f"Unsupported time format: {type(time_value)}")

