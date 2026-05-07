from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.curriculum.models import CurriculumUnit
from apps.lecturers.models import Lecturer
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetableSlot


class TimetablePersistenceService:
    @transaction.atomic
    def save_rows(self, upload_batch, rows):
        saved_slots = []
        for row in rows:
            term = AcademicTerm.objects.get(
                academic_year=row["academic_year"], semester=row["semester"]
            )
            curriculum_unit = CurriculumUnit.objects.select_related("curriculum", "unit").get(
                curriculum__program__code=row["program_code"],
                unit__code=row["unit_code"],
                year_of_study=row["year_of_study"],
                semester=row["semester"],
            )
            room = Room.objects.get(code=row["room_code"])
            lecturer = Lecturer.objects.select_related("user").get(
                user__university_id=row["lecturer_university_id"]
            )

            slot = TimetableSlot.objects.create(
                term=term,
                curriculum_unit=curriculum_unit,
                lecturer=lecturer,
                room=room,
                day_of_week=row["day_of_week"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                class_group=row["class_group"],
                upload_batch=upload_batch,
            )
            saved_slots.append(slot)

        if not saved_slots:
            raise ValidationError("No timetable rows were saved.")

        return saved_slots
