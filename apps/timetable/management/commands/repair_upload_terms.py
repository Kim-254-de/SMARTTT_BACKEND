"""
Uploaded master timetables used to be split by cohort: a "BCOM Y4S2" slot went
into the year's semester 2 term whatever term the file was for, so only part of
the timetable was in the current term.

    python manage.py repair_upload_terms
        Changes nothing. Lists every term: uploaded slots, slots the Generator
        published, and what the repair would move.

    python manage.py repair_upload_terms --from-term <uuid> [--from-term <uuid>] --apply
        Moves those terms' uploaded slots into the current term and records each
        slot's study semester (its old term's). Generator-published slots are
        never moved. A slot the current term already has is left where it was.

Also fills in the study semester of the current term's own uploaded slots.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.timetable.models import AcademicTerm, TimetableSlot


class Command(BaseCommand):
    help = "Reports, and with --apply repairs, uploaded master timetables split across terms."

    def add_arguments(self, parser):
        parser.add_argument("--from-term", action="append", default=[], help="A term to move uploaded slots out of.")
        parser.add_argument("--apply", action="store_true", help="Make the changes. Without it nothing is written.")

    def handle(self, *args, **options):
        current = AcademicTerm.objects.filter(is_current=True).first()
        self.stdout.write(f"Current term: {current or 'none'}")
        for term in AcademicTerm.objects.all():
            slots = TimetableSlot.objects.filter(term=term)
            uploaded = slots.filter(generator_key="").count()
            self.stdout.write(
                f"{term.pk}  {term.academic_year} S{term.semester}"
                f"{'  CURRENT' if term.is_current else ''}  {term.start_date} to {term.end_date}"
                f"  uploaded slots: {uploaded}  Generator slots: {slots.count() - uploaded}"
                f"  units: {slots.values('unit').distinct().count()}"
            )
        if not options["apply"]:
            self.stdout.write("Nothing changed. To move slots: --from-term <id> --apply")
            return
        if current is None:
            raise CommandError("No term is current: set one first.")
        sources = list(AcademicTerm.objects.filter(pk__in=options["from_term"]).exclude(pk=current.pk))
        if len(sources) != len(set(options["from_term"])):
            raise CommandError("--from-term must name existing terms other than the current one.")
        if not sources:
            raise CommandError("Name the terms to move slots out of with --from-term.")
        with transaction.atomic():
            for term in sources:
                moved = kept = 0
                for slot in TimetableSlot.objects.filter(term=term, generator_key=""):
                    taken = TimetableSlot.objects.filter(
                        term=current, program=slot.program, unit=slot.unit, year_of_study=slot.year_of_study,
                        day_of_week=slot.day_of_week, start_time=slot.start_time, end_time=slot.end_time,
                        room=slot.room, class_group=slot.class_group, stream=slot.stream,
                    ).exists()
                    if taken:
                        kept += 1
                        continue
                    slot.study_semester = slot.study_semester or term.semester
                    slot.term = current
                    slot.save(update_fields=["study_semester", "term", "updated_at"])
                    moved += 1
                self.stdout.write(f"{term}: moved {moved}, already in {current}: {kept}")
            filled = TimetableSlot.objects.filter(term=current, generator_key="", study_semester__isnull=True).update(
                study_semester=current.semester
            )
            self.stdout.write(f"{current}: study semester filled on {filled} slots")
