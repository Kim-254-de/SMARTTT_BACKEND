"""
Endpoints for the Timetable Generator (X-API-Key = GENERATOR_API_KEY): it
publishes each approved timetable here as the term's master timetable
(generator_publish.py).
"""
import uuid

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.timetable.models import TimetablePublication

from .generator_publish import PublishRefused, PublishSerializer, publish
from .permissions import HasGeneratorApiKey


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
