from .permissions import (
    IsSuperAdminOrReadOnly,
    IsDepartmentAdminOrSuper,
    IsRegistrarOrSuper,
    CanManageTimetable,
    CanViewTimetable,
    CanManageRooms,
    CanManageTimeSlots,
    IsLecturerOrAdmin,
    IsStudentOrAdmin,
    CanRescheduleTimetableSlot,
)

# Backward compatibility: older modules refer to "own timetable" permission.
CanViewOwnTimetable = CanViewTimetable

__all__ = [
    "IsSuperAdminOrReadOnly",
    "IsDepartmentAdminOrSuper",
    "IsRegistrarOrSuper",
    "CanManageTimetable",
    "CanViewTimetable",
    "CanViewOwnTimetable",
    "CanManageRooms",
    "CanManageTimeSlots",
    "IsLecturerOrAdmin",
    "IsStudentOrAdmin",
    "CanRescheduleTimetableSlot",
]
