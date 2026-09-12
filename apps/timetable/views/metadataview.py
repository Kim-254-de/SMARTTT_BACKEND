from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.programs.models import Program

class TimetableMetadataView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        current_term = AcademicTerm.objects.filter(is_current=True).first()
        if not current_term:
            return Response({"courses": [], "years": [], "groups": []}, status=200)

        slots = TimetableSlot.objects.filter(term=current_term).select_related('program')

        # 1. Distinct Courses
        program_map = {}
        for slot in slots:
            if slot.program_id:
                program_map[str(slot.program_id)] = slot.program.name

        courses = [{"id": pid, "name": name} for pid, name in sorted(program_map.items(), key=lambda x: x[1])]

        program_id = request.query_params.get('program_id')
        year_of_study = request.query_params.get('year_of_study')
        semester = request.query_params.get('semester', current_term.semester)

        filtered_slots = slots
        if program_id:
            filtered_slots = filtered_slots.filter(program_id=program_id)
        if year_of_study:
            filtered_slots = filtered_slots.filter(year_of_study=year_of_study)

        # 2. Absolute Unique Years using Python set
        raw_years = filtered_slots.values_list('year_of_study', flat=True)
        years = sorted(list(set(y for y in raw_years if y is not None)))

        # 3. Absolute Unique Groups using Python set & stripping whitespace
        raw_groups = filtered_slots.values_list('class_group', flat=True)
        groups = sorted(list(set(g.strip() for g in raw_groups if g and g.strip())))

        return Response({
            "semester": current_term.semester,
            "academic_year": current_term.academic_year,
            "courses": courses,
            "years": years,
            "groups": groups,
        })
