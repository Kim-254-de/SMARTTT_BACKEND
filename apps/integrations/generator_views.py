"""
Endpoints for the Timetable Generator (X-API-Key = GENERATOR_API_KEY): it
publishes each approved timetable here as the term's master timetable
(generator_publish.py).
"""
import uuid

import logging

from django.db import transaction
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.timetable.models import AcademicTerm, TimetablePublication

from .generator_publish import PublishRefused, PublishSerializer, _term, publish
from .permissions import HasGeneratorApiKey

logger = logging.getLogger(__name__)


class GeneratorPublishView(APIView):
    """
    POST /api/v1/integrations/generator/publish/

    201 -> published now; 200 -> this version was already published with the
    same classes (the stored result). 400 a malformed payload; 404 an unknown
    term_id; 409 stale_base | version_taken | unpublished_slots; 422
    invalid_timetable | unknown_department | term_mismatch | term_dates_required.
    Every refusal is {"code", "detail", ...} and writes nothing.
    """

    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]

    def post(self, request):
        serializer = PublishSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"code": "invalid_payload", "detail": "The timetable sent is not valid.", "errors": serializer.errors},
                status=400,
            )
        try:
            status, body = publish(serializer.validated_data)
        except PublishRefused as refused:
            return Response(refused.body, status=refused.status)
        return Response(body, status=status)


class GeneratorPublicationView(APIView):
    """GET /api/v1/integrations/generator/publish/<version>/?term=<term uuid>: what that publish did."""

    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]

    def get(self, request, version: int):
        try:
            term = uuid.UUID((request.query_params.get("term") or "").strip())
        except ValueError:
            term = None
        publication = TimetablePublication.objects.filter(term_id=term, version=version).first() if term else None
        if publication is None:
            return Response({"code": "not_found", "detail": f"SMARTTT has no version {version} of that term."}, status=404)
        return Response(
            {**publication.result, "published_by": publication.published_by, "published_at": publication.created_at}
        )


def _term_dict(term: AcademicTerm) -> dict:
    return {
        "id": str(term.pk),
        "academic_year": term.academic_year,
        "semester": term.semester,
        "start_date": term.start_date.isoformat(),
        "end_date": term.end_date.isoformat(),
        "is_current": term.is_current,
    }


class GeneratorTermsView(APIView):
    """GET generator/terms/: SMARTTT's terms."""

    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]

    def get(self, request):
        return Response({"terms": [_term_dict(t) for t in AcademicTerm.objects.all()]})


class _SetCurrent(serializers.Serializer):
    term_id = serializers.UUIDField(required=False, allow_null=True)
    academic_year = serializers.CharField(max_length=20)
    semester = serializers.IntegerField(min_value=1, max_value=3)
    term_start = serializers.DateField(required=False, allow_null=True)
    term_end = serializers.DateField(required=False, allow_null=True)
    by = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class GeneratorSetCurrentView(APIView):
    """
    POST generator/set-current/: the Director makes a term the current one, as
    an administrator can in SMARTTT. The term is found by id, else by year and
    semester, and created when it needs to be (with its dates). The answer's
    `id` is what the Generator links its term to.
    """

    authentication_classes: list = []
    permission_classes = [HasGeneratorApiKey]

    def post(self, request):
        body = _SetCurrent(data=request.data)
        if not body.is_valid():
            return Response({"code": "invalid_payload", "detail": "The term sent is not valid.", "errors": body.errors}, status=400)
        data = body.validated_data
        try:
            with transaction.atomic():
                term = _term(data)
                AcademicTerm.objects.filter(is_current=True).exclude(pk=term.pk).update(is_current=False)
                if not term.is_current:
                    term.is_current = True
                    term.save(update_fields=["is_current"])
        except PublishRefused as refused:
            return Response(refused.body, status=refused.status)
        logger.info("current term set to %s by %s", term, data["by"] or "the Timetable Generator")
        try:
            from apps.common.services.cache_service import PersonalizationCacheService

            PersonalizationCacheService.clear_all()
        except Exception:
            logger.exception("set-current: could not clear the personal timetable caches")
        return Response(_term_dict(term))
