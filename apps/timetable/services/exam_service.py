"""
Who sits which exam where, and who invigilates.

A student sits a paper when one of its seatings lists their class row:
their programme (by code, any of its duplicate Program rows), year of study,
study semester when given, and stream when given. A class row split over
rooms is cut by registration number: by the range sent with the seating, or
else by sorting the class row's students by registration number and giving
each part, in order, as many as it seats. Every student gets one room.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from apps.courses.models import StudentUnit
from apps.programs.models import Program
from apps.programs.utils.program_key import canonical_program_key
from apps.students.models import Student
from apps.timetable.models import AcademicTerm, ExamPaper, ExamPublication, ExamSeating


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def current_term() -> AcademicTerm | None:
    return AcademicTerm.objects.filter(is_current=True).first()


def latest_publication(term: AcademicTerm | None) -> ExamPublication | None:
    if term is None:
        return None
    return ExamPublication.objects.filter(term=term).order_by("-version").first()


def _program_codes(student: Student) -> set[str]:
    """The student's programme code, and its duplicates' (same canonical name)."""
    program = getattr(student, "program", None)
    if program is None:
        return set()
    key = canonical_program_key(program.name)
    codes = {compact(program.code)}
    codes.update(compact(p.code) for p in Program.objects.only("code", "name") if canonical_program_key(p.name) == key)
    return codes


def row_matches(row: dict, student: Student, codes: set[str] | None = None) -> bool:
    codes = codes if codes is not None else _program_codes(student)
    if compact(row.get("program", "")) not in codes:
        return False
    if int(row.get("year_of_study") or 0) != int(student.current_study_year or 0):
        return False
    semester = row.get("study_semester")
    if semester and int(semester) != int(student.current_semester or 0):
        return False
    stream = (row.get("stream") or "").strip()
    return not stream or stream == (student.timetable_group or "").strip()


def _row_key(row: dict) -> tuple:
    return (compact(row.get("program", "")), int(row.get("year_of_study") or 0), row.get("study_semester"), (row.get("stream") or "").strip())


def students_of_row(row: dict) -> list[Student]:
    """The class row's active students, by registration number."""
    candidates = Student.objects.select_related("program", "user").filter(
        is_active=True, current_study_year=row.get("year_of_study") or 0
    )
    wanted = compact(row.get("program", ""))
    out = []
    for s in candidates:
        if s.program is None:
            continue
        codes = {compact(s.program.code)}
        if wanted not in codes:
            codes = _program_codes(s)
        if row_matches(row, s, codes):
            out.append(s)
    return sorted(out, key=lambda s: s.registration_number)


def seat_for(student: Student, paper: ExamPaper, codes: set[str] | None = None) -> ExamSeating | None:
    """The student's room for the paper, or None when they don't sit it."""
    codes = codes if codes is not None else _program_codes(student)
    mine = [s for s in paper.seatings.all() if any(row_matches(r, student, codes) for r in s.class_rows)]
    if len(mine) <= 1:
        return mine[0] if mine else None
    reg = student.registration_number
    ranged = [s for s in mine if s.reg_from and s.reg_to]
    for s in ranged:
        if s.reg_from <= reg <= s.reg_to:
            return s
    # Split by count: the class row's students in registration-number order, part by part.
    parts = sorted(mine, key=lambda s: s.part)
    row = next(r for r in parts[0].class_rows if row_matches(r, student, codes))
    roster = [s.registration_number for s in students_of_row(row)]
    position = roster.index(reg) if reg in roster else len(roster)
    taken = 0
    for s in parts:
        taken += s.students
        if position < taken:
            return s
    return parts[-1]


def reg_ranges(paper: ExamPaper) -> dict[str, tuple[str, str]]:
    """For a class row split by count: each seating's first and last registration number (for display)."""
    by_row: dict[tuple, list[ExamSeating]] = defaultdict(list)
    for s in paper.seatings.all():
        if s.parts > 1 and not (s.reg_from and s.reg_to):
            for r in s.class_rows:
                by_row[_row_key(r)].append(s)
    out: dict[str, tuple[str, str]] = {}
    for seatings in by_row.values():
        seatings.sort(key=lambda s: s.part)
        roster = [st.registration_number for st in students_of_row(seatings[0].class_rows[0])]
        start = 0
        for s in seatings:
            chunk = roster[start : start + s.students]
            if chunk:
                out[str(s.pk)] = (chunk[0], chunk[-1])
            start += s.students
    return out


def _times(paper: ExamPaper) -> dict:
    return {
        "key": paper.key,
        "codes": paper.codes,
        "unit_codes": paper.unit_codes,
        "title": paper.title,
        "date": paper.date.isoformat(),
        "start_time": paper.start_time.strftime("%H:%M"),
        "end_time": paper.end_time.strftime("%H:%M"),
    }


ODEL_ENROLLMENT = {Student.EnrollmentType.PART_TIME, Student.EnrollmentType.DISTANCE_LEARNING}


def synced_unit_codes(student: Student, term: AcademicTerm) -> dict[str, str]:
    """The units the student synced this term, compacted code -> code as synced."""
    out: dict[str, str] = {}
    for su in StudentUnit.objects.select_related("unit").filter(user=student.user, term=term):
        out.setdefault(compact(su.unit.code), su.unit.code)
    return out


def _theirs(candidates: list[tuple[ExamPaper, ExamSeating | None]], student: Student) -> list:
    """Of one unit's papers (regular and ODEL twins), the ones the student sits: seated first, else by enrollment."""
    if len(candidates) < 2:
        return candidates
    seated = [c for c in candidates if c[1] is not None]
    if seated:
        return seated
    sitting = ExamPaper.Sitting.ODEL if student.enrollment_type in ODEL_ENROLLMENT else ExamPaper.Sitting.REGULAR
    return [c for c in candidates if c[0].sitting == sitting] or candidates


def student_exams(student: Student, publication: ExamPublication) -> list[dict]:
    """
    The student's papers, each with their own room.

    Only papers of units the student synced this term count ("BITE 131/COSC
    130" shows for one who synced COSC 130). A paper whose seating doesn't
    list the student's class row still shows, with no room and
    `room_confirmed` false, so the app says to check the notice board.
    """
    synced = synced_unit_codes(student, publication.term)
    if not synced:
        return []
    codes = _program_codes(student)
    by_unit: dict[str, list[tuple[ExamPaper, ExamSeating | None]]] = defaultdict(list)
    for paper in publication.papers.prefetch_related("seatings__room"):
        keys = {compact(c) for c in paper.unit_codes} & synced.keys()
        if not keys:
            continue
        entry = (paper, seat_for(student, paper, codes))
        for key in keys:
            by_unit[key].append(entry)
    mine: dict[str, tuple[ExamPaper, ExamSeating | None]] = {}
    for candidates in by_unit.values():
        for paper, seat in _theirs(candidates, student):
            mine[str(paper.pk)] = (paper, seat)
    out = []
    for paper, seat in mine.values():
        out.append(
            {
                **_times(paper),
                "units": [synced[k] for k in (compact(c) for c in paper.unit_codes) if k in synced],
                "sitting": paper.sitting,
                "room": seat.room.code if seat else None,
                "building": seat.room.building if seat else None,
                "room_confirmed": seat is not None,
            }
        )
    return sorted(out, key=lambda p: (p["date"], p["start_time"]))


def student_practicals(student: Student, publication: ExamPublication) -> list[dict]:
    """The practicals of units the student synced this term."""
    synced = synced_unit_codes(student, publication.term)
    return [
        {
            "unit_codes": p.unit_codes,
            "title": p.title,
            "date": p.date.isoformat(),
            "start_time": p.start_time.strftime("%H:%M"),
            "end_time": p.end_time.strftime("%H:%M"),
        }
        for p in publication.practicals.all()
        if any(compact(c) in synced for c in p.unit_codes)
    ]


@dataclass
class Duty:
    paper: ExamPaper
    role: str
    room: str
    rooms: list[str]


def lecturer_duties(staff_number: str, publication: ExamPublication) -> dict:
    """Papers the lecturer examines, and their invigilation duties (main collects every room's scripts)."""
    staff = (staff_number or "").strip().upper()
    examiner, duties = [], []
    for paper in publication.papers.prefetch_related("seatings__room"):
        if staff and paper.examiner_staff_number == staff:
            examiner.append(_times(paper))
        seatings = list(paper.seatings.all())
        rooms = sorted({s.room.code for s in seatings})
        mine = {(s.room.code, s.role) for s in seatings if staff and s.invigilator_staff_number == staff}
        for room, role in sorted(mine):
            duty = {**_times(paper), "room": room, "role": role, "students": sum(s.students for s in seatings if s.room.code == room)}
            if role == ExamSeating.Role.MAIN:
                duty["collect_from"] = [r for r in rooms if r != room]
            duties.append(duty)
    key = lambda p: (p["date"], p["start_time"])  # noqa: E731
    return {"examiner": sorted(examiner, key=key), "duties": sorted(duties, key=key)}


def students_of_paper(paper: ExamPaper) -> list[Student]:
    """Everyone who sits the paper (any room)."""
    out: dict[str, Student] = {}
    for s in paper.seatings.all():
        for r in s.class_rows:
            for st in students_of_row(r):
                out[str(st.pk)] = st
    return list(out.values())
