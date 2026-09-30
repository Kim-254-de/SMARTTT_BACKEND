from datetime import date, time

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.departments.models import Department, Faculty
from apps.lecturers.models import Lecturer
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.units.models import Unit

KEY = "test-attendance-key"
URL = reverse("integrations-attendance-student-units")
LECTURER_URL = reverse("integrations-attendance-lecturer-units")


@override_settings(ATTENDANCE_API_KEY=KEY)
class AttendanceStudentUnitsTests(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        self.dept = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.room = Room.objects.create(code="LH1", name="Lecture Hall 1", building="Main", capacity=100)
        self.term = AcademicTerm.objects.create(
            academic_year="2025/2026", semester=1, start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20), is_current=True,
        )
        self.old_term = AcademicTerm.objects.create(
            academic_year="2024/2025", semester=2, start_date=date(2025, 1, 6),
            end_date=date(2025, 4, 30), is_current=False,
        )
        lec_user = User.objects.create_user(
            username="pkamami", password="x", role=User.Role.LECTURER,
            university_id="STF/0001", first_name="Peter", last_name="Kamami",
        )
        self.lecturer = Lecturer.objects.create(user=lec_user, department=self.dept)
        self.student = User.objects.create_user(
            username="amina", password="x", role=User.Role.STUDENT,
            university_id="EBT1/08223/23", first_name="Amina", last_name="Kamau",
        )

    def _unit(self, code, name):
        return Unit.objects.create(code=code, name=name, credit_hours=3, department=self.dept)

    def _slot(self, unit, day="mon", start=(8, 0), end=(10, 0), term=None, **kw):
        return TimetableSlot.objects.create(
            term=term or self.term, unit=unit, room=self.room, day_of_week=day,
            start_time=time(*start), end_time=time(*end), **kw,
        )

    def _register(self, unit, class_group="", term=None, user=None):
        StudentUnit.objects.create(user=user or self.student, unit=unit, term=term or self.term, class_group=class_group)

    def _get(self, key=KEY, **params):
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        return self.client.get(URL, params, **headers)

    def test_requires_the_api_key(self):
        self.assertEqual(self._get(key=None, registration_number="EBT1/08223/23").status_code, 403)
        self.assertEqual(self._get(key="wrong", registration_number="EBT1/08223/23").status_code, 403)

    def test_unknown_or_missing_number(self):
        self.assertEqual(self._get(registration_number="EBT1/99999/23").status_code, 404)
        self.assertEqual(self._get().status_code, 400)

    def test_lists_this_terms_units_with_lecturers_and_slots(self):
        cosc100 = self._unit("COSC 100", "Intro to Computing")
        old = self._unit("COSC 050", "Last term's unit")
        self._slot(cosc100, day="tue", start=(10, 0), end=(12, 0), lecturer=self.lecturer)
        self._slot(cosc100, day="mon", lecturer_name_text="Dr. Jane Otieno")
        self._register(cosc100)
        self._register(old, term=self.old_term)

        res = self._get(registration_number="ebt1/08223/23")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["registration_number"], "EBT1/08223/23")
        self.assertEqual(res.data["term"], {"academic_year": "2025/2026", "semester": 1})
        [unit] = res.data["units"]
        self.assertEqual(unit["code"], "COSC 100")
        self.assertIsNone(unit["group"])
        self.assertFalse(unit["group_required"])
        self.assertEqual(unit["lecturers"], ["Dr. Jane Otieno", "Peter Kamami"])
        self.assertEqual([s["day_of_week"] for s in unit["slots"]], [1, 2])  # Monday first
        self.assertEqual(unit["slots"][0]["room"], "LH1")

    def test_group_student_gets_their_group_section_matching_the_lecturer_side(self):
        cosc103 = self._unit("COSC 103", "Computer Applications")
        self._slot(cosc103, class_group="GR A", lecturer=self.lecturer)
        self._slot(cosc103, day="wed", class_group="GR B", lecturer_name_text="Jane Otieno")
        self._register(cosc103, class_group="GR_A")

        [unit] = self._get(registration_number="EBT1/08223/23").data["units"]
        self.assertEqual((unit["code"], unit["group"]), ("COSC 103 GR A", "GR A"))
        self.assertEqual(unit["lecturers"], ["Peter Kamami"])
        self.assertEqual(len(unit["slots"]), 1)

        # Same section code as the lecturer's roster, so the two systems line up.
        lecturer_units = self.client.get(LECTURER_URL, {"staff_number": "STF/0001"}, HTTP_X_API_KEY=KEY).data["units"]
        self.assertEqual([u["code"] for u in lecturer_units], ["COSC 103 GR A"])
        self.assertIn("EBT1/08223/23", [s["registration_number"] for s in lecturer_units[0]["students"]])

    def test_split_unit_without_a_group_picked_asks_for_one(self):
        cosc103 = self._unit("COSC 103", "Computer Applications")
        self._slot(cosc103, class_group="GR A", lecturer=self.lecturer)
        self._register(cosc103)

        [unit] = self._get(registration_number="EBT1/08223/23").data["units"]
        self.assertEqual(unit["code"], "COSC 103")
        self.assertTrue(unit["group_required"])
        self.assertEqual((unit["lecturers"], unit["slots"]), ([], []))

    def test_unit_with_main_and_group_slots_gives_both_sections(self):
        cosc104 = self._unit("COSC 104", "Programming")
        self._slot(cosc104, lecturer=self.lecturer)
        self._slot(cosc104, day="thu", class_group="GR B", lecturer_name_text="Jane Otieno")
        self._register(cosc104, class_group="GR B")

        codes = [u["code"] for u in self._get(registration_number="EBT1/08223/23").data["units"]]
        self.assertEqual(codes, ["COSC 104", "COSC 104 GR B"])

    def test_unit_not_yet_timetabled_is_still_listed(self):
        self._register(self._unit("COSC 105", "Networks"), class_group="GR A")
        [unit] = self._get(registration_number="EBT1/08223/23").data["units"]
        self.assertEqual((unit["code"], unit["slots"], unit["group_required"]), ("COSC 105", [], False))

    def test_no_current_term(self):
        AcademicTerm.objects.update(is_current=False)
        res = self._get(registration_number="EBT1/08223/23")
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.data["term"], res.data["units"]), (None, []))
