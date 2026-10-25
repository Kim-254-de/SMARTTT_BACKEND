"""
The exam timetable in the app:

    GET /api/v1/exams/my/          a student's papers: date, time, codes, title and their own room
    GET /api/v1/exams/my-duties/   a lecturer's papers (as examiner) and invigilation duties
    GET /api/v1/terms/current/     the current term, with its mode (teaching | exams) and switch time
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.timetable.models import Practical
from apps.timetable.services.exam_service import current_term, latest_publication, lecturer_duties, student_exams


def _term(term) -> dict | None:
    if term is None:
        return None
    return {
        "id": str(term.pk),
        "academic_year": term.academic_year,
        "semester": term.semester,
        "start_date": term.start_date.isoformat(),
        "end_date": term.end_date.isoformat(),
        "is_current": term.is_current,
        "mode": term.mode,
        "exam_switch_at": term.exam_switch_at.isoformat() if term.exam_switch_at else None,
        "switched_at": term.switched_at.isoformat() if term.switched_at else None,
        "exam_closed_at": term.exam_closed_at.isoformat() if term.exam_closed_at else None,
    }


def _practicals(publication) -> list[dict]:
    return [
        {
            "unit_codes": p.unit_codes,
            "title": p.title,
            "date": p.date.isoformat(),
            "start_time": p.start_time.strftime("%H:%M"),
            "end_time": p.end_time.strftime("%H:%M"),
        }
        for p in Practical.objects.filter(publication=publication)
    ]


class CurrentTermView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_term(current_term()))


class MyExamsView(APIView):
    """The signed-in student's exams; before the switch, a preview (`mode` says which)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        term = current_term()
        publication = latest_publication(term)
        student = getattr(request.user, "student_profile", None)
        if student is None:
            return Response({"detail": "Only students have an exam timetable here; lecturers see my-duties."}, status=403)
        if publication is None:
            return Response({"term": _term(term), "version": None, "papers": [], "practicals": []})
        return Response(
            {
                "term": _term(term),
                "version": publication.version,
                "papers": student_exams(student, publication),
                "practicals": _practicals(publication),
            }
        )


class MyExamDutiesView(APIView):
    """The signed-in lecturer's papers as examiner and invigilation duties (main collects every room's scripts)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        term = current_term()
        publication = latest_publication(term)
        if publication is None:
            return Response({"term": _term(term), "version": None, "examiner": [], "duties": []})
        return Response(
            {"term": _term(term), "version": publication.version, **lecturer_duties(request.user.university_id or "", publication)}
        )
