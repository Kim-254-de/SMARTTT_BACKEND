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
URL = reverse("integrations-attendance-lecturer-units")


@override_settings(ATTENDANCE_API_KEY=KEY)
class AttendanceLecturerUnitsTests(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        self.dept = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.room = Room.objects.create(code="LH1", name="Lecture Hall 1", building="Main", capacity=100)
        self.room2 = Room.objects.create(code="LAB2", name="Lab 2", building="Main", capacity=40)
        self.term = AcademicTerm.objects.create(
            academic_year="2025/2026", semester=1, start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20), is_current=True,
        )
        self.old_term = AcademicTerm.objects.create(
            academic_year="2024/2025", semester=2, start_date=date(2025, 1, 6),
            end_date=date(2025, 4, 30), is_current=False,
        )
        self.cosc100 = self._unit("COSC 100", "Intro to Computing")
        self.cosc200 = self._unit("COSC 200", "Data Structures")
        self.cosc300 = self._unit("COSC 300", "Someone else's unit")

        self.user = User.objects.create_user(
            username="pkamami", password="x", role=User.Role.LECTURER,
            university_id="STF/0001", first_name="Peter", last_name="Kamami",
        )
        self.lecturer = Lecturer.objects.create(user=self.user, department=self.dept)
        other = User.objects.create_user(
            username="other", password="x", role=User.Role.LECTURER,
            university_id="STF/0002", first_name="Jane", last_name="Otieno",
        )
        self.other_lecturer = Lecturer.objects.create(user=other, department=self.dept)

    # -- helpers -----------------------------------------------------------
    def _unit(self, code, name):
        return Unit.objects.create(code=code, name=name, credit_hours=3, department=self.dept)

    def _slot(self, unit, day="mon", start=(8, 0), end=(10, 0), room=None, term=None, **kw):
        return TimetableSlot.objects.create(
            term=term or self.term, unit=unit, room=room or self.room, day_of_week=day,
            start_time=time(*start), end_time=time(*end), **kw,
        )

    def _register(self, unit, count, term=None):
        for i in range(count):
            student, _ = User.objects.get_or_create(
                username=f"s{i}", defaults={"role": User.Role.STUDENT, "university_id": f"REG/{i}"},
            )
            StudentUnit.objects.create(user=student, unit=unit, term=term or self.term)

    def _get(self, key=KEY, **params):
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        return self.client.get(URL, params, **headers)

    # -- auth --------------------------------------------------------------
    def test_requires_the_api_key(self):
        self.assertEqual(self._get(key=None, staff_number="STF/0001").status_code, 403)
        self.assertEqual(self._get(key="wrong", staff_number="STF/0001").status_code, 403)

    @override_settings(ATTENDANCE_API_KEY="")
    def test_refuses_everything_when_key_not_configured(self):
        self.assertEqual(self._get(key="", staff_number="STF/0001").status_code, 403)
        self.assertEqual(self._get(key="anything", staff_number="STF/0001").status_code, 403)

    def test_user_jwt_is_not_enough(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self._get(key=None, staff_number="STF/0001").status_code, 403)

    # -- behaviour ---------------------------------------------------------
    def test_returns_units_counts_and_slots_for_the_account(self):
        self._slot(self.cosc100, day="mon", lecturer=self.lecturer)
        self._slot(self.cosc100, day="thu", start=(14, 0), end=(16, 0), room=self.room2, lecturer=self.lecturer)
        self._slot(self.cosc200, day="wed", lecturer=self.lecturer)
        self._slot(self.cosc300, day="tue", lecturer=self.other_lecturer)   # not theirs
        self._slot(self.cosc200, day="fri", lecturer=self.lecturer, term=self.old_term)  # old term
        self._register(self.cosc100, 3)
        self._register(self.cosc200, 1, term=self.old_term)  # registered last term only

        res = self._get(staff_number="stf/0001")  # case-insensitive
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data["lecturer_account"])
        self.assertEqual(res.data["term"], {"academic_year": "2025/2026", "semester": 1})

        units = {u["code"]: u for u in res.data["units"]}
        self.assertEqual(list(units), ["COSC 100", "COSC 200"])
        self.assertEqual(units["COSC 100"]["registered_students"], 3)
        self.assertEqual(units["COSC 200"]["registered_students"], 0)
        self.assertEqual(units["COSC 100"]["matched_by"], "account")
        self.assertEqual(
            [(s["day_of_week"], s["start_time"], s["end_time"], s["room"]) for s in units["COSC 100"]["slots"]],
            [(1, "08:00", "10:00", "LH1"), (4, "14:00", "16:00", "LAB2")],
        )

    def test_lists_each_units_registered_students_with_reg_numbers_and_names(self):
        from apps.students.models import Student

        self._slot(self.cosc100, lecturer=self.lecturer)
        a = User.objects.create_user(username="a", password="x", role=User.Role.STUDENT,
                                     university_id="ebt1/00002/23", first_name="Amina", last_name="Kamau")
        b = User.objects.create_user(username="b", password="x", role=User.Role.STUDENT,
                                     university_id="EBT1/00001/23", first_name="Brian", last_name="Otieno")
        no_id = User.objects.create_user(username="c", password="x", role=User.Role.STUDENT)  # can't be rostered
        old = User.objects.create_user(username="d", password="x", role=User.Role.STUDENT, university_id="EBT1/00009/22")
        for student in (a, b, no_id):
            StudentUnit.objects.create(user=student, unit=self.cosc100, term=self.term)
        StudentUnit.objects.create(user=old, unit=self.cosc100, term=self.old_term)  # last term only

        # No university_id, but a Student profile carries the registration number.
        from apps.programs.models import Program

        program = Program.objects.create(department=self.dept, name="BSc Computer Science", code="BSCCS")
        profiled = User.objects.create_user(username="e", password="x", role=User.Role.STUDENT,
                                            email="c.ouma@example.com")
        Student.objects.create(user=profiled, registration_number="EBT1/00005/23", program=program,
                               department=self.dept, admission_year=2023,
                               first_name="Cynthia", last_name="Ouma", email="c.ouma@example.com")
        StudentUnit.objects.create(user=profiled, unit=self.cosc100, term=self.term)

        unit = self._get(staff_number="STF/0001").data["units"][0]
        self.assertEqual(unit["registered_students"], 4)
        self.assertEqual(unit["students"], [
            {"registration_number": "EBT1/00001/23", "full_name": "Brian Otieno"},
            {"registration_number": "EBT1/00002/23", "full_name": "Amina Kamau"},
            {"registration_number": "EBT1/00005/23", "full_name": "Cynthia Ouma"},
        ])

    def test_same_class_printed_for_several_programs_is_reported_once(self):
        from apps.programs.models import Program

        bsc = Program.objects.create(department=self.dept, name="BSc CS", code="BSCCS")
        bed = Program.objects.create(department=self.dept, name="BEd Sci", code="BEDSCI")
        self._slot(self.cosc100, lecturer=self.lecturer, program=bsc)
        self._slot(self.cosc100, lecturer=self.lecturer, program=bed)  # same day/time/room
        res = self._get(staff_number="STF/0001")
        self.assertEqual(len(res.data["units"]), 1)
        self.assertEqual(len(res.data["units"][0]["slots"]), 1)

    # -- units split into groups (COSC 103 GR A / GR B ...) ------------------
    def _student(self, reg, group, name="", unit=None):
        first, _, last = name.partition(" ")
        user = User.objects.create_user(username=reg, password="x", role=User.Role.STUDENT,
                                        university_id=reg, first_name=first, last_name=last)
        StudentUnit.objects.create(user=user, unit=unit or self.cosc100, term=self.term, class_group=group)
        return user

    def _split_cosc103(self):
        """COSC 103 split into GR A (this lecturer) and GR B (another), plus students in each."""
        cosc103 = self._unit("COSC 103", "Computer Applications")
        self._slot(cosc103, day="mon", class_group="GR_A", lecturer=self.lecturer)
        self._slot(cosc103, day="wed", start=(14, 0), end=(16, 0), class_group="GR_A", lecturer=self.lecturer)
        self._slot(cosc103, day="tue", class_group="GR_B", lecturer=self.other_lecturer)
        self._student("EBT1/00001/23", "GR A", "Amina Kamau", cosc103)   # written differently, same group
        self._student("EBT1/00002/23", "GR_A", "Brian Otieno", cosc103)
        self._student("EBT1/00003/23", "GR_B", "Cynthia Ouma", cosc103)
        self._student("EBT1/00004/23", "", "David Mwangi", cosc103)      # hasn't picked yet
        self._student("EBT1/00005/23", "", "Esther Wanjiru", cosc103)    # hasn't picked yet
        return cosc103

    def test_each_group_of_a_split_unit_is_its_own_class_with_only_its_students(self):
        self._split_cosc103()
        res = self._get(staff_number="STF/0001")
        self.assertEqual(len(res.data["units"]), 1)
        section = res.data["units"][0]
        self.assertEqual(section["code"], "COSC 103 GR A")
        self.assertEqual(section["unit_code"], "COSC 103")
        self.assertEqual(section["group"], "GR A")
        self.assertEqual(section["registered_students"], 2)
        self.assertEqual(section["students_without_group"], 2)
        self.assertEqual([s["registration_number"] for s in section["students"]], ["EBT1/00001/23", "EBT1/00002/23"])
        self.assertEqual([s["day_of_week"] for s in section["slots"]], [1, 3])

        other = self._get(staff_number="STF/0002").data["units"]
        self.assertEqual([(u["code"], u["registered_students"]) for u in other], [("COSC 103 GR B", 1)])
        self.assertEqual([s["full_name"] for s in other[0]["students"]], ["Cynthia Ouma"])

    def test_a_lecturer_with_the_lecture_and_a_group_gets_two_classes(self):
        cosc103 = self._split_cosc103()
        self._slot(cosc103, day="fri", room=self.room2, lecturer=self.lecturer)  # MAIN: the whole class
        units = {u["code"]: u for u in self._get(staff_number="STF/0001").data["units"]}
        self.assertEqual(list(units), ["COSC 103", "COSC 103 GR A"])
        self.assertIsNone(units["COSC 103"]["group"])
        self.assertEqual(units["COSC 103"]["registered_students"], 5)  # everyone, picked or not
        self.assertEqual(units["COSC 103"]["students_without_group"], 0)
        self.assertEqual(units["COSC 103 GR A"]["registered_students"], 2)

    def test_lecturer_dashboard_counts_only_the_lecturers_group(self):
        self._split_cosc103()
        self.client.force_authenticate(self.user)
        data = self.client.get(reverse("lecturer-profile")).data
        counts = {s["day"]: s["student_count"] for day in data["timetable"].values() for s in day}
        self.assertEqual(counts, {"MON": 2, "WED": 2})
        self.assertEqual(data["summary"]["total_students"], 2)

    def test_allocation_name_match_counts_without_claiming_the_slot(self):
        slot = self._slot(self.cosc200, lecturer_name_text="Dr. Peter Kamami / Kevin Tuei")
        res = self._get(staff_number="STF/0001")
        self.assertEqual([u["code"] for u in res.data["units"]], ["COSC 200"])
        self.assertEqual(res.data["units"][0]["matched_by"], "name")
        slot.refresh_from_db()
        self.assertIsNone(slot.lecturer_id)  # read-only, unlike the dashboard

    def test_no_account_falls_back_to_the_name_given(self):
        self._slot(self.cosc100, lecturer_name_text="Ann Wanjiru")
        res = self._get(staff_number="STF/0099", name="Dr. Ann Wanjiru")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["lecturer_account"])
        self.assertEqual([u["code"] for u in res.data["units"]], ["COSC 100"])
        self.assertEqual(res.data["units"][0]["matched_by"], "name")

    def test_unknown_lecturer_without_a_name_is_404(self):
        self.assertEqual(self._get(staff_number="STF/0099").status_code, 404)

    def test_staff_number_is_required(self):
        self.assertEqual(self._get().status_code, 400)

    def test_no_current_term_returns_no_units(self):
        self._slot(self.cosc100, lecturer=self.lecturer)
        AcademicTerm.objects.update(is_current=False)
        res = self._get(staff_number="STF/0001")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["term"])
        self.assertEqual(res.data["units"], [])
