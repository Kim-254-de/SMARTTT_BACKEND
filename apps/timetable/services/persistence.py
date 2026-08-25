from typing import List, Dict, Any, Tuple
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

from apps.units.models import Unit
from apps.programs.models import Program
from apps.departments.models import Department
from apps.lecturers.models import Lecturer
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.timetable.utils import (
    DatabaseOperationException,
    ResourceNotFoundException,
    DuplicateSessionException,
    TimetableLogger,
)


class TimetablePersistenceService:
    def __init__(self):
        """Initialize service with logging."""
        self.logger = TimetableLogger()
    
    @transaction.atomic
    def save_rows(
        self,
        upload_batch,
        rows: List[Dict[str, Any]]
    ) -> Tuple[List[TimetableSlot], List[Dict[str, Any]]]:
        saved_slots = []
        errors = []
        
        # Per-batch caches: the same program/unit/room/lecturer/term codes
        # commonly repeat across hundreds of rows in a real timetable upload,
        # so cache lookups by code instead of re-querying the database on
        # every single row.
        cache = {
            "term": {},
            "department": {},
            "program": {},
            "unit": {},
            "room": {},
            "lecturer": {},
        }
        
        for idx, row in enumerate(rows, 1):
            try:
                # Each row gets its own savepoint so a genuine database-level
                # error (e.g. a constraint violation) on one row can't poison
                # the whole transaction and cascade-fail every row after it.
                #
                # Cache writes are only merged in AFTER the savepoint commits
                # successfully - if we wrote to the shared cache mid-row and
                # that row later failed for an unrelated reason (e.g. a bad
                # room_code after a new Program/Unit was already created),
                # the savepoint rollback would undo that Program/Unit, but
                # the cache would still hold a dangling reference to it and
                # poison every later row that shares that code.
                pending_cache = {k: {} for k in cache}
                with transaction.atomic():
                    slot = self._get_or_create_slot(upload_batch, row, cache, pending_cache)
                for section, entries in pending_cache.items():
                    cache[section].update(entries)
                saved_slots.append(slot)
                
            except DuplicateSessionException as e:
                errors.append({
                    "row_number": idx,
                    "error": str(e),
                    "error_code": "DUPLICATE_SESSION",
                    "data": {k: v for k, v in row.items() if k not in ["start_time", "end_time"]}
                })
            except ResourceNotFoundException as e:
                errors.append({
                    "row_number": idx,
                    "error": str(e),
                    "error_code": "RESOURCE_NOT_FOUND",
                    "data": {k: v for k, v in row.items() if k not in ["start_time", "end_time"]}
                })
            except Exception as e:
                errors.append({
                    "row_number": idx,
                    "error": f"Unexpected error: {str(e)}",
                    "error_code": "DATABASE_ERROR",
                    "data": {k: v for k, v in row.items() if k not in ["start_time", "end_time"]}
                })
                self.logger.log_database_error(
                    "CREATE_SLOT",
                    str(e),
                    upload_batch.id
                )
        
        return saved_slots, errors
    
    def _get_or_create_slot(
        self,
        upload_batch,
        row: Dict[str, Any],
        cache: Dict[str, Dict[str, Any]] = None,
        pending_cache: Dict[str, Dict[str, Any]] = None,
    ) -> TimetableSlot:
        if cache is None:
            cache = {"term": {}, "department": {}, "program": {}, "unit": {}, "room": {}, "lecturer": {}}
        if pending_cache is None:
            pending_cache = {k: {} for k in cache}

        # Get AcademicTerm
        term_key = (row["academic_year"], row["semester"])
        term = cache["term"].get(term_key)
        if term is None:
            try:
                term = AcademicTerm.objects.get(
                    academic_year=row["academic_year"],
                    semester=row["semester"]
                )
            except AcademicTerm.DoesNotExist:
                raise ResourceNotFoundException(
                    f"Academic term not found: {row['academic_year']} S{row['semester']}"
                )
            pending_cache["term"][term_key] = term

        # Get or create Department (for program/unit assignment)
        department = cache["department"].get("COMP")
        if department is None:
            department = Department.objects.filter(code__iexact="COMP").first()
            if not department:
                from apps.departments.models import Faculty
                default_faculty, _ = Faculty.objects.get_or_create(
                    code="GEN",
                    defaults={"name": "General"}
                )
                department, _ = Department.objects.get_or_create(
                    code="COMP",
                    defaults={"name": "School of Computing", "faculty": default_faculty}
                )
            pending_cache["department"]["COMP"] = department
            
        # Get or create Program
        program_code = row["program_code"]
        program_key = program_code.lower()
        program = cache["program"].get(program_key)
        if program is None:
            program = Program.objects.filter(code__iexact=program_code).first()
            if not program:
                program = Program.objects.create(
                    code=program_code[:64],
                    name=f"Program {program_code}"[:255],
                    department=department,
                    duration_years=4
                )
            pending_cache["program"][program_key] = program
            
        # Get or create Unit
        unit_code = row["unit_code"]
        unit_key = unit_code.lower()
        unit = cache["unit"].get(unit_key)
        if unit is None:
            unit = Unit.objects.filter(code__iexact=unit_code).first()
            if not unit:
                unit_name = row.get("unit_name") or unit_code
                unit = Unit.objects.create(
                    code=unit_code[:64],
                    name=unit_name[:255],
                    credit_hours=3.0,
                    department=department
                )
            pending_cache["unit"][unit_key] = unit
        
        # Get Room
        room_key = row["room_code"]
        room = cache["room"].get(room_key)
        if room is None:
            try:
                room = Room.objects.get(code=row["room_code"])
            except Room.DoesNotExist:
                raise ResourceNotFoundException(
                    f"Room not found: {row['room_code']}"
                )
            pending_cache["room"][room_key] = room
        
        # Get Lecturer (optional — a slot can exist before a lecturer is
        # assigned; assignment happens later via the allocation upload)
        lecturer_university_id = str(row.get("lecturer_university_id") or "").strip()
        lecturer = None
        if lecturer_university_id:
            lecturer = cache["lecturer"].get(lecturer_university_id)
            if lecturer is None:
                try:
                    lecturer = Lecturer.objects.select_related("user").get(
                        user__university_id=lecturer_university_id
                    )
                except Lecturer.DoesNotExist:
                    raise ResourceNotFoundException(
                        f"Lecturer not found: {lecturer_university_id}"
                    )
                pending_cache["lecturer"][lecturer_university_id] = lecturer
        
        # Check for duplicate
        existing = TimetableSlot.objects.filter(
            term=term,
            unit=unit,
            program=program,
            year_of_study=row["year_of_study"],
            lecturer=lecturer,
            room=room,
            day_of_week=row["day_of_week"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            class_group=row["class_group"],
        ).exists()
        
        if existing:
            raise DuplicateSessionException(
                f"Duplicate session: {unit.code} "
                f"{row['day_of_week']} {row['start_time']}-{row['end_time']}"
            )
        
        # Create new slot
        slot = TimetableSlot.objects.create(
            term=term,
            unit=unit,
            program=program,
            year_of_study=row["year_of_study"],
            lecturer=lecturer,
            room=room,
            day_of_week=row["day_of_week"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            class_group=row["class_group"],
            upload_batch=upload_batch,
        )
        
        return slot

