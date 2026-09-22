from django.core.management.base import BaseCommand

from apps.timetable.services.allocation_service import resolve_academic_year, year_slots


class Command(BaseCommand):
    help = (
        "Clears lecturer names written by the old allocation upload (slots with a "
        "lecturer name but no allocation document), so only the per-department "
        "allocation documents decide who teaches each class. Run once, then "
        "re-upload each department's allocation document."
    )

    def add_arguments(self, parser):
        parser.add_argument("--academic-year", type=str, default=None, help="Defaults to the current term's year")
        parser.add_argument("--apply", action="store_true", help="Actually clear; without it only counts are shown")

    def handle(self, *args, **options):
        academic_year = resolve_academic_year(options["academic_year"])
        legacy = year_slots(academic_year).filter(allocation_document__isnull=True).exclude(lecturer_name_text="")
        count = legacy.count()
        if not options["apply"]:
            self.stdout.write(f"{count} slot(s) in {academic_year} carry a legacy lecturer name. Re-run with --apply to clear them.")
            return
        cleared = legacy.update(lecturer_name_text="", lecturer=None)
        self.stdout.write(self.style.SUCCESS(f"Cleared {cleared} legacy lecturer assignment(s) in {academic_year}."))
