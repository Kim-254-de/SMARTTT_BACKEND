from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
import re
from django.db import models

from apps.enrollments.models import StudentEnrollment
from apps.enrollments.serializers import StudentEnrollmentSerializer
from apps.timetable.models import AcademicTerm
from apps.curriculum.models import CurriculumUnit
from apps.personalization.services.personalization_cache_service import PersonalizationCacheService


class StudentEnrollmentViewSet(ModelViewSet):
    queryset = StudentEnrollment.objects.select_related("student", "curriculum_unit", "term").all()
    serializer_class = StudentEnrollmentSerializer
    filterset_fields = ["term", "status", "student"]

    @action(detail=False, methods=["post"], url_path="sync")
    def sync_enrollments(self, request):
        """
        Sync student enrollments with registered unit codes from the frontend.
        Expects request body format:
        {
            "unit_codes": ["COSC 435", "COSC 451", ...]
        }
        """
        user = request.user
        student = getattr(user, "student_profile", None)
        if not student:
            return Response(
                {"error": "User does not have a student profile"},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        unit_codes = request.data.get("unit_codes", [])
        if not isinstance(unit_codes, list):
            return Response(
                {"error": "unit_codes must be a list of strings"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Resolve Academic Term
        academic_year = student.academic_year_string
        semester = student.current_semester
        
        term = AcademicTerm.objects.filter(
            academic_year=academic_year, 
            semester=semester
        ).first()
        
        if not term:
            # Fallback to current term
            term = AcademicTerm.objects.filter(is_current=True).first()
            
        if not term:
            # Create a fallback term if none exists to avoid failing completely
            term, _ = AcademicTerm.objects.get_or_create(
                academic_year=academic_year,
                semester=semester,
                defaults={
                    "start_date": timezone.now().date(),
                    "end_date": timezone.now().date() + timedelta(days=120),
                    "is_current": True
                }
            )

        # 2. Normalize input unit codes (remove all non-alphanumeric, e.g. "COSC 435" -> "COSC435")
        normalized_inputs = []
        for raw_code in unit_codes:
            if not isinstance(raw_code, str):
                continue
            clean_code = re.sub(r'[^A-Z0-9]', '', raw_code.upper())
            if clean_code:
                normalized_inputs.append((raw_code, clean_code))
                
        # 3. Match normalized codes to existing CurriculumUnit objects
        matched_curriculum_units = []
        for raw, clean in normalized_inputs:
            candidates = CurriculumUnit.objects.select_related("unit", "curriculum").filter(
                models.Q(unit__code__iexact=raw) |
                models.Q(unit__code__iexact=clean) |
                models.Q(unit__code__icontains=clean)
            )
            
            matched_cu = None
            for cand in candidates:
                cand_clean = re.sub(r'[^A-Z0-9]', '', cand.unit.code.upper())
                if cand_clean == clean:
                    matched_cu = cand
                    break
            
            if matched_cu:
                if matched_cu not in matched_curriculum_units:
                    matched_curriculum_units.append(matched_cu)

        # 4. Update student enrollments for this term
        enrolled_cu_ids = [cu.id for cu in matched_curriculum_units]
        
        # Mark non-matching enrollments for this student and term as Dropped
        StudentEnrollment.objects.filter(
            student=student,
            term=term
        ).exclude(
            curriculum_unit_id__in=enrolled_cu_ids
        ).update(status=StudentEnrollment.Status.DROPPED)
        
        # Create or update matching enrollments to ENROLLED
        synced_count = 0
        for cu in matched_curriculum_units:
            enrollment, created = StudentEnrollment.objects.update_or_create(
                student=student,
                curriculum_unit=cu,
                term=term,
                defaults={"status": StudentEnrollment.Status.ENROLLED}
            )
            synced_count += 1

        # Clear Cache for this student/term so they see the fresh personalized timetable immediately
        PersonalizationCacheService.invalidate(str(student.id), term.academic_year, term.semester)

        return Response({
            "message": f"Successfully synchronized {synced_count} units.",
            "synced_units": [cu.unit.code for cu in matched_curriculum_units],
            "term": str(term)
        }, status=status.HTTP_200_OK)
