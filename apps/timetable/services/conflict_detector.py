"""
Conflict detection service for timetable sessions.

Detects and reports various types of conflicts:
- Room conflicts (double-booking)
- Lecturer conflicts (teaching multiple sessions simultaneously)
- Program conflicts (two sessions for same program at same time)
"""

from typing import List, Dict, Any
from django.db import transaction

from apps.timetable.models import TimetableConflict, TimetableSlot
from apps.timetable.utils import ConflictDetectionException, TimetableLogger


class TimetableConflictDetectionService:
    """
    Service for detecting timetable conflicts.
    
    Detects:
    - Room conflicts: same room booked at overlapping times
    - Lecturer conflicts: lecturer scheduled for multiple sessions at same time
    - Program conflicts: same program sessions overlap
    """
    
    def __init__(self):
        """Initialize conflict detector with logging."""
        self.logger = TimetableLogger()
    
    @transaction.atomic
    def detect(self, slots: List[TimetableSlot]) -> List[TimetableConflict]:
        """
        Detect conflicts in timetable slots.
        
        Args:
            slots: List of TimetableSlot instances to check
            
        Returns:
            List of detected TimetableConflict instances
        """
        conflicts = []
        conflict_details = {}
        
        for i, current_slot in enumerate(slots):
            for candidate_slot in slots[i + 1:]:
                # Conflicts only occur in same term and day
                if current_slot.term_id != candidate_slot.term_id:
                    continue
                if current_slot.day_of_week != candidate_slot.day_of_week:
                    continue
                
                # Check if times overlap
                if not self._check_time_overlap(current_slot, candidate_slot):
                    continue
                
                # Determine conflict type(s)
                conflict_types = self._determine_conflict_types(current_slot, candidate_slot)
                
                for conflict_type in conflict_types:
                    # Create conflict record
                    conflict = TimetableConflict.objects.create(
                        conflict_type=conflict_type,
                        term=current_slot.term,
                        slot_a=current_slot,
                        slot_b=candidate_slot,
                        details=self._generate_conflict_details(
                            current_slot,
                            candidate_slot,
                            conflict_type
                        ),
                    )
                    conflicts.append(conflict)
                    
                    # Log conflict detection
                    self.logger.log_conflict_detected(
                        upload_batch_id=current_slot.upload_batch_id or "unknown",
                        conflict_type=conflict_type,
                        slot_a_id=current_slot.id,
                        slot_b_id=candidate_slot.id,
                    )
                    
                    # Track for statistics
                    if conflict_type not in conflict_details:
                        conflict_details[conflict_type] = 0
                    conflict_details[conflict_type] += 1
        
        return conflicts
    
    @staticmethod
    def _check_time_overlap(slot_a: TimetableSlot, slot_b: TimetableSlot) -> bool:
        """
        Check if two time slots overlap.
        
        Args:
            slot_a: First timetable slot
            slot_b: Second timetable slot
            
        Returns:
            True if slots overlap, False otherwise
        """
        # Slots overlap if: slot_a starts before slot_b ends AND slot_b starts before slot_a ends
        return slot_a.start_time < slot_b.end_time and slot_b.start_time < slot_a.end_time
    
    @staticmethod
    def _determine_conflict_types(slot_a: TimetableSlot, slot_b: TimetableSlot) -> List[str]:
        """
        Determine what type(s) of conflict exist between two slots.
        """
        conflicts = []
        
        # Room conflict: same room
        if slot_a.room_id == slot_b.room_id:
            conflicts.append(TimetableConflict.Type.ROOM)
        
        # Lecturer conflict: same lecturer
        if slot_a.lecturer_id == slot_b.lecturer_id:
            conflicts.append(TimetableConflict.Type.LECTURER)
        
        # Program conflict: same program
        if slot_a.program_id and slot_b.program_id:
            if slot_a.program_id == slot_b.program_id:
                conflicts.append(TimetableConflict.Type.PROGRAM)
        
        return conflicts if conflicts else [TimetableConflict.Type.ROOM]  # Default to ROOM
    
    @staticmethod
    def _generate_conflict_details(
        slot_a: TimetableSlot,
        slot_b: TimetableSlot,
        conflict_type: str
    ) -> Dict[str, Any]:
        """
        Generate detailed conflict information.
        
        Args:
            slot_a: First timetable slot
            slot_b: Second timetable slot
            conflict_type: Type of conflict
            
        Returns:
            Dictionary with conflict details
        """
        return {
            "conflict_type": conflict_type,
            "slot_a": {
                "id": str(slot_a.id),
                "unit": str(slot_a.unit.code),
                "lecturer": slot_a.lecturer.user.university_id,
                "room": slot_a.room.code,
                "time": f"{slot_a.start_time} - {slot_a.end_time}",
            },
            "slot_b": {
                "id": str(slot_b.id),
                "unit": str(slot_b.unit.code),
                "lecturer": slot_b.lecturer.user.university_id,
                "room": slot_b.room.code,
                "time": f"{slot_b.start_time} - {slot_b.end_time}",
            },
            "overlap_time": f"{max(slot_a.start_time, slot_b.start_time)} - "
                           f"{min(slot_a.end_time, slot_b.end_time)}",
        }
    
    def detect_batch_conflicts(
        self,
        term_id: str,
        day_of_week: str = None
    ) -> Dict[str, Any]:
        """
        Detect all conflicts for a specific term and optional day.
        
        Useful for generating conflict reports.
        
        Args:
            term_id: Academic term ID
            day_of_week: Optional specific day to check
            
        Returns:
            Dictionary with conflict statistics and details
        """
        query = TimetableConflict.objects.filter(term_id=term_id).select_related(
            "slot_a",
            "slot_b",
            "slot_a__lecturer",
            "slot_b__lecturer",
            "slot_a__room",
            "slot_b__room",
        )
        
        if day_of_week:
            query = query.filter(slot_a__day_of_week=day_of_week)
        
        conflicts = query.all()
        
        # Build statistics
        conflict_by_type = {}
        for conflict in conflicts:
            if conflict.conflict_type not in conflict_by_type:
                conflict_by_type[conflict.conflict_type] = 0
            conflict_by_type[conflict.conflict_type] += 1
        
        return {
            "total": conflicts.count(),
            "by_type": conflict_by_type,
            "conflicts": conflicts,
        }

