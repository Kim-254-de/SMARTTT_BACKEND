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
        
        for idx, row in enumerate(rows, 1):
            try:
                # Check for existence before creating
                slot = self._get_or_create_slot(upload_batch, row)
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
        
        if not saved_slots and errors:
            raise DatabaseOperationException(
                f"Failed to save any timetable slots. Errors: {len(errors)}"
            )
        
        return saved_slots, errors
    
    def _get_or_create_slot(
        self,
        upload_batch,
        row: Dict[str, Any]
    ) -> TimetableSlot:
        # Get AcademicTerm
        try:
            term = AcademicTerm.objects.get(
                academic_year=row["academic_year"],
                semester=row["semester"]
            )
        except AcademicTerm.DoesNotExist:
            raise ResourceNotFoundException(
                f"Academic term not found: {row['academic_year']} S{row['semester']}"
            )
        
        # Get or create Department (for program/unit assignment)
        department = Department.objects.filter(code__iexact="COMP").first()
        if not department:
            department, _ = Department.objects.get_or_create(
                code="COMP",
                defaults={"name": "School of Computing"}
            )
            
        # Get or create Program
        program_code = row["program_code"]
        program = Program.objects.filter(code__iexact=program_code).first()
        if not program:
            program = Program.objects.create(
                code=program_code[:20],
                name=f"Program {program_code}"[:100],
                department=department,
                duration_years=4
            )
            
        # Get or create Unit
        unit_code = row["unit_code"]
        unit = Unit.objects.filter(code__iexact=unit_code).first()
        if not unit:
            unit_name = row.get("unit_name") or unit_code
            unit = Unit.objects.create(
                code=unit_code[:20],
                name=unit_name[:100],
                credit_hours=3.0,
                department=department
            )
        
        # Get Room
        try:
            room = Room.objects.get(code=row["room_code"])
        except Room.DoesNotExist:
            raise ResourceNotFoundException(
                f"Room not found: {row['room_code']}"
            )
        
        # Get Lecturer
        try:
            lecturer = Lecturer.objects.select_related("user").get(
                user__university_id=row["lecturer_university_id"]
            )
        except Lecturer.DoesNotExist:
            raise ResourceNotFoundException(
                f"Lecturer not found: {row['lecturer_university_id']}"
            )
        
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

