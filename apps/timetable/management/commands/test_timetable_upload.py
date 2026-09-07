import os
import sys
from django.core.management.base import BaseCommand, CommandError
from apps.timetable.services.pdf_timetable_parser import parse_pdf, to_timetable_slot_dicts
from apps.timetable.services.persistence import TimetablePersistenceService
from apps.timetable.models import TimetableUploadBatch, AcademicTerm, TimetableSlot


class Command(BaseCommand):
    help = "Test and benchmark timetable PDF parsing and database persistence directly via CLI."

    def add_arguments(self, parser):
        parser.add_argument("pdf_path", type=str, help="Absolute or relative path to the timetable PDF")
        parser.add_argument("--year", type=str, default="2026/2027", help="Academic year (default: 2026/2027)")
        parser.add_argument("--dry-run", action="store_true", help="Parse and validate without saving to database")
        parser.add_argument("--limit", type=int, default=None, help="Process only the first N rows for quick sanity check")

    def handle(self, *args, **options):
        pdf_path = options["pdf_path"]
        academic_year = options["year"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        if not os.path.exists(pdf_path):
            raise CommandError(f"File not found: {pdf_path}")

        self.stdout.write(self.style.NOTICE(f"\n[1/4] Starting PDF extraction on: {pdf_path}"))
        
        # 1. Parse raw PDF
        try:
            parse_result = parse_pdf(pdf_path)
            self.stdout.write(self.style.SUCCESS(f"  Extracted {len(parse_result.slots)} raw slot candidates."))
            if parse_result.warnings:
                self.stdout.write(self.style.WARNING(f"  Encountered {len(parse_result.warnings)} warnings during table extraction."))
        except Exception as e:
            raise CommandError(f"PDF extraction failed: {str(e)}")

        # 2. Normalize to schema dictionary
        self.stdout.write(self.style.NOTICE(f"[2/4] Normalizing and grouping rows for {academic_year}..."))
        slot_dicts = to_timetable_slot_dicts(parse_result, academic_year=academic_year)
        total_normalized = len(slot_dicts)
        self.stdout.write(self.style.SUCCESS(f"  Produced {total_normalized} valid slot dictionaries."))

        if limit and limit < total_normalized:
            slot_dicts = slot_dicts[:limit]
            self.stdout.write(self.style.WARNING(f"  Limiting insertion to first {limit} rows as requested."))

        # Display sample output for verification
        if slot_dicts:
            sample = slot_dicts[0]
            self.stdout.write(self.style.HTTP_INFO("\nSample Normalized Slot [Row 1]:"))
            for k, v in sample.items():
                self.stdout.write(f"  - {k:22}: {v}")
            self.stdout.write("")

        # 3. Dry-Run Evaluation
        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry-run complete. No database records created.\n"))
            return

        # 4. Database Persistence
        self.stdout.write(self.style.NOTICE("[3/4] Running persistence service into PostgreSQL..."))
        
        # Create an audit batch
        batch = TimetableUploadBatch.objects.create(
            file_name=os.path.basename(pdf_path),
            status="processing"
        )

        persistence_service = TimetablePersistenceService()
        try:
            saved_slots, errors = persistence_service.save_rows(upload_batch=batch, rows=slot_dicts)
            
            batch.rows_received = len(slot_dicts)
            batch.rows_saved = len(saved_slots)
            batch.rows_failed = len(errors)
            batch.status = "processed" if not errors else "partial"
            batch.save()

            self.stdout.write(self.style.SUCCESS(f"\n[4/4] Persistence Complete!"))
            self.stdout.write(f"  - Saved Slots : {len(saved_slots)}")
            self.stdout.write(f"  - Errors      : {len(errors)}")

            if errors:
                self.stdout.write(self.style.ERROR("\nSample Errors Encountered:"))
                for err in errors[:5]:
                    self.stdout.write(f"  Row {err.get('row_number')}: {err.get('error')}")

            # Verify Day distribution
            days_count = {}
            for s in saved_slots:
                days_count[s.day_of_week] = days_count.get(s.day_of_week, 0) + 1
            
            self.stdout.write(self.style.HTTP_INFO("\nDay of Week Distribution in Database:"))
            for day, count in sorted(days_count.items()):
                self.stdout.write(f"  - {day:10}: {count} slots")

        except Exception as e:
            batch.status = "failed"
            batch.save()
            raise CommandError(f"Database persistence crashed: {str(e)}")
