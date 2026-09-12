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

        raw_years = filtered_slots.values_list('year_of_study', flat=True)
        years = sorted(list(set(y for y in raw_years if y is not None)))

        if year_of_study:
            filtered_slots = filtered_slots.filter(year_of_study=year_of_study)

        # 3. Scoped Groups with Smart Fallback
        raw_groups = list(filtered_slots.values_list('class_group', flat=True))
        cleaned_groups = [g.strip() for g in raw_groups if g and g.strip()]
        
        unique_groups = set(cleaned_groups)

        # Smart check: If 'MAIN' exists alongside fragmented GR_x groups, 
        # check if MAIN is the intended primary stream for non-split courses.
        # If a program relies heavily on MAIN or has a clean unified structure, 
        # we can prioritize MAIN or filter out unwanted external cross-program groups.
        if "MAIN" in unique_groups and len(unique_groups) > 1:
            # Check if non-MAIN groups are just a minority overflow (common units shared with other streams)
            main_count = cleaned_groups.count("MAIN")
            total_count = len(cleaned_groups)
            
            # If MAIN makes up more than 40% or if it's a strict pure course, 
            # you can choose to collapse or surface MAIN prominently. 
            # For courses with no groups, often forcing just ['MAIN'] or filtering out GR_ if MAIN is dominant works:
            if main_count / total_count > 0.3:
                # Keep MAIN and filter out minor cross-stream contamination if needed, 
                # or safely default to letting them choose MAIN.
                groups = ["MAIN"]
            else:
                groups = sorted(list(unique_groups))
        elif not unique_groups:
            groups = ["MAIN"]
        else:
            groups = sorted(list(unique_groups))

        return Response({
            "semester": current_term.semester,
            "academic_year": current_term.academic_year,
            "courses": courses,
            "years": years,
            "groups": groups,
        })
