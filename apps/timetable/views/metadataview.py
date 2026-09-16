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
            return Response({"courses": [], "years": [], "streams": []}, status=200)

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

        raw_years = filtered_slots.values_list('year_of_study', flat=True)
        years = sorted(list(set(y for y in raw_years if y is not None)))

        if year_of_study:
            filtered_slots = filtered_slots.filter(year_of_study=year_of_study)

        # Distinct sub-streams for this program+year, e.g. the "1"/"2" in
        # "BED.MATH/CHEM Y3S1(1)" / "...(2)". Unlike class_group (which
        # varies per shared unit pool within a single stream - see
        # TimetableSlot.stream docstring), stream identifies the single
        # physical row/class a student actually belongs to, so it's what
        # the student needs to pick to disambiguate their whole timetable.
        raw_streams = list(filtered_slots.values_list('stream', flat=True))
        streams = sorted({s.strip() for s in raw_streams if s and s.strip()})

        return Response({
            "semester": current_term.semester,
            "academic_year": current_term.academic_year,
            "courses": courses,
            "years": years,
            # "streams" is empty when this program+year has only one class
            # (no disambiguation needed) - the frontend should skip the
            # picker in that case rather than showing an empty dropdown.
            "streams": streams,
            # The frontend saves this (not the raw course id it already
            # holds) back to ProfileView.patch as program_id, so student
            # preferences link to the exact Program row the master
            # timetable upload created - not a name-based get_or_create
            # that would silently create a disconnected duplicate. Since
            # "courses" above is already keyed by real Program.id, this is
            # just an echo of the selected program_id once one is chosen.
            "resolved_program_id": program_id or None,
        })
