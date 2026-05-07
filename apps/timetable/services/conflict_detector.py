from apps.timetable.models import TimetableConflict


class TimetableConflictDetectionService:
    def detect(self, slots):
        conflicts = []
        for i, current in enumerate(slots):
            for candidate in slots[i + 1 :]:
                if current.term_id != candidate.term_id:
                    continue
                if current.day_of_week != candidate.day_of_week:
                    continue
                if not (current.start_time < candidate.end_time and candidate.start_time < current.end_time):
                    continue

                conflict_type = None
                if current.room_id == candidate.room_id:
                    conflict_type = TimetableConflict.Type.ROOM
                elif current.lecturer_id == candidate.lecturer_id:
                    conflict_type = TimetableConflict.Type.LECTURER
                elif current.curriculum_unit.curriculum.program_id == candidate.curriculum_unit.curriculum.program_id:
                    conflict_type = TimetableConflict.Type.PROGRAM

                if conflict_type:
                    conflict = TimetableConflict.objects.create(
                        conflict_type=conflict_type,
                        term=current.term,
                        slot_a=current,
                        slot_b=candidate,
                        details={
                            "current": str(current.id),
                            "candidate": str(candidate.id),
                        },
                    )
                    conflicts.append(conflict)

        return conflicts
