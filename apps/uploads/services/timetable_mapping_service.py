from __future__ import annotations

from django.db.models import Q

from apps.departments.models import Department
from apps.programs.models import Program
from apps.units.models import Unit
from apps.lecturers.models import Lecturer
from apps.rooms.models import Room
from apps.timetable.models import TimeSlot
from apps.uploads.utils import build_student_group, clean_text


class TimetableMappingService:
    @staticmethod
    def resolve_department(row: dict) -> Department | None:
        value = clean_text(row.get("department"))
        if not value:
            return None
        return Department.objects.filter(Q(code__iexact=value) | Q(name__iexact=value)).first()

    @staticmethod
    def resolve_program(row: dict, department: Department | None) -> Program | None:
        value = clean_text(row.get("program"))
        if not value:
            return None
        queryset = Program.objects.filter(Q(code__iexact=value) | Q(name__iexact=value))
        if department:
            queryset = queryset.filter(department=department)
        return queryset.first()

    @staticmethod
    def resolve_unit(row: dict, program: Program | None) -> Unit | None:
        value = clean_text(row.get("unit_code"))
        if not value:
            return None
        queryset = Unit.objects.filter(code__iexact=value)
        if program:
            dept_queryset = queryset.filter(department=program.department)
            if dept_queryset.exists():
                return dept_queryset.first()
        return queryset.first()

    @staticmethod
    def resolve_lecturer(row: dict, department: Department | None) -> Lecturer | None:
        value = clean_text(row.get("lecturer"))
        if not value:
            return None
        queryset = Lecturer.objects.select_related("user", "department").filter(
            Q(user__university_id__iexact=value)
            | Q(user__username__iexact=value)
            | Q(user__first_name__iexact=value)
            | Q(user__last_name__iexact=value)
        )
        if " " in value:
            first_name, last_name = value.split(" ", 1)
            queryset = queryset | Lecturer.objects.select_related("user", "department").filter(
                Q(user__first_name__iexact=first_name) & Q(user__last_name__iexact=last_name)
            )
        if department:
            queryset = queryset.filter(department=department)
        return queryset.distinct().first()

    @staticmethod
    def resolve_room(row: dict) -> Room | None:
        value = clean_text(row.get("room"))
        if not value:
            return None
        return Room.objects.filter(code__iexact=value).first()

    @staticmethod
    def resolve_time_slot(row: dict) -> TimeSlot | None:
        start_time = row.get("start_time")
        end_time = row.get("end_time")
        if not start_time or not end_time:
            return None
        slot = TimeSlot.objects.filter(start_time=start_time, end_time=end_time).first()
        if slot:
            return slot
        duration_minutes = int((end_time.hour * 60 + end_time.minute) - (start_time.hour * 60 + start_time.minute))
        return TimeSlot.objects.create(
            start_time=start_time,
            end_time=end_time,
            slot_name=f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}",
            duration_minutes=duration_minutes,
        )

    @staticmethod
    def build_mapping(row: dict) -> dict:
        department = TimetableMappingService.resolve_department(row)
        program = TimetableMappingService.resolve_program(row, department)
        if not department and program:
            department = program.department
            
        unit = TimetableMappingService.resolve_unit(row, program)
        lecturer = TimetableMappingService.resolve_lecturer(row, department)
        room = TimetableMappingService.resolve_room(row)
        time_slot = TimetableMappingService.resolve_time_slot(row)
        return {
            "department": department,
            "program": program,
            "unit": unit,
            "lecturer": lecturer,
            "room": room,
            "time_slot": time_slot,
            "student_group": clean_text(row.get("student_group")) or build_student_group(row),
        }