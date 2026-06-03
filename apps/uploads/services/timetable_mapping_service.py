from __future__ import annotations

import re
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
            value = "School of Computing"
        code = re.sub(r'[^A-Z0-9]', '', value.upper())
        if not code:
            code = "DEPT"
        dept = Department.objects.filter(
            Q(code__iexact=value) | Q(name__iexact=value) | Q(code__iexact=code)
        ).first()
        if not dept:
            dept = Department.objects.create(code=code[:20], name=value[:100])
        return dept

    @staticmethod
    def resolve_program(row: dict, department: Department | None) -> Program | None:
        value = clean_text(row.get("program"))
        if not value:
            return None
        if not department:
            department = Department.objects.get_or_create(code="SCHOOLOFCOMPUTING", defaults={"name": "School of Computing"})[0]
            
        code = re.sub(r'[^A-Z0-9]', '', value.upper())
        if not code:
            code = "PROG"
            
        prog = Program.objects.filter(
            Q(code__iexact=value) | Q(name__iexact=value) | Q(code__iexact=code),
            department=department
        ).first()
        
        if not prog:
            prog = Program.objects.create(
                code=code[:20],
                name=value[:100],
                department=department,
                description=f"Bachelor of Science in {value}",
                duration_years=4
            )
        return prog

    @staticmethod
    def resolve_unit(row: dict, program: Program | None) -> Unit | None:
        value = clean_text(row.get("unit_code"))
        if not value:
            return None
        clean_code = re.sub(r'[^A-Z0-9]', '', value.upper())
        queryset = Unit.objects.filter(Q(code__iexact=value) | Q(code__iexact=clean_code))
        if program:
            dept_queryset = queryset.filter(department=program.department)
            if dept_queryset.exists():
                unit = dept_queryset.first()
            else:
                unit = queryset.first()
        else:
            unit = queryset.first()
            
        if not unit:
            name = row.get("unit_name") or value
            dept = program.department if program else None
            if not dept:
                dept = Department.objects.get_or_create(code="SCHOOLOFCOMPUTING", defaults={"name": "School of Computing"})[0]
            unit = Unit.objects.create(
                code=value[:20],
                name=name[:100],
                credit_hours=3,
                department=dept,
                description=f"Course Unit {value}"
            )
        
        # Auto-create Curriculum and CurriculumUnit for the program if provided
        if program and unit:
            from apps.curriculum.models import Curriculum, CurriculumUnit
            curriculum, _ = Curriculum.objects.get_or_create(
                program=program,
                department=program.department,
                academic_year=row.get("academic_year") or "2025/2026",
                study_year=row.get("study_year") or 1,
                semester=row.get("semester") or 1
            )
            CurriculumUnit.objects.get_or_create(
                unit=unit,
                curriculum=curriculum,
                defaults={
                    "is_core": True,
                    "is_elective": False,
                    "display_order": 1
                }
            )
        return unit

    @staticmethod
    def resolve_lecturer(row: dict, department: Department | None) -> Lecturer | None:
        value = clean_text(row.get("lecturer"))
        if not value:
            value = "Staff"
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
        lect = queryset.distinct().first()
        if not lect:
            from apps.accounts.models import User
            username = re.sub(r'[^a-zA-Z0-9]', '', value.lower())
            if not username:
                username = "lecturer_user"
            idx = 1
            base_username = username
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{idx}"
                idx += 1
            user = User.objects.create_user(
                username=username,
                email=f"{username}@example.com",
                first_name=value[:30],
                last_name="Lecturer",
                university_id=f"LEC_{username.upper()[:15]}",
                role="lecturer"
            )
            dept = department
            if not dept:
                dept = Department.objects.get_or_create(code="SCHOOLOFCOMPUTING", defaults={"name": "School of Computing"})[0]
            lect = Lecturer.objects.create(user=user, department=dept)
        return lect

    @staticmethod
    def resolve_room(row: dict) -> Room | None:
        value = clean_text(row.get("room"))
        if not value:
            value = "TBA"
        clean_code = re.sub(r'[^A-Z0-9]', '', value.upper())
        room = Room.objects.filter(Q(code__iexact=value) | Q(code__iexact=clean_code)).first()
        if not room:
            room = Room.objects.create(
                code=value[:20],
                name=f"Room {value}"[:100],
                capacity=100
            )
        return room

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