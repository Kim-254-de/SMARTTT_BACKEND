from datetime import date, time
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.departments.models import Department, Faculty
from apps.integrations.attendance_push import change_payloads
from apps.lecturers.models import Lecturer
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetablePublication, TimetableSlot
from apps.units.models import Unit

KEY = "test-generator-key"
PUBLISH = reverse("integrations-generator-publish")


@override_settings(GENERATOR_API_KEY=KEY, ALLOCATOR_API_KEY="allocator-key")
@mock.patch("apps.integrations.timetabling_views.notify_attendance_of_changes")
class GeneratorTests(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        self.cs = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.room1 = Room.objects.create(code="STB 1", name="STB 1", building="STB", capacity=150,
                                         capacity_confirmed=True)
        self.room2 = Room.objects.create(code="STB 2", name="STB 2", building="STB", capacity=150)
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 21),
            end_date=date(2026, 12, 18), is_current=True,
        )
        self.bsc = Program.objects.create(department=self.cs, name="BSc Computer Science", code="BSC.COMP SCI")
        self.bit = Program.objects.create(department=self.cs, name="BSc IT", code="BSC.IT")
        self.cosc103 = Unit.objects.create(code="COSC 103", name="Intro", credit_hours=3, department=self.cs)
        self.cosc200 = Unit.objects.create(code="COSC 200", name="DS", credit_hours=3, department=self.cs)
        user = User.objects.create_user(username="jane", password="x", role=User.Role.LECTURER,
                                        university_id="STF/0001", first_name="Jane", last_name="Otieno")
        self.jane = Lecturer.objects.create(user=user, department=self.cs)

    def _session(self, key, unit=None, room=None, day="TUE", start="10:00", end="12:00", group=None, rows=None):
        return {
            "key": key, "unit_id": (unit or self.cosc103).id, "group_label": group,
            "class_rows": rows or [{"program_id": self.bsc.id, "year_of_study": 1, "study_semester": 1,
                                    "stream": ""}],
            "room_id": str((room or self.room1).id), "day_of_week": day, "start_time": start, "end_time": end,
        }

    def _publish(self, sessions, version=1, based_on=None, key=KEY, **extra):
        body = {"term_id": str(self.term.id), "version": version, "based_on_version": based_on,
                "published_by": "director", "sessions": sessions, **extra}
        return self.client.post(PUBLISH, body, format="json", HTTP_X_API_KEY=key)

    # -- access ------------------------------------------------------------
    def test_requires_generator_key(self, push):
        self.assertEqual(self._publish([self._session("A")], key="allocator-key").status_code, 403)
        snapshot = reverse("integrations-generator-snapshot")
        self.assertEqual(self.client.get(snapshot, HTTP_X_API_KEY="allocator-key").status_code, 403)

    # -- snapshot ----------------------------------------------------------
    def test_snapshot(self, push):
        TimetableSlot.objects.create(term=self.term, unit=self.cosc103, room=self.room1, day_of_week="tue",
                                     start_time=time(10), end_time=time(12), program=self.bsc,
                                     class_group="GR A", lecturer=self.jane)
        body = self.client.get(reverse("integrations-generator-snapshot"), HTTP_X_API_KEY=KEY).json()
        self.assertEqual(body["term"]["id"], str(self.term.id))
        self.assertEqual(body["departments"][0]["lecturers"], {"full_time": 1, "part_time": 0})
        self.assertEqual(len(body["rooms"]), 2)
        self.assertIsNone(body["published"]["version"])
        session = body["published"]["sessions"][0]
        self.assertIsNone(session["key"])
        self.assertEqual(session["lecturer_id"], str(self.jane.id))
        self.assertEqual(session["group_label"], "GR A")
        codes = {w["code"] for w in body["warnings"]}
        self.assertIn("room_capacity_unconfirmed", codes)
        self.assertIn("program_without_curriculum", codes)

    # -- publish -----------------------------------------------------------
    def test_publish_creates_one_slot_per_class_row(self, push):
        rows = [{"program_id": self.bsc.id, "year_of_study": 1, "study_semester": 1, "stream": ""},
                {"program_id": self.bit.id, "year_of_study": 1, "study_semester": 1, "stream": "2"}]
        response = self._publish([self._session("COSC103-GRA-1", group="GR A", rows=rows)])
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["slot_count"], 2)
        self.assertEqual(body["changes"]["added"], ["COSC103-GRA-1"])
        slots = TimetableSlot.objects.filter(session_key="COSC103-GRA-1")
        self.assertEqual(slots.count(), 2)
        self.assertEqual({s.class_group for s in slots}, {"GR A"})
        self.assertEqual({s.day_of_week for s in slots}, {"tue"})
        push.assert_called_once()

    def test_idempotent_on_version(self, push):
        sessions = [self._session("A")]
        self.assertEqual(self._publish(sessions).status_code, 201)
        again = self._publish(sessions)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(TimetablePublication.objects.count(), 1)
        self.assertEqual(TimetableSlot.objects.count(), 1)
        different = self._publish([self._session("A", day="WED")])
        self.assertEqual(different.status_code, 409)
        self.assertEqual(different.json()["code"], "version_taken")

    def test_version_guard(self, push):
        self.assertEqual(self._publish([self._session("A")]).status_code, 201)
        stale = self._publish([self._session("A", day="WED")], version=2, based_on=None)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["code"], "stale_base")
        self.assertEqual(self._publish([self._session("A", day="WED")], version=2, based_on=1).status_code, 201)

    def test_republish_moves_by_key_and_reports_changes(self, push):
        self._publish([self._session("A"), self._session("B", unit=self.cosc200, day="MON"),
                       self._session("C", unit=self.cosc200, day="FRI")])
        kept = TimetableSlot.objects.get(session_key="B").id
        response = self._publish(
            [self._session("A", day="WED"), self._session("B", unit=self.cosc200, day="MON"),
             self._session("D", unit=self.cosc200, day="THU")],
            version=2, based_on=1,
        )
        changes = response.json()["changes"]
        self.assertEqual(changes["moved"], ["A"])
        self.assertEqual(changes["added"], ["D"])
        self.assertEqual(changes["removed"], ["C"])
        self.assertEqual(changes["unchanged"], 1)
        self.assertEqual(TimetableSlot.objects.get(session_key="B").id, kept)
        self.assertEqual(TimetableSlot.objects.get(session_key="A").day_of_week, "wed")
        self.assertFalse(TimetableSlot.objects.filter(session_key="C").exists())

    def test_lecturer_kept_across_versions(self, push):
        self._publish([self._session("A", group="GR A")])
        TimetableSlot.objects.filter(session_key="A").update(lecturer=self.jane, lecturer_name_text="Jane Otieno")
        self._publish([self._session("A", group="GR A", day="THU")], version=2, based_on=1)
        slot = TimetableSlot.objects.get(session_key="A")
        self.assertEqual(slot.day_of_week, "thu")
        self.assertEqual(slot.lecturer_id, self.jane.id)

    def test_refuses_moving_an_allocated_lecturer_into_a_clash(self, push):
        self._publish([self._session("A", group="GR A"), self._session("B", unit=self.cosc200, day="MON")])
        TimetableSlot.objects.update(lecturer=self.jane)
        response = self._publish(
            [self._session("A", group="GR A"), self._session("B", unit=self.cosc200, room=self.room2,
                                                             rows=[{"program_id": self.bit.id,
                                                                    "year_of_study": 2}])],
            version=2, based_on=1,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "lecturer_clash")
        self.assertEqual(TimetablePublication.objects.count(), 1)

    def test_unpublished_slots_need_explicit_replace(self, push):
        TimetableSlot.objects.create(term=self.term, unit=self.cosc103, room=self.room1, day_of_week="mon",
                                     start_time=time(7), end_time=time(9), program=self.bsc,
                                     lecturer=self.jane)
        refused = self._publish([self._session("A")])
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["code"], "unpublished_slots")
        ok = self._publish([self._session("A")], replace_unpublished=True)
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(ok.json()["changes"]["replaced_unpublished_slots"], 1)
        slot = TimetableSlot.objects.get()
        self.assertEqual(slot.session_key, "A")
        self.assertEqual(slot.lecturer_id, self.jane.id)  # the uploaded section's lecturer carries over

    def test_hard_rules(self, push):
        room_clash = self._publish([self._session("A"), self._session("B", unit=self.cosc200,
                                                                      rows=[{"program_id": self.bit.id,
                                                                             "year_of_study": 1}])])
        self.assertEqual(room_clash.status_code, 422)
        self.assertEqual(room_clash.json()["errors"][0]["rule"], "H1")

        row_clash = self._publish([self._session("A"), self._session("B", unit=self.cosc200, room=self.room2)])
        self.assertEqual(row_clash.json()["errors"][0]["rule"], "H2")

        # One class row split across parallel groups of the same unit is fine.
        parallel = self._publish([self._session("A", group="GR A"),
                                  self._session("B", group="GR B", room=self.room2)])
        self.assertEqual(parallel.status_code, 201, parallel.content)
        self.assertEqual(TimetableSlot.objects.count(), 2)

    def test_validation_errors(self, push):
        cases = [
            self._session("A", day="SAT"),
            self._session("A", start="06:00", end="08:00"),
            self._session("A", start="18:00", end="20:00"),
            self._session("A", start="12:00", end="10:00"),
            self._session("A", start="9am"),
            {**self._session("A"), "unit_id": 99999},
            {**self._session("A"), "room_id": "nope"},
            {**self._session("A"), "class_rows": []},
            {**self._session("A"), "key": "has spaces"},
        ]
        for session in cases:
            response = self._publish([session])
            self.assertEqual(response.status_code, 422, session)
        self.assertEqual(self._publish([self._session("A"), self._session("A")]).status_code, 422)
        self.assertEqual(self._publish([]).status_code, 400)
        self.assertEqual(self._publish([self._session("A")], version=0).status_code, 400)
        self.assertFalse(TimetableSlot.objects.exists())

    def test_publication_status(self, push):
        self._publish([self._session("A")])
        url = reverse("integrations-generator-publication", args=[1])
        self.assertEqual(self.client.get(url, HTTP_X_API_KEY=KEY).json()["version"], 1)
        missing = reverse("integrations-generator-publication", args=[2])
        self.assertEqual(self.client.get(missing, HTTP_X_API_KEY=KEY).status_code, 404)


class ChangePayloadTests(APITestCase):
    def test_groups_by_lecturer(self):
        payloads = change_payloads([
            ("stf/0001", "COSC 103 GR A"), ("STF/0001", "COSC 200"), (None, "COSC 103 GR B"),
            ("STF/0001", "COSC 200"),
        ])
        self.assertEqual(payloads, [
            {"staff_number": None, "unit_codes": ["COSC 103 GR B"]},
            {"staff_number": "STF/0001", "unit_codes": ["COSC 103 GR A", "COSC 200"]},
        ])


@override_settings(GENERATOR_API_KEY=KEY, ATTENDANCE_API_KEY="attendance-key", ALLOCATOR_API_KEY="allocator-key")
class PublishToAttendanceTests(APITestCase):
    """A published, allocated class is what Smart Attendance lets the lecturer activate."""

    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        cs = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.room = Room.objects.create(code="STB 1", name="STB 1", building="STB", capacity=150)
        self.room2 = Room.objects.create(code="STB 2", name="STB 2", building="STB", capacity=150)
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 21),
            end_date=date(2026, 12, 18), is_current=True,
        )
        self.program = Program.objects.create(department=cs, name="BSc CS", code="BSC.COMP SCI")
        self.unit = Unit.objects.create(code="COSC 103", name="Intro", credit_hours=3, department=cs)
        user = User.objects.create_user(username="jane", password="x", role=User.Role.LECTURER,
                                        university_id="STF/0001", first_name="Jane", last_name="Otieno")
        self.jane = Lecturer.objects.create(user=user, department=cs)

    def _publish(self, version, based_on, day, room):
        body = {"term_id": str(self.term.id), "version": version, "based_on_version": based_on,
                "published_by": "director", "sessions": [{
                    "key": "COSC103-GRA-1", "unit_id": self.unit.id, "group_label": "GR A",
                    "class_rows": [{"program_id": self.program.id, "year_of_study": 1, "study_semester": 1,
                                    "stream": ""}],
                    "room_id": str(room.id), "day_of_week": day, "start_time": "10:00", "end_time": "12:00"}]}
        return self.client.post(PUBLISH, body, format="json", HTTP_X_API_KEY=KEY)

    @mock.patch("apps.integrations.timetabling_views.notify_attendance_of_changes")
    def test_published_class_reaches_the_lecturers_attendance_units(self, push):
        self.assertEqual(self._publish(1, None, "TUE", self.room).status_code, 201)

        from apps.integrations.allocator import section_key, set_section_lecturer

        set_section_lecturer(self.term, section_key(self.unit.id, "GR A"), str(self.jane.id))
        units = self.client.get(
            reverse("integrations-attendance-lecturer-units"), {"staff_number": "STF/0001"},
            HTTP_X_API_KEY="attendance-key",
        ).json()["units"]
        self.assertEqual(units[0]["code"], "COSC 103 GR A")
        # SMARTTT stores TUE; attendance counts days 0=Sunday, so Tuesday is 2.
        self.assertEqual(units[0]["slots"], [{"day_of_week": 2, "start_time": "10:00", "end_time": "12:00",
                                              "room": "STB 1", "class_group": "GR A", "program": "BSc CS"}])

        # A mid-term room move is pushed to attendance for Jane's class.
        push.reset_mock()
        response = self._publish(2, 1, "TUE", self.room2)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["changes"]["moved"], ["COSC103-GRA-1"])
        self.assertIn(("STF/0001", "COSC 103 GR A"), push.call_args.args[0])
        slot = TimetableSlot.objects.get(session_key="COSC103-GRA-1")
        self.assertEqual((slot.room_id, slot.lecturer_id), (self.room2.id, self.jane.id))
