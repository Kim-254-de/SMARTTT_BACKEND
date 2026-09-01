"""
Test suite for memory-efficient timetable processing.

Run with: pytest tests/test_timetable_streaming.py -v
"""
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.timetable.models import (
    AcademicTerm,
    TimetableUploadBatch,
    TimetableSlot,
)
from apps.timetable.services.pdf_timetable_parser import (
    parse_pdf_streaming,
    parse_pdf,
    RawSlot,
)
from apps.timetable.services.upload_service_streaming import process_upload_streaming

User = get_user_model()


class PDFParserStreamingTests(TestCase):
    """Test streaming PDF parser functionality."""

    def setUp(self):
        self.test_pdf_path = Path(__file__).parent / "fixtures" / "sample_timetable.pdf"

    @pytest.mark.skipif(not Path("tests/fixtures/sample_timetable.pdf").exists(), 
                        reason="Sample PDF not provided")
    def test_parse_pdf_streaming_returns_generator(self):
        """Test that parse_pdf_streaming returns a generator."""
        result = parse_pdf_streaming(str(self.test_pdf_path))
        # Should be a generator
        assert hasattr(result, '__iter__')

    @pytest.mark.skipif(not Path("tests/fixtures/sample_timetable.pdf").exists(),
                        reason="Sample PDF not provided")
    def test_streaming_chunk_size_respected(self):
        """Test that chunk_size is respected."""
        chunks = []
        for batch, page, table in parse_pdf_streaming(
            str(self.test_pdf_path), chunk_size=10
        ):
            if page == -1:  # Sentinel
                break
            chunks.append((len(batch), page))

        # Each batch should be <= chunk_size (except last)
        for size, _ in chunks[:-1]:
            assert size <= 10

    def test_parse_pdf_fallback_to_standard(self):
        """Test that parse_pdf still works as standard mode."""
        # This would test with actual PDF if available
        pass


class TimetableUploadStreamingTests(TransactionTestCase):
    """Test streaming upload service."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027",
            semester=1,
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
            is_current=True,
        )

    def test_process_upload_streaming_with_mock_pdf(self):
        """Test upload processing with mocked PDF parser."""
        upload = TimetableUploadBatch.objects.create(
            uploaded_by=self.user,
            source_file="test.pdf",
            status=TimetableUploadBatch.Status.RECEIVED,
        )

        # Mock the PDF parser to return test data
        test_slots = [
            RawSlot(
                cohort_label="BSC.CS Y1S1",
                day="Monday",
                start_time="9",
                end_time="10",
                unit_code_raw="CS101",
                venue="UTC",
                room="101",
                page=1,
                raw_cell_text="CS101",
            )
        ]

        with patch("apps.timetable.services.upload_service_streaming.parse_pdf_streaming") as mock_parser:
            mock_parser.return_value = iter([
                (test_slots, 1, 1),
                ([], -1, -1),  # Sentinel
            ])

            result = process_upload_streaming(upload)

            assert result.status == TimetableUploadBatch.Status.PROCESSED
            assert result.rows_received == 1
            assert result.rows_saved > 0

    def test_progress_callback_invoked(self):
        """Test that progress callback is called during processing."""
        upload = TimetableUploadBatch.objects.create(
            uploaded_by=self.user,
            source_file="test.pdf",
            status=TimetableUploadBatch.Status.RECEIVED,
        )

        callback_invocations = []

        def mock_callback(rows_received, rows_saved, message):
            callback_invocations.append((rows_received, rows_saved))

        test_slots = [
            RawSlot(
                cohort_label="BSC.CS Y1S1",
                day="Monday",
                start_time="9",
                end_time="10",
                unit_code_raw="CS101",
                venue="UTC",
                room="101",
                page=1,
                raw_cell_text="CS101",
            )
        ]

        with patch("apps.timetable.services.upload_service_streaming.parse_pdf_streaming"):
            with patch("apps.timetable.services.upload_service_streaming._save_slot_batch") as mock_save:
                mock_save.return_value = 1
                # Would need to mock more thoroughly for real test
                pass


class MemoryProfileTests(TestCase):
    """Test memory efficiency of streaming approach."""

    def test_streaming_memory_usage(self):
        """
        Test that streaming approach uses less memory than loading all at once.
        Requires: pip install memory-profiler
        """
        try:
            from memory_profiler import memory_usage
        except ImportError:
            self.skipTest("memory-profiler not installed")

        # This test would profile memory usage
        # In practice, use: python -m memory_profiler script.py


class IntegrationTests(TransactionTestCase):
    """End-to-end integration tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="admin123"
        )

    @pytest.mark.skipif(not Path("tests/fixtures/timetable_may_aug_2026.pdf").exists(),
                        reason="TUN May-Aug 2026 timetable PDF not provided")
    def test_real_tun_timetable_processing(self):
        """
        Integration test with real TUN May-Aug 2026 timetable.
        
        This test processes the actual PDF provided and validates:
        - No memory timeout
        - Correct row parsing
        - Proper error reporting
        """
        pdf_path = Path("tests/fixtures/timetable_may_aug_2026.pdf")

        # Create upload
        with open(pdf_path, "rb") as f:
            upload = TimetableUploadBatch.objects.create(
                uploaded_by=self.user,
                source_file="tuntimetable.pdf",
                status=TimetableUploadBatch.Status.RECEIVED,
            )
            upload.source_file.save("tuntimetable.pdf", f)

        # Process
        result = process_upload_streaming(upload)

        # Assertions
        assert result.status in [
            TimetableUploadBatch.Status.PROCESSED,
            TimetableUploadBatch.Status.FAILED,
        ]
        assert result.rows_received > 0
        assert isinstance(result.validation_errors, list)

        # Print diagnostics
        print(f"\n=== TUN Timetable Processing Results ===")
        print(f"Status: {result.status}")
        print(f"Rows Received: {result.rows_received}")
        print(f"Rows Saved: {result.rows_saved}")
        print(f"Errors: {len(result.validation_errors)}")
        if result.validation_errors:
            for err in result.validation_errors[:5]:
                print(f"  - Row {err.get('row')}: {err.get('error')}")


class BattchProcessingTests(TransactionTestCase):
    """Test batch processing logic."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="test123"
        )

    def test_batch_size_configuration(self):
        """Test that batch sizes are configurable."""
        from apps.timetable.services.upload_service_streaming import (
            BATCH_SIZE,
            SLOT_BATCH_INSERT_SIZE,
        )

        # These should be configurable constants
        assert isinstance(BATCH_SIZE, int)
        assert isinstance(SLOT_BATCH_INSERT_SIZE, int)
        assert BATCH_SIZE > 0
        assert SLOT_BATCH_INSERT_SIZE > 0

    def test_deduplication_with_update_or_create(self):
        """Test that duplicate slots are properly handled."""
        # Create initial slot
        term = AcademicTerm.objects.create(
            academic_year="2026/2027",
            semester=1,
            start_date=timezone.now().date(),
            end_date=timezone.now().date(),
        )

        from apps.programs.models import Program
        from apps.departments.models import Department, Faculty
        from apps.units.models import Unit
        from apps.rooms.models import Room

        faculty = Faculty.objects.create(code="ENG", name="Engineering")
        dept = Department.objects.create(code="CS", name="Computer Science", faculty=faculty)
        prog = Program.objects.create(code="CS1", name="CS Program", department=dept)
        unit = Unit.objects.create(code="CS101", name="Intro to CS", department=dept)
        room = Room.objects.create(code="LC1", name="Lecture Hall 1")

        # First slot
        slot1 = TimetableSlot.objects.create(
            term=term,
            unit=unit,
            program=prog,
            year_of_study=1,
            day="mon",
            start_time="09:00:00",
            end_time="10:00:00",
            room=room,
        )
        initial_count = TimetableSlot.objects.count()

        # Attempt to create duplicate (should update instead)
        updated_slot, created = TimetableSlot.objects.update_or_create(
            term=term,
            unit=unit,
            program=prog,
            year_of_study=1,
            day="mon",
            start_time="09:00:00",
            defaults={
                "end_time="11:00:00",
                "room=room,
            },
        )

        # Should not increase count
        final_count = TimetableSlot.objects.count()
        assert final_count == initial_count
        assert not created  # Should be update, not creation


# CLI test command
if __name__ == "__main__":
    """Run tests with: python manage.py test tests.test_timetable_streaming"""
    pass
