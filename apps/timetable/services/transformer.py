from datetime import time


class TimetableTransformService:
    def transform_row(self, row):
        start = row["start_time"]
        end = row["end_time"]

        if hasattr(start, "time"):
            start = start.time()
        if hasattr(end, "time"):
            end = end.time()

        if not isinstance(start, time) or not isinstance(end, time):
            raise ValueError("start_time and end_time must be valid time values")

        return {
            "academic_year": str(row["academic_year"]),
            "semester": int(row["semester"]),
            "program_code": str(row["program_code"]).strip(),
            "unit_code": str(row["unit_code"]).strip(),
            "year_of_study": int(row["year_of_study"]),
            "day_of_week": str(row["day_of_week"]).strip().lower()[:3],
            "start_time": start,
            "end_time": end,
            "room_code": str(row["room_code"]).strip(),
            "lecturer_university_id": str(row["lecturer_university_id"]).strip(),
            "class_group": str(row.get("class_group", "MAIN")).strip() or "MAIN",
        }
