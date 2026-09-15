from collections import defaultdict

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.programs.utils import canonical_program_key


class TimetableMetadataView(APIView):
    """
    Drives the student "Timetable Stream Setup" dropdowns.

    Programs are matched per-upload-batch and can end up duplicated in the
    DB under the same display name (see apps.programs.utils for why) — a
    3rd/4th-year student and a 1st/2nd-year student can end up looking at
    what is really one program split across two different Program rows.
    So courses here are grouped by their *display name* rather than raw
    Program id: each entry in "courses" can map to several underlying
    Program ids, and "years"/"groups" are the union across all of them —
    a program that is genuinely only offered in, say, years 1-2 still
    only ever shows years [1, 2], because that union is still built
    purely from whatever TimetableSlot rows actually exist.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        current_term = AcademicTerm.objects.filter(is_current=True).first()
        if not current_term:
            return Response({"courses": [], "years": [], "groups": []}, status=200)

        slots = TimetableSlot.objects.filter(term=current_term).select_related('program')

        # ── 1. Group programs that look the same, regardless of which
        #        underlying (possibly duplicated) Program row they came from ──
        program_groups: dict = defaultdict(lambda: {"name": None, "program_ids": set()})
        for slot in slots:
            if not slot.program_id:
                continue
            key = canonical_program_key(slot.program.name)
            group = program_groups[key]
            group["program_ids"].add(slot.program_id)
            # Prefer the most descriptive (longest) spelling as the display name
            if not group["name"] or len(slot.program.name) > len(group["name"]):
                group["name"] = slot.program.name

        courses = [
            {"id": key, "name": group["name"]}
            for key, group in sorted(program_groups.items(), key=lambda kv: kv[1]["name"])
        ]

        selected_key = request.query_params.get('program_id')
        year_of_study = request.query_params.get('year_of_study')

        # Resolve the selected course to the *set* of underlying Program ids
        # it represents. Accept a raw Program id too, for older clients that
        # haven't picked up the grouped-key response yet.
        selected_program_ids = set()
        if selected_key:
            if selected_key in program_groups:
                selected_program_ids = program_groups[selected_key]["program_ids"]
            else:
                selected_program_ids = {selected_key}

        filtered_slots = slots
        if selected_program_ids:
            filtered_slots = filtered_slots.filter(program_id__in=selected_program_ids)

        raw_years = filtered_slots.values_list('year_of_study', flat=True)
        years = sorted(set(y for y in raw_years if y is not None))

        if year_of_study:
            try:
                year_of_study = int(year_of_study)
            except (TypeError, ValueError):
                year_of_study = None
        if year_of_study:
            filtered_slots = filtered_slots.filter(year_of_study=year_of_study)

        # ── 3. Scoped Groups with Smart Fallback ──────────────────────────
        raw_groups = list(filtered_slots.values_list('class_group', flat=True))
        cleaned_groups = [g.strip() for g in raw_groups if g and g.strip()]
        unique_groups = set(cleaned_groups)

        if "MAIN" in unique_groups and len(unique_groups) > 1:
            main_count = cleaned_groups.count("MAIN")
            total_count = len(cleaned_groups)
            if main_count / total_count > 0.3:
                groups = ["MAIN"]
            else:
                groups = sorted(unique_groups)
        elif not unique_groups:
            groups = ["MAIN"]
        else:
            groups = sorted(unique_groups)

        response = {
            "semester": current_term.semester,
            "academic_year": current_term.academic_year,
            "courses": courses,
            "years": years,
            "groups": groups,
        }

        # ── Resolve the concrete Program row to actually save on the student.
        #    A program split across duplicate rows means the "right" row
        #    depends on which one has slots for the year the student picked —
        #    pick whichever candidate has the most matching slots for that
        #    year (ties broken by lowest id, for stability). ──
        if selected_program_ids and year_of_study:
            counts = defaultdict(int)
            qs = slots.filter(program_id__in=selected_program_ids).values_list('program_id', 'year_of_study')
            for pid, y in qs:
                if y == year_of_study:
                    counts[pid] += 1
            if counts:
                best_id = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                response["resolved_program_id"] = str(best_id)

        return Response(response)
