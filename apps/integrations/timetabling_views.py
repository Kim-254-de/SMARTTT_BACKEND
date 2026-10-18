"""
Endpoints for the two timetabling systems, under /api/v1/integrations/:

  allocator/...  Timetable Allocator, X-API-Key = ALLOCATOR_API_KEY
  generator/...  Timetable Generator, X-API-Key = GENERATOR_API_KEY

Sign-in (`authenticate/`, `identity/`) and `terms/` are the same for both;
each system reaches them with its own key. Everything else belongs to one.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.departments.models import Department
from apps.lecturers.models import Lecturer
from apps.timetable.models import AcademicTerm, TimetablePublication

from . import allocator, generator
from .attendance_push import notify_attendance_of_changes
from .permissions import HasAllocatorApiKey, HasGeneratorApiKey
from .timetabling_identity import authenticate_staff, find_identity


def _int_param(request, name: str) -> tuple[int | None, Response | None]:
    raw = (request.query_params.get(name) or "").strip()
    if not raw:
        return None, None
    try:
        return int(raw), None
    except ValueError:
        return None, Response({"detail": f"{name} must be a number."}, status=400)


def _term_or_error(request) -> tuple[AcademicTerm | None, Response | None]:
    term_id = (request.query_params.get("term") or "").strip() or None
    term = allocator.resolve_term(term_id)
    if term is None:
        detail = "No such term." if term_id else "No current term is set."
        return None, Response({"detail": detail}, status=404)
    return term, None


class _TimetablingView(APIView):
    authentication_classes: list = []


# ---------------------------------------------------------------------------
# Shared by both systems
# ---------------------------------------------------------------------------


class _AuthenticateView(_TimetablingView):
    """
    POST {"identifier": "STF/0001" | "name@uni.ac.ke", "password": "..."}

    Wrong credentials are a 200 with {"authenticated": false}, not a 401, so
    the caller can never mistake them for its own key being refused (403).

    200 -> {"authenticated": false}
    200 -> {"authenticated": true,
            "account": {"id", "role", "university_id", "email", "full_name", "is_active"},
            "timetabling_office": bool,
            "departments": [{"id", "code", "name", "faculty", "role": "cod"|"admin"|"editor"}]}
    """

    def post(self, request):
        identifier = str(request.data.get("identifier") or "").strip()
        password = request.data.get("password")
        if not identifier or not isinstance(password, str) or not password:
            return Response({"detail": "identifier and password are required."}, status=400)
        identity = authenticate_staff(identifier, password)
        if identity is None:
            return Response({"authenticated": False})
        return Response({"authenticated": True, **identity})


class _IdentityView(_TimetablingView):
    """
    GET ?account_id=<uuid> -> the same identity as authenticate/, without a
    password, for refreshing a sign-in. 404 when the account is gone or inactive.
    """

    def get(self, request):
        account_id = (request.query_params.get("account_id") or "").strip()
        if not account_id:
            return Response({"detail": "account_id query param is required."}, status=400)
        identity = find_identity(account_id)
        if identity is None:
            return Response({"detail": "No active account with this id."}, status=404)
        return Response(identity)


class _TermsView(_TimetablingView):
    """GET -> {"terms": [{"id", "academic_year", "semester", "start_date", "end_date", "is_current"}]}"""

    def get(self, request):
        return Response({"terms": [allocator.term_dict(t) for t in AcademicTerm.objects.all()]})


class AllocatorAuthenticateView(_AuthenticateView):
    permission_classes = [HasAllocatorApiKey]


class AllocatorIdentityView(_IdentityView):
    permission_classes = [HasAllocatorApiKey]


class AllocatorTermsView(_TermsView):
    permission_classes = [HasAllocatorApiKey]


class GeneratorAuthenticateView(_AuthenticateView):
    permission_classes = [HasGeneratorApiKey]


class GeneratorIdentityView(_IdentityView):
    permission_classes = [HasGeneratorApiKey]


class GeneratorTermsView(_TermsView):
    permission_classes = [HasGeneratorApiKey]


# ---------------------------------------------------------------------------
# Timetable Allocator
# ---------------------------------------------------------------------------


class AllocatorDepartmentsView(_TimetablingView):
    """
    GET -> {"departments": [{"id", "code", "name", "faculty", "cod": {"id", "full_name"} | null}]}

    Every active department, for the Director's view of allocation progress.
    """

    permission_classes = [HasAllocatorApiKey]

    def get(self, request):
        departments = (
            Department.objects.filter(status="active")
            .select_related("faculty", "head_of_department")
            .order_by("faculty__name", "name")
        )
        return Response({"departments": [
            {
                "id": d.id,
                "code": d.code,
                "name": d.name,
                "faculty": d.faculty.name if d.faculty_id else None,
                "cod": (
                    {"id": str(d.head_of_department_id), "full_name": d.head_of_department.get_full_name().strip()}
                    if d.head_of_department_id else None
                ),
            }
            for d in departments
        ]})


class AllocatorSectionsView(_TimetablingView):
    """
    GET ?department=<id>[&term=<uuid>]   (term defaults to the current one)

    The published classes whose unit the department owns - including those it
    teaches to other departments' students - one per section (unit + group):

    200 -> {"term": {...}, "department_id": 7, "sections": [{
              "key": "412-GRA", "code": "COSC 103 GR A", "group": "GR A" | null,
              "unit": {"id", "code", "name", "credit_hours", "department_id"},
              "class_rows": [{"program_id", "program_code", "program_name",
                              "year_of_study", "study_semester", "stream"}],
              "meetings": [{"day_of_week": "TUE", "start_time": "10:00", "end_time": "12:00",
                            "room": {"id", "code", "capacity"}, "session_key"}],
              "weekly_hours": 2.0, "registered_students": 148,
              "lecturer": {...} | null, "lecturer_conflict": false,
              "lecturer_name_text": "",       # from an older allocation document, no account linked
              "session_keys": ["COSC103-GRA-1"]}]}
    """

    permission_classes = [HasAllocatorApiKey]

    def get(self, request):
        department_id, error = _int_param(request, "department")
        if error:
            return error
        if department_id is None:
            return Response({"detail": "department query param is required."}, status=400)
        if not Department.objects.filter(pk=department_id).exists():
            return Response({"detail": "No such department."}, status=404)
        term, error = _term_or_error(request)
        if error:
            return error
        return Response({
            "term": allocator.term_dict(term),
            "department_id": department_id,
            "sections": allocator.department_sections(term, department_id),
        })


class AllocatorSectionDetailView(_TimetablingView):
    """GET sections/<key>/[?term=] -> one section, as in sections/. 404 when it isn't in the term."""

    permission_classes = [HasAllocatorApiKey]

    def get(self, request, key: str):
        term, error = _term_or_error(request)
        if error:
            return error
        section = allocator.find_section(term, key)
        if section is None:
            return Response({"detail": "No such section in this term."}, status=404)
        return Response({"term": allocator.term_dict(term), "section": section})


class AllocatorSectionLecturerView(_TimetablingView):
    """
    PATCH sections/<key>/lecturer/[?term=]
    {"lecturer_id": "<uuid>" | null, "expected_lecturer_id": "<uuid>" | null}

    Sets the lecturer on every slot of the section, or clears it with null.
    `expected_lecturer_id` is optional: when sent, the change is refused (409
    `stale`) unless that is still the section's lecturer, so two people
    editing one class can't silently overwrite each other.

    The clash (H11) and weekly-hours (H12) checks run here under a lock on the
    lecturer; the Allocator's own checks are only for fast feedback.

    200 -> {"term": {...}, "section": {...}, "changed": bool, "previous_lecturer_ids": [...]}
    400 -> {"code": "unknown_lecturer", "detail"}
    404 -> {"code": "not_found", "detail"}
    409 -> {"code": "lecturer_clash" | "max_hours" | "stale", "detail", ...evidence}
    """

    permission_classes = [HasAllocatorApiKey]

    def patch(self, request, key: str):
        if "lecturer_id" not in request.data:
            return Response({"detail": "lecturer_id is required (null clears the lecturer)."}, status=400)
        lecturer_id = request.data.get("lecturer_id")
        if lecturer_id is not None and not isinstance(lecturer_id, str):
            return Response({"detail": "lecturer_id must be a string or null."}, status=400)
        expected = request.data["expected_lecturer_id"] if "expected_lecturer_id" in request.data else ...
        if expected is not ... and expected is not None and not isinstance(expected, str):
            return Response({"detail": "expected_lecturer_id must be a string or null."}, status=400)

        term, error = _term_or_error(request)
        if error:
            return error
        try:
            result = allocator.set_section_lecturer(term, key, lecturer_id or None, expected)
        except allocator.AllocationRefused as refused:
            return Response({"code": refused.code, "detail": refused.message, **refused.details},
                            status=refused.status)

        if result.changed:
            _push_lecturer_change(result)
        return Response({
            "term": allocator.term_dict(term),
            "section": result.section,
            "changed": result.changed,
            "previous_lecturer_ids": result.previous_lecturer_ids,
        })


def _push_lecturer_change(result: allocator.AllocationResult) -> None:
    """Both the new and the previous lecturer re-sync in attendance."""
    code = result.section["code"]
    changes = [(None, code)]
    lecturer = result.section.get("lecturer")
    if lecturer:
        changes.append((lecturer.get("staff_number"), code))
    for previous in Lecturer.objects.select_related("user").filter(pk__in=result.previous_lecturer_ids):
        changes.append((previous.user.university_id, code))
    notify_attendance_of_changes(changes)


class AllocatorLecturersView(_TimetablingView):
    """
    GET [?department=<id>][&term=<uuid>]

    Active lecturers (of one department, or all), with employment type and
    max_weekly_teaching_hours. With `term`, each also has `meetings` (what
    they already teach that term, across all departments) and `weekly_hours`,
    so the Allocator can tell who is free at a slot in one call.
    """

    permission_classes = [HasAllocatorApiKey]

    def get(self, request):
        department_id, error = _int_param(request, "department")
        if error:
            return error
        term = None
        if (request.query_params.get("term") or "").strip():
            term, error = _term_or_error(request)
            if error:
                return error
        return Response({
            "term": allocator.term_dict(term) if term else None,
            "lecturers": allocator.department_lecturers(term, department_id),
        })


class AllocatorLecturerSessionsView(_TimetablingView):
    """
    GET lecturers/<id>/sessions/[?term=]

    200 -> {"term": {...}, "lecturer": {...}, "weekly_hours": 8.0,
            "meetings": [{"section_key", "code", "unit_department_id", "day_of_week",
                          "start_time", "end_time", "room", "linked"}]}
    `linked` is false for classes matched only by the name on an older
    allocation document (no account linked yet).
    """

    permission_classes = [HasAllocatorApiKey]

    def get(self, request, lecturer_id):
        term, error = _term_or_error(request)
        if error:
            return error
        lecturer = Lecturer.objects.select_related("user", "department").filter(pk=lecturer_id).first()
        if lecturer is None:
            return Response({"detail": "No such lecturer."}, status=404)
        meetings = allocator.lecturer_meetings(term, lecturer)
        return Response({
            "term": allocator.term_dict(term),
            "lecturer": allocator.lecturer_dict(lecturer),
            "weekly_hours": allocator.weekly_hours(meetings),
            "meetings": meetings,
        })


# ---------------------------------------------------------------------------
# Timetable Generator
# ---------------------------------------------------------------------------


class GeneratorSnapshotView(_TimetablingView):
    """
    GET ?term=<uuid>   (defaults to the current term)

    Read-only master data for solving the term: rooms, departments (with FT/PT
    lecturer counts), lecturers, programmes, units, curricula, class sizes,
    registrations, the term's current timetable with its lecturers
    (`published.sessions`, for repair re-solves) and `warnings` about missing
    or placeholder data. See generator.build_snapshot.
    """

    permission_classes = [HasGeneratorApiKey]

    def get(self, request):
        term, error = _term_or_error(request)
        if error:
            return error
        return Response(generator.build_snapshot(term))


class GeneratorPublishView(_TimetablingView):
    """
    POST {"term_id", "version": 4, "based_on_version": 3 | null, "published_by": "<id> <name>",
          "replace_unpublished": false,
          "sessions": [{"key": "COSC103-GRA-1", "unit_id": 412, "group_label": "GR A" | null,
                        "class_rows": [{"program_id", "year_of_study", "study_semester", "stream"}],
                        "room_id": "<uuid>", "day_of_week": "TUE",
                        "start_time": "10:00", "end_time": "12:00"}]}

    201 -> the publication (new)          200 -> the publication (same version re-sent)
    400 -> malformed request              404 -> no such term
    409 -> {"code": "stale_base" | "version_taken" | "unpublished_slots" | "lecturer_clash", ...}
    422 -> {"code": "invalid", "errors": [...]}: the version breaks a rule; nothing written
    """

    permission_classes = [HasGeneratorApiKey]

    def post(self, request):
        if not isinstance(request.data, dict):
            return Response({"detail": "Expected a JSON object."}, status=400)
        try:
            result = generator.publish_version(dict(request.data))
        except generator.PublishRefused as refused:
            return Response({"code": refused.code, "detail": refused.message, **refused.details},
                            status=refused.status)
        if result.created:
            notify_attendance_of_changes(result.attendance_changes)
        return Response(generator.publication_dict(result.publication), status=201 if result.created else 200)


class GeneratorPublicationView(_TimetablingView):
    """GET publish/<version>/?term=<uuid> -> the publication, 404 when that version doesn't exist."""

    permission_classes = [HasGeneratorApiKey]

    def get(self, request, version: int):
        term, error = _term_or_error(request)
        if error:
            return error
        publication = TimetablePublication.objects.filter(term=term, version=version).first()
        if publication is None:
            return Response({"detail": "No such version for this term."}, status=404)
        return Response(generator.publication_dict(publication))
