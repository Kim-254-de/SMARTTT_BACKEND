"""
A student's exam timetable: the papers and practicals of the units they
synced, from the current term's latest exam version.

  1. The current term and its latest published exam timetable
  2. The student's synced units this term (StudentUnit), as compacted codes
  3. A paper (or practical) is theirs when any of its codes is one of those
     ("BITE 131/COSC 130" shows for a student who synced COSC 130)
  4. A unit with a regular and an ODEL paper (ODEL and part-time students sit
     separate papers): the one seating their class row, else the one of their
     enrollment (part-time and distance learning sit the ODEL papers)
  5. Their room: the paper's seating for their own class row (programme, year
     and stream); when that can't be told, every room of the paper, with
     `room_confirmed` false so the app says to check the notice board
"""
from __future__ import annotations

from apps.courses.models import StudentUnit
from apps.integrations.generator_publish import compact
from apps.programs.models import Program
from apps.students.models import Student
from apps.timetable.models import AcademicTerm, ExamPaper, ExamTimetable

from .services import _program_ids_for_student


def _empty(term, message: str, version=None, published_at=None) -> dict:
    return {
        "term": str(term) if term else None,
        "version": version,
        "published_at": published_at,
        "papers": [],
        "practicals": [],
        "summary": {"paper_count": 0, "practical_count": 0, "message": message},
    }


def _hhmm(value) -> str:
    return value.strftime("%H:%M")


def _own_seats(paper: ExamPaper, student, program_ids: list, program_codes: set[str]) -> list:
    """The seating of the student's own class row: their programme, year and (when split) stream."""
    if student is None or not (program_ids or program_codes):
        return []
    year = getattr(student, "current_study_year", None)
    stream = compact(getattr(student, "timetable_group", None) or "")
    out = []
    for seat in paper.seating.all():
        same_program = (seat.program_id is not None and seat.program_id in program_ids) or (
            seat.program_code and compact(seat.program_code) in program_codes
        )
        if not same_program or seat.year_of_study != year:
            continue
        if seat.stream and compact(seat.stream) != stream:
            continue
        out.append(seat)
    return out


ODEL_ENROLLMENT = {Student.EnrollmentType.PART_TIME, Student.EnrollmentType.DISTANCE_LEARNING}


def _theirs(candidates: list[tuple[ExamPaper, list]], student) -> list[tuple[ExamPaper, list]]:
    """Of a unit's papers (each with the student's own seating in it), the ones the student sits."""
    if len(candidates) < 2:
        return candidates
    seated = [c for c in candidates if c[1]]
    # A class row named by stream ("... (ODEL)") is theirs before one with no stream, which matches anyone.
    by_stream = [c for c in seated if any(seat.stream for seat in c[1])]
    if by_stream or seated:
        return by_stream or seated
    sitting = ExamPaper.Sitting.ODEL if getattr(student, "enrollment_type", None) in ODEL_ENROLLMENT else ExamPaper.Sitting.REGULAR
    return [c for c in candidates if c[0].sitting == sitting] or candidates


def _rooms(seats) -> list[dict]:
    seen, out = set(), []
    for s in seats:
        if s.room_code in seen:
            continue
        seen.add(s.room_code)
        out.append({"room": s.room_code, "class_row": s.class_row, "part": s.part, "parts": s.parts})
    return out


def exams_for_user(user) -> dict:
    term = AcademicTerm.objects.filter(is_current=True).first()
    if term is None:
        return _empty(None, "No current academic term configured.")
    timetable = ExamTimetable.objects.filter(term=term).order_by("-version").first()
    if timetable is None:
        return _empty(term, "The exam timetable for this term hasn't been published yet.")
    version, published_at = timetable.version, timetable.created_at.isoformat()

    synced = list(StudentUnit.objects.select_related("unit").filter(user=user, term=term))
    if not synced:
        return _empty(term, "No synced units found. Use Sync to see your exams.", version, published_at)
    unit_by_key: dict[str, str] = {}
    for su in synced:
        unit_by_key.setdefault(compact(su.unit.code), su.unit.code)

    student = getattr(user, "student_profile", None)
    program_ids = _program_ids_for_student(student) if student else []
    program_codes = {compact(code) for code in Program.objects.filter(pk__in=program_ids).values_list("code", flat=True)}
    program_codes.discard("")

    matched: dict[str, tuple[ExamPaper, list]] = {}
    by_unit: dict[str, list[tuple[ExamPaper, list]]] = {}
    for paper in timetable.papers.prefetch_related("seating"):
        keys = [k for k in paper.code_keys if k in unit_by_key]
        if not keys:
            continue
        entry = (paper, _own_seats(paper, student, program_ids, program_codes))
        for k in keys:
            by_unit.setdefault(k, []).append(entry)
    for candidates in by_unit.values():
        for paper, own in _theirs(candidates, student):
            matched[str(paper.pk)] = (paper, own)

    papers = []
    for paper, own in sorted(matched.values(), key=lambda e: (e[0].date, e[0].start_time, e[0].key)):
        units = [unit_by_key[k] for k in paper.code_keys if k in unit_by_key]
        confirmed = bool(own) and len({s.room_code for s in own}) == 1
        papers.append(
            {
                "codes": paper.codes,
                "units": units,
                "title": paper.title,
                "sitting": paper.sitting,
                "date": paper.date.isoformat(),
                "start_time": _hhmm(paper.start_time),
                "end_time": _hhmm(paper.end_time),
                "rooms": _rooms(own or paper.seating.all()),
                "room_confirmed": confirmed,
            }
        )
    practicals = [
        {
            "codes": pr.codes,
            "units": [unit_by_key[k] for k in pr.code_keys if k in unit_by_key],
            "title": pr.title,
            "department": pr.department,
            "date": pr.date.isoformat(),
            "start_time": _hhmm(pr.start_time),
            "end_time": _hhmm(pr.end_time),
        }
        for pr in timetable.practicals.all()
        if any(k in unit_by_key for k in pr.code_keys)
    ]
    message = "" if papers or practicals else "None of your synced units has an exam in this timetable."
    return {
        "term": str(term),
        "version": version,
        "published_at": published_at,
        "papers": papers,
        "practicals": practicals,
        "summary": {"paper_count": len(papers), "practical_count": len(practicals), "message": message},
    }
