from __future__ import annotations

import re
import pandas as pd
from django.core.files.uploadedfile import UploadedFile

from apps.uploads.utils import ParsedWorkbookRow, normalize_column_name, normalize_row_payload


class ExcelParserService:
    @staticmethod
    def read_workbook(uploaded_file: UploadedFile, sheet_name: int | str = 0) -> pd.DataFrame:
        dataframe = pd.read_excel(uploaded_file, sheet_name=sheet_name, dtype=object, engine="openpyxl")
        dataframe = dataframe.dropna(how="all").reset_index(drop=True)
        
        # Automatically detect and convert 2D grid-based timetables to a flat tabular layout
        dataframe = ExcelParserService.convert_grid_to_flat(dataframe)
        
        dataframe.columns = [normalize_column_name(column) for column in dataframe.columns]
        return dataframe

    @staticmethod
    def convert_grid_to_flat(df: pd.DataFrame) -> pd.DataFrame:
        """
        Detects if a DataFrame is a 2D Grid Timetable (cohorts as rows, day/time as columns)
        and converts it into a standardized flat tabular format.
        """
        # 1. Locate the day and time header rows by scanning the first 15 rows
        day_row_idx = None
        time_row_idx = None
        days_of_week = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
        
        for idx in range(min(15, len(df))):
            row_values = [str(x).lower().strip() for x in df.iloc[idx].values]
            has_day = any(day in row_values for day in days_of_week)
            has_time = any(re.match(r'^\d+[-:]\d+$', str(x).strip()) for x in df.iloc[idx].values if pd.notna(x))
            
            if has_day and not has_time:
                day_row_idx = idx
            elif has_time:
                time_row_idx = idx
                if day_row_idx is None:
                    # Look in the rows above the time row for the day headers
                    for prev_idx in range(idx):
                        prev_row_values = [str(x).lower().strip() for x in df.iloc[prev_idx].values]
                        if any(day in prev_row_values for day in days_of_week):
                            day_row_idx = prev_idx
                            break
                break
                
        # If we didn't find a time slot row, it is likely not a grid timetable, return as-is
        if time_row_idx is None:
            return df
            
        if day_row_idx is None and time_row_idx > 0:
            day_row_idx = time_row_idx - 1
            
        # 2. Extract academic year and semester from the top rows if possible
        academic_year = "2025/2026"
        semester = 1
        
        for idx in range(min(10, len(df))):
            row_text = " ".join([str(x) for x in df.iloc[idx].values if pd.notna(x)])
            year_match = re.search(r'\b(20\d{2})\b', row_text)
            if year_match:
                year = int(year_match.group(1))
                academic_year = f"{year-1}/{year}"
            
            if any(term in row_text.lower() for term in ["semester 1", "first semester"]):
                semester = 1
            elif any(term in row_text.lower() for term in ["semester 2", "second semester", "may-august"]):
                semester = 2
                
        # 3. Build column mappings: col_idx -> (day, start_time, end_time)
        day_map = {
            "mon": "MON", "monday": "MON",
            "tue": "TUE", "tues": "TUE", "tuesday": "TUE",
            "wed": "WED", "wednesday": "WED",
            "thu": "THU", "thursday": "THU",
            "fri": "FRI", "friday": "FRI",
            "sat": "SAT", "saturday": "SAT",
            "sun": "SUN", "sunday": "SUN",
        }
        
        col_mappings = {}
        current_day = "MON"
        
        for col_idx in range(1, len(df.columns)):
            # Resolve Day (handles merged cells in headers by scanning left)
            if day_row_idx is not None:
                day_val = df.iloc[day_row_idx, col_idx]
                if pd.notna(day_val) and str(day_val).strip():
                    normalized_day = str(day_val).strip().lower()
                    for key, val in day_map.items():
                        if normalized_day == key or normalized_day.startswith(key):
                            current_day = val
                            break
                            
            # Resolve Time Slot
            time_val = df.iloc[time_row_idx, col_idx]
            if pd.notna(time_val) and str(time_val).strip():
                slot_str = str(time_val).strip()
                match = re.match(r'^(\d+)(?::(\d+))?\s*[-:]\s*(\d+)(?::(\d+))?$', slot_str)
                if match:
                    start_hour = int(match.group(1))
                    start_min = int(match.group(2)) if match.group(2) else 0
                    end_hour = int(match.group(3))
                    end_min = int(match.group(4)) if match.group(4) else 0
                    
                    start_time = f"{start_hour:02d}:{start_min:02d}"
                    end_time = f"{end_hour:02d}:{end_min:02d}"
                    
                    col_mappings[col_idx] = {
                        "day": current_day,
                        "start_time": start_time,
                        "end_time": end_time,
                    }
                    
        # 4. Process program rows (everything below the time header row)
        flat_rows = []
        cohort_pattern = re.compile(r'\bY(\d)(?:S(\d))?\b', re.IGNORECASE)
        
        start_data_row = time_row_idx + 1
        for row_idx in range(start_data_row, len(df)):
            cohort_val = df.iloc[row_idx, 0]
            if pd.isna(cohort_val) or not str(cohort_val).strip():
                continue
                
            cohort_str = str(cohort_val).strip()
            
            # Parse cohort (e.g. "DIP CRIMINOLOGY Y2S1")
            cohort_match = cohort_pattern.search(cohort_str)
            study_year = 1
            row_semester = semester
            
            if cohort_match:
                study_year = int(cohort_match.group(1))
                if cohort_match.group(2):
                    row_semester = int(cohort_match.group(2))
                program_name = cohort_str[:cohort_match.start()].strip().rstrip(".").strip()
            else:
                program_name = cohort_str
                
            if not program_name:
                continue
                
            # Iterate over time slot columns
            for col_idx, time_info in col_mappings.items():
                cell_val = df.iloc[row_idx, col_idx]
                if pd.isna(cell_val) or not str(cell_val).strip():
                    continue
                    
                cell_str = str(cell_val).strip()
                lines = [line.strip() for line in cell_str.split('\n') if line.strip()]
                
                unit_code = None
                room = None
                
                if len(lines) >= 2:
                    unit_code = lines[0]
                    room = lines[1]
                elif len(lines) == 1:
                    text = lines[0]
                    # Try to separate Unit Code (e.g. "CRIM 0209") and Room (e.g. "TC 4")
                    match = re.search(r'\b([A-Za-z]+[-_]?\s*\d+)\b', text)
                    if match:
                        unit_code = match.group(1)
                        room = text.replace(unit_code, "").strip().replace("/", "").strip()
                    else:
                        parts = text.split(None, 1)
                        unit_code = parts[0]
                        room = parts[1] if len(parts) > 1 else "TBA"
                
                if not unit_code:
                    continue
                    
                unit_code = unit_code.strip()
                room = room.strip() if room else "TBA"
                
                # Build flat record
                flat_rows.append({
                    "unit_code": unit_code,
                    "unit_name": unit_code,
                    "program": program_name,
                    "department": "",
                    "lecturer": "",
                    "room": room,
                    "day": time_info["day"],
                    "start_time": time_info["start_time"],
                    "end_time": time_info["end_time"],
                    "semester": row_semester,
                    "study_year": study_year,
                    "academic_year": academic_year,
                    "session_type": "lecture",
                })
                
        return pd.DataFrame(flat_rows)

    @staticmethod
    def parse_rows(dataframe: pd.DataFrame) -> list[ParsedWorkbookRow]:
        rows: list[ParsedWorkbookRow] = []
        for index, row in dataframe.iterrows():
            raw_data = {key: (None if pd.isna(value) else value) for key, value in row.to_dict().items()}
            rows.append(
                ParsedWorkbookRow(
                    row_number=index + 2,
                    raw_data=raw_data,
                    normalized_data=normalize_row_payload(raw_data),
                )
            )
        return rows