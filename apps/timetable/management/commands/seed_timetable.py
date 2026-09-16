from django.core.management.base import BaseCommand
from apps.timetable.services.pdf_timetable_parser import parse_pdf, to_timetable_slot_dicts
from apps.uploads.services.timetable_mapping_service import TimetableMappingService
from apps.timetable.models import TimetableSession

class Command(BaseCommand):
    help = "Parses the master timetable PDF and seeds sessions into the database."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to the master timetable PDF file")
        parser.add_argument("--academic-year", type=str, default="2026/2027", help="Academic year (e.g., 2026/2027)")

    def handle(self, *args, **options):
        file_path = options["file_path"]
        academic_year = options["academic_year"]

        self.stdout.write(f"Parsing timetable from {file_path}...")
        try:
            parse_result = parse_pdf(file_path)
            slot_dicts = to_timetable_slot_dicts(parse_result, academic_year=academic_year)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to parse PDF: {e}"))
            return

        self.stdout.write(f"Extracted {len(slot_dicts)} raw slots. Mapping and saving to database...")
        
        created_count = 0
        for data in slot_dicts:
            mapping = TimetableMappingService.build_mapping(data)
            unit = mapping.get("unit")
            time_slot = mapping.get("time_slot")
            program = mapping.get("program")
            room = mapping.get("room")

            if not unit or not time_slot:
                continue

            TimetableSession.objects.get_or_create(
                unit=unit,
                time_slot=time_slot,
                day_of_week=data["day_of_week"],
                academic_year=data["academic_year"],
                semester=data["semester"],
                study_year=data["year_of_study"],
                program=program,
                room=room,
                student_group=data["class_group"],
            )
            created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {created_count} timetable sessions."))
