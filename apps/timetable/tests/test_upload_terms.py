"""A master timetable upload lands in one term; the repair moves one that was split by cohort."""

from datetime import date, time
from io import StringIO
from types import SimpleNamespace

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.departments.models import Department
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.timetable.services.pdf_timetable_parser import to_timetable_slot_dicts
from apps.units.models import Unit


def parsed(*labels):
    slots = [
        SimpleNamespace(cohort_label=label, group="MAIN", day="MON", start_time="08:00", end_time="09:00", hour_label="08-09",
                        unit_code_raw="COSC 100", venue="LH1", page=1)
        for label in labels
    ]
    return SimpleNamespace(slots=slots)


class UploadTermTests(TestCase):
    def test_a_y_s2_class_stays_in_the_term_of_the_file(self):
        rows = to_timetable_slot_dicts(parsed("BCOM Y4S2", "BCOM Y2S1"), "2026/2027", term_semester=1)
        self.assertEqual([(r["semester"], r["study_semester"], r["year_of_study"]) for r in rows], [(1, 2, 4), (1, 1, 2)])


class RepairTests(TestCase):
    def setUp(self):
        dept = Department.objects.create(name="Business", code="BS")
        self.program = Program.objects.create(department=dept, code="BCOM", name="BCom")
        self.unit = Unit.objects.create(code="BCOM 401", name="X", credit_hours=3, department=dept)
        self.room = Room.objects.create(code="LH1", name="LH1", building="M", capacity=50)
        self.current = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18), is_current=True
        )
        self.split = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=2, start_date=date(2026, 9, 7), end_date=date(2027, 1, 5)
        )

    def slot(self, term, day="mon", key=""):
        return TimetableSlot.objects.create(
            term=term, unit=self.unit, program=self.program, year_of_study=4, room=self.room, day_of_week=day,
            start_time=time(8), end_time=time(9), generator_key=key,
        )

    def run_command(self, *args):
        out = StringIO()
        call_command("repair_upload_terms", *args, stdout=out)
        return out.getvalue()

    def test_reports_without_changing_anything(self):
        moved = self.slot(self.split)
        text = self.run_command()
        self.assertIn("uploaded slots: 1", text)
        self.assertIn("Nothing changed", text)
        moved.refresh_from_db()
        self.assertEqual(moved.term, self.split)

    def test_moves_uploaded_slots_only_and_records_the_semester(self):
        moved = self.slot(self.split)
        published = self.slot(self.split, day="tue", key="K|BCOMY4S2")
        own = self.slot(self.current, day="wed")
        twin = self.slot(self.split, day="wed")  # the current term already has it
        self.run_command("--from-term", str(self.split.pk), "--apply")
        for s in (moved, published, own, twin):
            s.refresh_from_db()
        self.assertEqual((moved.term, moved.study_semester), (self.current, 2))
        self.assertEqual(published.term, self.split)
        self.assertEqual(twin.term, self.split)
        self.assertEqual(own.study_semester, 1)

    def test_apply_needs_named_terms(self):
        with self.assertRaises(CommandError):
            self.run_command("--apply")
        with self.assertRaises(CommandError):
            self.run_command("--from-term", str(self.current.pk), "--apply")
