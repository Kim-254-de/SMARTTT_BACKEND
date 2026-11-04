"""Synced students per unit and class row, for Attendance's exam papers; the admin's rooms, for the Generator."""

from datetime import date, time

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.departments.models import Department
from apps.lecturers.models import Lecturer
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.students.models import Student
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.units.models import Unit

ATT_KEY = "test-attendance-key"
GEN_KEY = "test-generator-key"
ENROLMENT = reverse("integrations-attendance-unit-enrolment")
ROOMS = reverse("integrations-generator-rooms")


@override_settings(ATTENDANCE_API_KEY=ATT_KEY, GENERATOR_API_KEY=GEN_KEY)
class UnitEnrolmentTests(APITestCase):
    def setUp(self):
        self.cs = Department.objects.create(name="Computer Science", code="CS")
        self.bsc = Program.objects.create(department=self.cs, code="BSC.CS", name="BSc Computer Science")
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18),
            is_current=True,
        )
        self.old = AcademicTerm.objects.create(
            academic_year="2025/2026", semester=2, start_date=date(2026, 1, 6), end_date=date(2026, 4, 30),
        )
        self.math = Unit.objects.create(code="MATH 241", name="Linear Algebra", credit_hours=3, department=self.cs)
        self.cosc = Unit.objects.create(code="COSC 130", name="Programming", credit_hours=3, department=self.cs)
        self.n = 0

    def student(self, year=2, stream="", enrollment=Student.EnrollmentType.FULL_TIME):
        self.n += 1
        reg = f"CS/{self.n:04d}/25"
        user = User.objects.create_user(
            username=f"s{self.n}", email=f"s{self.n}@x.ke", password="x", role=User.Role.STUDENT, university_id=reg
        )
        Student.objects.create(
            user=user, registration_number=reg, program=self.bsc, department=self.cs, admission_year=2025,
            first_name="S", last_name=reg, email=f"s{self.n}@x.ke", current_study_year=year, current_semester=1,
            timetable_group=stream, enrollment_type=enrollment,
        )
        return user

    def sync(self, user, unit, term=None):
        StudentUnit.objects.create(user=user, unit=unit, term=term or self.term)

    def post(self, codes, key=ATT_KEY):
        return self.client.post(ENROLMENT, {"codes": codes}, format="json", HTTP_X_API_KEY=key)

    def test_needs_attendances_key(self):
        self.assertEqual(self.post(["MATH 241"], key="wrong").status_code, 403)
        self.assertEqual(self.client.get(ROOMS, HTTP_X_API_KEY=ATT_KEY).status_code, 403)

    def test_counts_synced_students_by_class_row_and_sitting(self):
        for _ in range(3):
            self.sync(self.student(), self.math)
        self.sync(self.student(stream="B"), self.math)
        self.sync(self.student(year=3, enrollment=Student.EnrollmentType.PART_TIME), self.math)
        self.sync(self.student(), self.math, term=self.old)  # another term: not counted
        body = self.post(["Math 241"]).data  # written as the department wrote it
        unit = body["units"]["Math 241"]
        self.assertEqual((unit["name"], unit["students"]), ("Linear Algebra", 5))
        rows = [(r["program"], r["year_of_study"], r["stream"], r["sitting"], r["students"]) for r in unit["rows"]]
        self.assertEqual(
            rows, [("BSC.CS", 3, "", "odel", 1), ("BSC.CS", 2, "", "regular", 3), ("BSC.CS", 2, "B", "regular", 1)]
        )
        self.assertEqual(body["term"]["academic_year"], "2026/2027")

    def test_a_known_unit_nobody_synced_and_an_unknown_code(self):
        body = self.post(["COSC 130", "XYZ 999", ""]).data
        self.assertEqual((body["units"]["COSC 130"]["students"], body["units"]["COSC 130"]["rows"]), (0, []))
        self.assertEqual(body["unknown"], ["XYZ 999"])

    def test_lecturers_on_the_timetable(self):
        user = User.objects.create_user(
            username="jane", password="x", role=User.Role.LECTURER, university_id="stf/0001",
            first_name="Jane", last_name="L",
        )
        lecturer = Lecturer.objects.create(user=user, department=self.cs)
        room = Room.objects.create(code="LH1", name="LH1", building="Main", capacity=100)
        for day in ("mon", "wed"):
            TimetableSlot.objects.create(
                term=self.term, unit=self.cosc, room=room, day_of_week=day, start_time=time(8), end_time=time(10),
                lecturer=lecturer,
            )
        unit = self.post(["COSC 130"]).data["units"]["COSC 130"]
        self.assertEqual(unit["lecturers"], [{"staff_number": "STF/0001", "name": "Jane L"}])

    def slot(self, unit, program=None, year=2, stream="", day="mon", study_semester=None, term=None):
        room, _ = Room.objects.get_or_create(code="LH1", defaults={"name": "LH1", "building": "Main", "capacity": 100})
        TimetableSlot.objects.create(
            term=term or self.term, unit=unit, program=program or self.bsc, year_of_study=year, stream=stream,
            study_semester=study_semester, room=room, day_of_week=day, start_time=time(8), end_time=time(10),
        )

    @staticmethod
    def classes(unit):
        return [(r["program"], r["year_of_study"], r["study_semester"], r["stream"], r["students"]) for r in unit["rows"]]

    def test_the_master_timetable_names_the_classes_when_nobody_synced(self):
        bed = Program.objects.create(department=self.cs, code="BED.SCI", name="BEd Science")
        self.slot(self.math, study_semester=2)
        self.slot(self.math, day="wed", study_semester=2)  # another meeting of one class: still one row
        self.slot(self.math, program=bed, year=3, stream="1", study_semester=1)
        self.slot(self.math, program=bed, year=3, stream="2", study_semester=1)
        self.slot(self.cosc, program=bed, year=1, term=self.old)  # another term: not this one's class
        body = self.post(["MATH 241", "COSC 130"]).data
        self.assertEqual(body["unknown"], [])
        self.assertEqual(body["units"]["COSC 130"]["rows"], [])
        unit = body["units"]["MATH 241"]
        self.assertEqual(unit["students"], 0)
        self.assertEqual(
            self.classes(unit), [("BED.SCI", 3, 1, "1", 0), ("BED.SCI", 3, 1, "2", 0), ("BSC.CS", 2, 2, "", 0)]
        )
        self.assertEqual({r["sitting"] for r in unit["rows"]}, {"regular"})

    def test_a_synced_class_on_the_timetable_is_one_row_with_its_students(self):
        self.slot(self.math, study_semester=1)
        self.sync(self.student(), self.math)
        self.sync(self.student(), self.math)
        unit = self.post(["MATH 241"]).data["units"]["MATH 241"]
        self.assertEqual(self.classes(unit), [("BSC.CS", 2, 1, "", 2)])

    def test_synced_students_of_a_class_not_on_the_timetable_still_count(self):
        self.slot(self.math, year=3, study_semester=1)
        self.sync(self.student(year=2), self.math)
        unit = self.post(["MATH 241"]).data["units"]["MATH 241"]
        self.assertEqual(self.classes(unit), [("BSC.CS", 2, 1, "", 1), ("BSC.CS", 3, 1, "", 0)])

    def test_a_slot_that_doesnt_say_takes_the_programme_years_usual_semester(self):
        self.slot(self.math)
        for _ in range(2):
            student = self.student()
            Student.objects.filter(user=student).update(current_semester=2)
        self.student()
        unit = self.post(["MATH 241"]).data["units"]["MATH 241"]
        self.assertEqual(self.classes(unit), [("BSC.CS", 2, 2, "", 0)])
        self.slot(self.cosc, year=4)  # nobody to go by
        self.assertEqual(self.classes(self.post(["COSC 130"]).data["units"]["COSC 130"]), [("BSC.CS", 4, 1, "", 0)])

    def test_duplicate_programmes_are_one_class(self):
        other = Department.objects.create(name="School of Computing", code="SOC")
        dup = Program.objects.create(department=other, code="BSC.CS2", name="BSC computer  science")
        self.slot(self.math, program=dup, study_semester=1)
        self.sync(self.student(), self.math)
        unit = self.post(["MATH 241"]).data["units"]["MATH 241"]
        self.assertEqual(self.classes(unit), [("BSC.CS", 2, 1, "", 1)])

    def test_the_generator_reads_the_same_classes_with_its_own_key(self):
        self.slot(self.math, study_semester=1)
        url = reverse("integrations-generator-unit-enrolment")
        self.assertEqual(self.client.post(url, {"codes": ["MATH 241"]}, format="json", HTTP_X_API_KEY=ATT_KEY).status_code, 403)
        unit = self.client.post(url, {"codes": ["MATH 241"]}, format="json", HTTP_X_API_KEY=GEN_KEY).data["units"]["MATH 241"]
        self.assertEqual(self.classes(unit), [("BSC.CS", 2, 1, "", 0)])

    def test_the_generator_reads_the_admins_rooms(self):
        Room.objects.create(code="UTC 1", name="UTC 1", building="UTC", capacity=300)
        Room.objects.create(code="LAB 2", name="Lab", building="Main", capacity=40, room_type=Room.Type.LAB)
        rooms = self.client.get(ROOMS, HTTP_X_API_KEY=GEN_KEY).data["rooms"]
        self.assertEqual([(r["code"], r["capacity"], r["status"]) for r in rooms], [("LAB 2", 40, "active"), ("UTC 1", 300, "active")])


@override_settings(ATTENDANCE_API_KEY=ATT_KEY, GENERATOR_API_KEY=GEN_KEY)
class GeneratorTermTests(APITestCase):
    def setUp(self):
        self.old = AcademicTerm.objects.create(
            academic_year="2025/2026", semester=2, start_date=date(2026, 1, 6), end_date=date(2026, 4, 30), is_current=True
        )
        self.url = reverse("integrations-generator-set-current")

    def post(self, body, key=GEN_KEY):
        return self.client.post(self.url, body, format="json", HTTP_X_API_KEY=key)

    def test_needs_the_generators_key(self):
        self.assertEqual(self.post({"academic_year": "2025/2026", "semester": 2}, key="wrong").status_code, 403)

    def test_makes_an_existing_term_current_and_lists_terms(self):
        term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18)
        )
        res = self.post({"academic_year": "2026/2027", "semester": 1, "by": "Dee Director"})
        self.assertEqual((res.status_code, res.data["id"], res.data["is_current"]), (200, str(term.pk), True))
        self.old.refresh_from_db()
        self.assertFalse(self.old.is_current)
        listed = self.client.get(reverse("integrations-generator-terms"), HTTP_X_API_KEY=GEN_KEY).data["terms"]
        self.assertEqual({t["id"]: t["is_current"] for t in listed}, {str(term.pk): True, str(self.old.pk): False})

    def test_creates_the_term_with_its_dates_or_says_it_needs_them(self):
        res = self.post({"academic_year": "2026/2027", "semester": 1})
        self.assertEqual((res.status_code, res.data["code"]), (422, "term_dates_required"))
        self.old.refresh_from_db()
        self.assertTrue(self.old.is_current)
        res = self.post({"academic_year": "2026/2027", "semester": 1, "term_start": "2026-09-07", "term_end": "2026-12-18"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(AcademicTerm.objects.get(pk=res.data["id"]).is_current)
