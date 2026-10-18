from datetime import date, time
from unittest import mock

from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.departments.models import Department, DepartmentAdmin, Faculty
from apps.integrations.allocator import section_key
from apps.lecturers.models import Lecturer
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.units.models import Unit

KEY = "test-allocator-key"


@override_settings(ALLOCATOR_API_KEY=KEY, ATTENDANCE_API_KEY="attendance-key", GENERATOR_API_KEY="generator-key")
class AllocatorTestCase(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        self.cs = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.edu = Department.objects.create(faculty=faculty, name="Education", code="ED")
        self.room = Room.objects.create(code="STB 1", name="Science Block 1", building="STB", capacity=150)
        self.room2 = Room.objects.create(code="STB 2", name="Science Block 2", building="STB", capacity=150)
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 21),
            end_date=date(2026, 12, 18), is_current=True,
        )
        self.bed = Program.objects.create(department=self.edu, name="Bachelor of Education", code="BED.MATH/CHEM")
        self.bsc = Program.objects.create(department=self.cs, name="BSc Computer Science", code="BSC.COMP SCI")
        self.cosc103 = Unit.objects.create(code="COSC 103", name="Intro to Computing", credit_hours=3,
                                           department=self.cs)
        self.edfo = Unit.objects.create(code="EDFO 111", name="Foundations", credit_hours=3, department=self.edu)

        self.jane = self._lecturer("STF/0001", "Jane", "Otieno")
        self.collins = self._lecturer("STF/0002", "Collins", "Mwangi", max_hours=4)

    def _lecturer(self, staff_number, first, last, department=None, max_hours=12):
        user = User.objects.create_user(
            username=staff_number.replace("/", ""), password="secret-pass", role=User.Role.LECTURER,
            university_id=staff_number, first_name=first, last_name=last,
        )
        return Lecturer.objects.create(user=user, department=department or self.cs,
                                       max_weekly_teaching_hours=max_hours)

    def _slot(self, unit, day="tue", start=(10, 0), end=(12, 0), room=None, program=None, group="MAIN", **kw):
        return TimetableSlot.objects.create(
            term=self.term, unit=unit, room=room or self.room, day_of_week=day,
            start_time=time(*start), end_time=time(*end), program=program or self.bed,
            class_group=group, **kw,
        )

    def _get(self, name, key=KEY, args=None, **params):
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        return self.client.get(reverse(name, args=args), params, **headers)

    def _patch(self, section, body, key=KEY):
        url = reverse("integrations-allocator-section-lecturer", args=[section])
        return self.client.patch(url, body, format="json", HTTP_X_API_KEY=key)


class AllocatorAccessTests(AllocatorTestCase):
    def test_requires_its_own_key(self):
        url = "integrations-allocator-sections"
        self.assertEqual(self._get(url, key=None, department=self.cs.id).status_code, 403)
        self.assertEqual(self._get(url, key="wrong", department=self.cs.id).status_code, 403)
        self.assertEqual(self._get(url, key="attendance-key", department=self.cs.id).status_code, 403)
        self.assertEqual(self._get(url, key="generator-key", department=self.cs.id).status_code, 403)
        self.assertEqual(self._get(url, department=self.cs.id).status_code, 200)

    @override_settings(ALLOCATOR_API_KEY="")
    def test_fails_closed_when_unset(self):
        self.assertEqual(self._get("integrations-allocator-terms", key="").status_code, 403)
        self.assertEqual(self._get("integrations-allocator-terms", key="anything").status_code, 403)


class AllocatorIdentityTests(AllocatorTestCase):
    def _auth(self, identifier, password):
        return self.client.post(
            reverse("integrations-allocator-authenticate"),
            {"identifier": identifier, "password": password}, format="json", HTTP_X_API_KEY=KEY,
        )

    def test_wrong_password_is_200_not_authenticated(self):
        response = self._auth("STF/0001", "nope")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": False})

    def test_cod_and_department_staff_roles(self):
        self.cs.head_of_department = self.jane.user
        self.cs.save()
        DepartmentAdmin.objects.create(user=self.jane.user, department=self.edu, role="editor")

        body = self._auth("stf/0001", "secret-pass").json()
        self.assertTrue(body["authenticated"])
        self.assertFalse(body["timetabling_office"])
        roles = {d["code"]: d["role"] for d in body["departments"]}
        self.assertEqual(roles, {"CS": "cod", "ED": "editor"})

    def test_timetabling_office_group(self):
        Group.objects.create(name="timetabling_office").user_set.add(self.collins.user)
        body = self._auth("STF/0002", "secret-pass").json()
        self.assertTrue(body["timetabling_office"])

    def test_identity_refresh_drops_inactive_accounts(self):
        url = "integrations-allocator-identity"
        self.assertEqual(self._get(url, account_id=str(self.jane.user.id)).status_code, 200)
        self.jane.user.is_active = False
        self.jane.user.save()
        self.assertEqual(self._get(url, account_id=str(self.jane.user.id)).status_code, 404)
        self.assertEqual(self._get(url, account_id="not-a-uuid").status_code, 404)


class AllocatorSectionsTests(AllocatorTestCase):
    def test_groups_slots_into_sections_including_servicing(self):
        # COSC 103 GR A serves two class rows (one physical class); GR B its own.
        self._slot(self.cosc103, program=self.bed, group="GR A")
        self._slot(self.cosc103, program=self.bsc, group="GR A")
        self._slot(self.cosc103, room=self.room2, group="GR B")
        self._slot(self.edfo, day="wed")  # Education's own unit: not CS's to allocate

        body = self._get("integrations-allocator-sections", department=self.cs.id).json()
        codes = [s["code"] for s in body["sections"]]
        self.assertEqual(codes, ["COSC 103 GR A", "COSC 103 GR B"])

        gr_a = body["sections"][0]
        self.assertEqual(gr_a["key"], section_key(self.cosc103.id, "GR A"))
        self.assertEqual(len(gr_a["class_rows"]), 2)
        self.assertEqual(len(gr_a["meetings"]), 1)  # same hour + room = one meeting
        self.assertEqual(gr_a["meetings"][0]["day_of_week"], "TUE")
        self.assertEqual(gr_a["weekly_hours"], 2.0)
        self.assertIsNone(gr_a["lecturer"])

    def test_registered_students_per_group(self):
        self._slot(self.cosc103, group="GR A")
        for i, group in enumerate(["GR A", "GR_A", "GR B", ""]):
            student = User.objects.create_user(username=f"s{i}", password="x", role=User.Role.STUDENT)
            StudentUnit.objects.create(user=student, unit=self.cosc103, term=self.term, class_group=group)
        section = self._get("integrations-allocator-sections", department=self.cs.id).json()["sections"][0]
        self.assertEqual(section["registered_students"], 2)

    def test_department_required_and_known(self):
        self.assertEqual(self._get("integrations-allocator-sections").status_code, 400)
        self.assertEqual(self._get("integrations-allocator-sections", department="x").status_code, 400)
        self.assertEqual(self._get("integrations-allocator-sections", department=999).status_code, 404)

    def test_no_current_term(self):
        AcademicTerm.objects.update(is_current=False)
        response = self._get("integrations-allocator-sections", department=self.cs.id)
        self.assertEqual(response.status_code, 404)


@mock.patch("apps.integrations.timetabling_views.notify_attendance_of_changes")
class AllocatorSetLecturerTests(AllocatorTestCase):
    def setUp(self):
        super().setUp()
        self._slot(self.cosc103, program=self.bed, group="GR A")
        self._slot(self.cosc103, program=self.bsc, group="GR A")
        self._slot(self.cosc103, room=self.room2, group="GR B")
        self.gr_a = section_key(self.cosc103.id, "GR A")
        self.gr_b = section_key(self.cosc103.id, "GR B")

    def test_sets_lecturer_on_every_slot_and_pushes(self, push):
        response = self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)})
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["changed"])
        self.assertEqual(body["section"]["lecturer"]["staff_number"], "STF/0001")

        slots = TimetableSlot.objects.filter(unit=self.cosc103, class_group="GR A")
        self.assertEqual({s.lecturer_id for s in slots}, {self.jane.id})
        self.assertEqual({s.lecturer_name_text for s in slots}, {"Jane Otieno"})
        push.assert_called_once()
        self.assertIn(("STF/0001", "COSC 103 GR A"), push.call_args.args[0])

    def test_same_lecturer_again_is_a_no_op(self, push):
        self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)})
        push.reset_mock()
        body = self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)}).json()
        self.assertFalse(body["changed"])
        push.assert_not_called()

    def test_double_booking_is_refused(self, push):
        self.assertEqual(self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)}).status_code, 200)
        response = self._patch(self.gr_b, {"lecturer_id": str(self.jane.id)})
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["code"], "lecturer_clash")
        self.assertEqual(body["clashes"][0]["clashes_with"], "COSC 103 GR A")
        self.assertIsNone(TimetableSlot.objects.get(unit=self.cosc103, class_group="GR B").lecturer_id)

    def test_clash_with_a_name_only_allocation_document_slot(self, push):
        self._slot(self.edfo, day="tue", start=(11, 0), end=(13, 0), lecturer_name_text="Dr. Jane Otieno (FT)")
        response = self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["clashes"][0]["clashes_with"], "EDFO 111")

    def test_back_to_back_is_not_a_clash(self, push):
        self._slot(self.edfo, day="tue", start=(12, 0), end=(14, 0), lecturer=self.jane)
        self.assertEqual(self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)}).status_code, 200)

    def test_weekly_hours_limit(self, push):
        self._slot(self.edfo, day="mon", start=(8, 0), end=(11, 0), lecturer=self.collins)  # 3 of 4 hours
        response = self._patch(self.gr_a, {"lecturer_id": str(self.collins.id)})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "max_hours")
        self.assertEqual(response.json()["weekly_hours"], 5.0)

    def test_stale_expected_lecturer(self, push):
        self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)})
        response = self._patch(self.gr_a, {"lecturer_id": str(self.collins.id), "expected_lecturer_id": None})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "stale")
        ok = self._patch(self.gr_a, {"lecturer_id": str(self.collins.id), "expected_lecturer_id": str(self.jane.id)})
        self.assertEqual(ok.status_code, 200)

    def test_replacing_pushes_both_lecturers(self, push):
        self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)})
        push.reset_mock()
        self._patch(self.gr_a, {"lecturer_id": str(self.collins.id)})
        changes = push.call_args.args[0]
        self.assertIn(("STF/0001", "COSC 103 GR A"), changes)
        self.assertIn(("STF/0002", "COSC 103 GR A"), changes)

    def test_clearing(self, push):
        self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)})
        body = self._patch(self.gr_a, {"lecturer_id": None}).json()
        self.assertIsNone(body["section"]["lecturer"])
        self.assertFalse(TimetableSlot.objects.filter(lecturer__isnull=False).exists())

    def test_bad_input(self, push):
        self.assertEqual(self._patch(self.gr_a, {}).status_code, 400)
        self.assertEqual(self._patch(self.gr_a, {"lecturer_id": 5}).status_code, 400)
        self.assertEqual(self._patch(self.gr_a, {"lecturer_id": "not-a-uuid"}).json()["code"], "unknown_lecturer")
        self.assertEqual(self._patch("garbage", {"lecturer_id": None}).status_code, 404)
        self.assertEqual(self._patch(f"{self.cosc103.id}-GRZ", {"lecturer_id": None}).status_code, 404)

    def test_inactive_lecturer_refused(self, push):
        self.jane.user.is_active = False
        self.jane.user.save()
        self.assertEqual(self._patch(self.gr_a, {"lecturer_id": str(self.jane.id)}).status_code, 400)


class AllocatorLecturerTests(AllocatorTestCase):
    def test_lecturers_with_their_week(self):
        self._slot(self.cosc103, lecturer=self.jane, group="GR A")
        self._slot(self.cosc103, lecturer=self.jane, group="GR A", program=self.bsc)
        body = self._get("integrations-allocator-lecturers", department=self.cs.id,
                         term=str(self.term.id)).json()
        jane = next(lec for lec in body["lecturers"] if lec["staff_number"] == "STF/0001")
        self.assertEqual(jane["employment_type"], "full_time")
        self.assertEqual(jane["weekly_hours"], 2.0)
        self.assertEqual(len(jane["meetings"]), 1)

    def test_without_term_no_meetings(self):
        body = self._get("integrations-allocator-lecturers").json()
        self.assertNotIn("meetings", body["lecturers"][0])

    def test_lecturer_sessions(self):
        self._slot(self.edfo, lecturer=self.jane)  # another department's unit still counts
        body = self._get("integrations-allocator-lecturer-sessions", args=[self.jane.id]).json()
        self.assertEqual(body["weekly_hours"], 2.0)
        self.assertEqual(body["meetings"][0]["code"], "EDFO 111")

    def test_departments(self):
        body = self._get("integrations-allocator-departments").json()
        self.assertEqual({d["code"] for d in body["departments"]}, {"CS", "ED"})
