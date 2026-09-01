from typing import List, Dict, Any, Tuple
from datetime import date, timedelta
from django.db import transaction

from apps.units.models import Unit
from apps.programs.models import Program
from apps.departments.models import Department, Faculty
from apps.lecturers.models import Lecturer
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.timetable.utils import TimetableLogger


class TimetablePersistenceService:
    def __init__(self):
        """Initialize service with logging."""
        self.logger = TimetableLogger()

    def _preload_and_seed_cache(self, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Pre-fetch all required foreign-key objects in bulk queries to eliminate
        N+1 database round-trips during processing.
        """
        cache = {
            "term": {},
            "department": {},
            "program": {},
            "unit": {},
            "room": {},
            "lecturer": {},
        }

        # 1. Default Department & Faculty
        default_faculty, _ = Faculty.objects.get_or_create(
            code="GEN",
            defaults={"name": "General Faculty"}
        )
        default_dept, _ = Department.objects.get_or_create(
            code="COMP",
            defaults={"name": "School of Computing", "faculty": default_faculty}
        )
        cache["department"]["comp"] = default_dept

        # 2. Academic Terms
        term_pairs = {(r["academic_year"], int(r["semester"])) for r in rows if r.get("academic_year") and r.get("semester")}
        for year, sem in term_pairs:
            term = AcademicTerm.objects.filter(academic_year=year, semester=sem).first()
            if not term:
                today = date.today()
                term = AcademicTerm.objects.create(
                    academic_year=year,
                    semester=sem,
                    start_date=today,
                    end_date=today + timedelta(days=120),
                    is_current=False,
                )
            cache["term"][(year, sem)] = term

        # 3. Programs
        program_codes = {str(r["program_code"]).strip() for r in rows if r.get("program_code")}
        existing_programs = Program.objects.filter(code__in=program_codes)
        for p in existing_programs:
            cache["program"][p.code.lower()] = p

        missing_p_codes = [c for c in program_codes if c.lower() not in cache["program"]]
        if missing_p_codes:
            new_programs = [
                Program(
                    code=c[:64],
                    name=f"Program {c}"[:255],
                    department=default_dept,
                    duration_years=4
                )
                for c in missing_p_codes
            ]
            Program.objects.bulk_create(new_programs, ignore_conflicts=True)
            for p in Program.objects.filter(code__in=missing_p_codes):
                cache["program"][p.code.lower()] = p

        # 4. Units
        unit_codes = {str(r["unit_code"]).strip() for r in rows if r.get("unit_code")}
        existing_units = Unit.objects.filter(code__in=unit_codes)
        for u in existing_units:
            cache["unit"][u.code.lower()] = u

        missing_u_codes = [c for c in unit_codes if c.lower() not in cache["unit"]]
        if missing_u_codes:
            new_units = [
                Unit(
                    code=c[:64],
                    name=c[:255],
                    credit_hours=3.0,
                    department=default_dept
                )
                for c in missing_u_codes
            ]
            Unit.objects.bulk_create(new_units, ignore_conflicts=True)
            for u in Unit.objects.filter(code__in=missing_u_codes):
                cache["unit"][u.code.lower()] = u

        # 5. Rooms
        room_codes = {str(r["room_code"]).strip() for r in rows if r.get("room_code")}
        existing_rooms = Room.objects.filter(code__in=room_codes)
        for rm in existing_rooms:
            cache["room"][rm.code.lower()] = rm

        missing_r_codes = [c for c in room_codes if c.lower() not in cache["room"]]
        if missing_r_codes:
            new_rooms = [
                Room(
                    code=c[:20],
                    name=c[:100],
                    capacity=50,
                )
                for c in missing_r_codes
            ]
            Room.objects.bulk_create(new_rooms, ignore_conflicts=True)
            for rm in Room.objects.filter(code__in=missing_r_codes):
                cache["room"][rm.code.lower()] = rm

        # 6. Lecturers (optional)
        lecturer_ids = {
            str(r["lecturer_university_id"]).strip()
            for r in rows
            if r.get("lecturer_university_id") and str(r["lecturer_university_id"]).strip()
        }
        if lecturer_ids:
            existing_lecturers = Lecturer.objects.select_related("user").filter(
                user__university_id__in=lecturer_ids
            )
            for lec in existing_lecturers:
                if lec.user and lec.user.university_id:
                    cache["lecturer"][lec.user.university_id.lower()] = lec

        return cache

    @transaction.atomic
    def save_rows(
        self,
        upload_batch,
        rows: List[Dict[str, Any]]
    ) -> Tuple[List[TimetableSlot], List[Dict[str, Any]]]:
        if not rows:
            return [], []

        # 1. Preload all entities in bulk
        cache = self._preload_and_seed_cache(rows)

        slots_to_create = []
        errors = []
        seen_slot_keys = set()

        # 2. Map rows to model instances in memory
        for idx, row in enumerate(rows, start=1):
            try:
                term_key = (row["academic_year"], int(row["semester"]))
                term = cache["term"].get(term_key)
                if not term:
                    errors.append({"row_number": idx, "error": f"Academic term missing: {term_key}"})
                    continue

                program = cache["program"].get(str(row["program_code"]).strip().lower())
                unit = cache["unit"].get(str(row["unit_code"]).strip().lower())
                room = cache["room"].get(str(row["room_code"]).strip().lower())

                lec_id = str(row.get("lecturer_university_id") or "").strip().lower()
                lecturer = cache["lecturer"].get(lec_id) if lec_id else None

                day_val = str(row.get("day_of_week") or "").strip().upper()[:3]
                start_time_val = str(row.get("start_time") or "")
                end_time_val = str(row.get("end_time") or "")
                class_group_val = str(row.get("class_group") or "MAIN")
                year_of_study_val = int(row.get("year_of_study") or 1)

                slot_dedup_key = (
                    term.id,
                    program.id if program else None,
                    unit.id if unit else None,
                    year_of_study_val,
                    day_val,
                    start_time_val,
                    end_time_val,
                    room.id if room else None,
                    class_group_val,
                )

                if slot_dedup_key in seen_slot_keys:
                    continue
                seen_slot_keys.add(slot_dedup_key)

                slot = TimetableSlot(
                    term=term,
                    unit=unit,
                    program=program,
                    year_of_study=year_of_study_val,
                    lecturer=lecturer,
                    room=room,
                    day_of_week=day_val,
                    start_time=start_time_val,
                    end_time=end_time_val,
                    class_group=class_group_val,
                    upload_batch=upload_batch,
                )
                slots_to_create.append(slot)

            except Exception as e:
                errors.append({"row_number": idx, "error": f"Row processing error: {str(e)}"})

        # 3. Fast Bulk Insertion
        if slots_to_create:
            TimetableSlot.objects.bulk_create(slots_to_create, batch_size=500, ignore_conflicts=True)

        return slots_to_create, errors
