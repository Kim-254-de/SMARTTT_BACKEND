"""
The Timetable Generator's exam endpoints (X-API-Key = GENERATOR_API_KEY):
publishing the exam timetable (exam_publish.py) and switching the term to
exams and back (exam_mode.py).
"""

import uuid

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.timetable.models import AcademicTerm

from . import exam_mode
from .exam_publish import ExamPublishRefused, ExamPublishSerializer, publish
from .permissions import HasGeneratorApiKey


class _GeneratorView(APIView):
    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]


class ExamPublishView(_GeneratorView):
    """POST generator/exam-publish/: 201 published, 200 the same version again; refusals write nothing."""

    def post(self, request):
        serializer = ExamPublishSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"code": "invalid_payload", "detail": "The exam timetable sent is not valid.", "errors": serializer.errors},
                status=400,
            )
        try:
            status, body = publish(serializer.validated_data)
        except ExamPublishRefused as refused:
            return Response(refused.body, status=refused.status)
        return Response(body, status=status)


def _term_param(request) -> uuid.UUID | None:
    try:
        return uuid.UUID((request.query_params.get("term") or "").strip())
    except ValueError:
        return None


class ExamModeView(_GeneratorView):
    """GET generator/exam-mode/?term=: the term's mode, and its switch and close."""

    def get(self, request):
        term = AcademicTerm.objects.filter(pk=_term_param(request)).first() if _term_param(request) else None
        if term is None:
            return Response({"code": "unknown_term", "detail": "SMARTTT has no such term."}, status=404)
        return Response(exam_mode.state(term))


class _ModeActionView(_GeneratorView):
    act = staticmethod(exam_mode.switch)
    cancel = staticmethod(exam_mode.cancel_switch)

    def post(self, request):
        serializer = exam_mode.ExamModeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"code": "invalid_payload", "detail": "Give term_id and at, or now.", "errors": serializer.errors}, status=400)
        data = serializer.validated_data
        try:
            return Response(self.act(data["term_id"], data.get("at"), data.get("now", False), data.get("by", "")))
        except exam_mode.ExamModeRefused as refused:
            return Response(refused.body, status=refused.status)

    def delete(self, request):
        term = _term_param(request)
        if term is None:
            return Response({"code": "invalid_payload", "detail": "Give ?term=<term id>."}, status=400)
        try:
            return Response(self.cancel(term, request.query_params.get("by", "")))
        except exam_mode.ExamModeRefused as refused:
            return Response(refused.body, status=refused.status)


class ExamSwitchView(_ModeActionView):
    """POST generator/exam-switch/ {term_id, at | now: true, by}; DELETE ?term= cancels a scheduled switch."""


class ExamCloseView(_ModeActionView):
    """POST generator/exam-close/ {term_id, at | now: true, by}; DELETE ?term= cancels a scheduled close."""

    act = staticmethod(exam_mode.close)
    cancel = staticmethod(exam_mode.cancel_close)
