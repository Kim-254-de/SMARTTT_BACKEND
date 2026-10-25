import copy
from datetime import date, time
from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.departments.models import Department
from apps.integrations import attendance_push
from apps.lecturers.models import Lecturer
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.integrations.services import get_lecturer_units
from apps.timetable.models import AcademicTerm, AllocationDocument, TimetablePublication, TimetableSlot
from apps.units.models import Unit

KEY = "test-generator-key"
URL = "/api/v1/integrations/generator/publish/"


class InlineThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class PublishCase(APITestCase):
    """Departments, a programme, a unit and a hall, and helpers to publish a payload."""

    def setUp(self):
        self.cs = Department.objects.create(name="Computer Science", code="CS")
        self.edu = Department.objects.create(name="Education", code="ED")
        self.bsc = Program.objects.create(department=self.cs, code="BSC.COMP SCI", name="BSc Computer Science")
        self.cosc = Unit.objects.create(code="COSC 103", name="Computer Applications", credit_hours=3, department=self.cs)
        self.hall = Room.objects.create(code="STB 1", name="STB 1", building="STB", capacity=120)

    def session(self, key="COSC103-GRA-1", **over):
        s = {
            "key": key,
            "unit_id": None,
            "unit_code": "COSC 103",
            "unit_name": "Computer Applications",
            "weekly_hours": 3,
            "department": {"smarttt_id": self.cs.pk, "code": "DCOMP", "name": "Computer Science"},
            "group_label": "GR A",
            "room": {"code": "STB 1", "building": "STB", "capacity": 120, "room_type": "lecture_hall"},
            "day_of_week": "TUE",
            "start_time": "10:00",
            "end_time": "12:00",
            "class_rows": [
                {"label": "BSC.COMP SCI Y1S1", "program_id": None, "program_code": "BSC.COMP SCI",
                 "year_of_study": 1, "study_semester": 1, "stream": "", "department_smarttt_id": self.cs.pk},
            ],
        }
        s.update(over)
        return s

    def payload(self, sessions, version=1, based_on=None, **over):
        p = {
            "term_id": None,
            "academic_year": "2026/2027",
            "semester": 1,
            "term_start": "2026-09-07",
            "term_end": "2026-12-18",
            "version": version,
            "based_on_version": based_on,
            "published_by": "Dee Director (STF/0900)",
            "replace_unpublished": False,
            "sessions": sessions,
        }
        p.update(over)
        return p

    def post(self, payload, key=KEY):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(URL, payload, format="json", HTTP_X_API_KEY=key)



@override_settings(GENERATOR_API_KEY=KEY, ATTENDANCE_BASE_URL="", ATTENDANCE_API_KEY="")
class GeneratorPublishTests(PublishCase):
    def test_needs_the_generators_own_key(self):
        self.assertEqual(self.client.post(URL, {}, format="json").status_code, 403)
        self.assertEqual(self.post(self.payload([self.session()]), key="wrong").status_code, 403)
        with override_settings(GENERATOR_API_KEY=""):
            self.assertEqual(self.post(self.payload([self.session()]), key="").status_code, 403)

    def test_first_publish_creates_the_term_and_one_slot_per_class_row(self):
        bed = {"label": "BED.ARTS Y1S1", "program_id": None, "program_code": "BED.ARTS", "year_of_study": 1,
               "study_semester": 1, "stream": "", "department_smarttt_id": self.edu.pk}
        new_unit = self.session(
            "EDFO111-1", unit_code="EDFO 111", unit_name="Foundations of Education",
            department={"smarttt_id": self.edu.pk, "code": "DEDU", "name": "Education"},
            group_label=None, room={"code": "NEW 9", "building": "NEW", "capacity": 300, "room_type": "lecture_hall"},
            day_of_week="WED", class_rows=[bed],
        )
        res = self.post(self.payload([self.session(), new_unit]))
        self.assertEqual(res.status_code, 201, res.content)

        term = AcademicTerm.objects.get(academic_year="2026/2027", semester=1)
        self.assertEqual((term.start_date, term.end_date), (date(2026, 9, 7), date(2026, 12, 18)))
        self.assertEqual(res.data["term_id"], str(term.pk))
        self.assertEqual(res.data["changes"], {"added": ["COSC103-GRA-1", "EDFO111-1"], "moved": [], "removed": [], "unchanged": 0})
        self.assertEqual(res.data["created"], {"units": ["EDFO 111"], "rooms": ["NEW 9"], "programs": ["BED.ARTS"]})
        self.assertEqual(res.data["units"]["COSC 103"], self.cosc.pk)

        slot = TimetableSlot.objects.get(term=term, generator_key="COSC103-GRA-1|BSCCOMPSCIY1S1")
        self.assertEqual((slot.unit, slot.program, slot.room), (self.cosc, self.bsc, self.hall))
        self.assertEqual((slot.day_of_week, slot.start_time, slot.end_time, slot.class_group), ("tue", time(10), time(12), "GR_A"))
        edfo = TimetableSlot.objects.get(term=term, generator_key="EDFO111-1|BEDARTSY1S1")
        self.assertEqual((edfo.class_group, edfo.unit.department, edfo.program.department), ("MAIN", self.edu, self.edu))
        self.assertTrue(Room.objects.get(code="NEW 9").capacity_confirmed)
        self.assertEqual(TimetablePublication.objects.get(term=term).version, 1)

    def test_resending_a_version_answers_the_stored_result_and_never_rewrites(self):
        first = self.post(self.payload([self.session()]))
        again = self.post(self.payload([self.session()]))
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(again.data, first.data)
        other = self.post(self.payload([self.session(start_time="14:00", end_time="16:00")]))
        self.assertEqual((other.status_code, other.data["code"]), (409, "version_taken"))
        self.assertEqual(TimetableSlot.objects.get().start_time, time(10))

    def test_a_new_version_updates_slots_in_place_and_keeps_their_lecturers(self):
        self.post(self.payload([self.session(), self.session("COSC103-GRA-2", day_of_week="THU")]))
        slot = TimetableSlot.objects.get(generator_key="COSC103-GRA-1|BSCCOMPSCIY1S1")
        user = User.objects.create_user(username="pk", password="x", role=User.Role.LECTURER, university_id="STF/0001")
        slot.lecturer = Lecturer.objects.create(user=user, department=self.cs)
        slot.save()

        moved = self.session(day_of_week="FRI", start_time="08:00", end_time="10:00")
        res = self.post(self.payload([moved, self.session("COSC103-GRB-1", group_label="GR B")], version=2, based_on=1))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["changes"], {"added": ["COSC103-GRB-1"], "moved": ["COSC103-GRA-1"], "removed": ["COSC103-GRA-2"], "unchanged": 0})

        kept = TimetableSlot.objects.get(pk=slot.pk)
        self.assertEqual((kept.day_of_week, kept.start_time, kept.lecturer_id), ("fri", time(8), slot.lecturer_id))
        self.assertFalse(TimetableSlot.objects.filter(generator_key__startswith="COSC103-GRA-2|").exists())
        self.assertEqual(TimetableSlot.objects.count(), 2)

    def test_two_classes_can_swap_places(self):
        a = self.session("A-1")
        b = self.session("B-1", group_label="GR B", start_time="12:00", end_time="14:00")
        self.post(self.payload([a, b]))
        swapped = [{**a, "start_time": "12:00", "end_time": "14:00"}, {**b, "start_time": "10:00", "end_time": "12:00"}]
        res = self.post(self.payload(swapped, version=2, based_on=1))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(sorted(res.data["changes"]["moved"]), ["A-1", "B-1"])

    def test_versions_only_go_up_from_smarttts_latest(self):
        self.post(self.payload([self.session()]))
        for version, based_on in ((2, None), (3, 2), (2, 2)):
            res = self.post(self.payload([self.session()], version=version, based_on=based_on))
            self.assertEqual((res.status_code, res.data["code"], res.data["latest_version"]), (409, "stale_base", 1))

    def test_uploaded_slots_are_only_replaced_when_confirmed(self):
        term = AcademicTerm.objects.create(academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18))
        TimetableSlot.objects.create(term=term, unit=self.cosc, room=self.hall, day_of_week="mon", start_time=time(8), end_time=time(10))
        res = self.post(self.payload([self.session()], term_id=str(term.pk)))
        self.assertEqual((res.status_code, res.data["code"], res.data["unpublished_slots"]), (409, "unpublished_slots", 1))

        res = self.post(self.payload([self.session()], term_id=str(term.pk), replace_unpublished=True))
        self.assertEqual((res.status_code, res.data["replaced_uploaded_slots"]), (201, 1))
        self.assertFalse(TimetableSlot.objects.filter(term=term, generator_key="").exists())

    def test_refuses_a_broken_timetable_and_writes_nothing(self):
        clash = self.session("X-1", group_label="GR X", start_time="11:00", end_time="13:00")
        res = self.post(self.payload([self.session(), clash]))
        self.assertEqual((res.status_code, res.data["code"]), (422, "invalid_timetable"))
        self.assertIn("STB 1 holds", res.data["detail"])

        late = self.session(start_time="18:00", end_time="20:00")
        self.assertEqual(self.post(self.payload([late])).status_code, 422)

        orphan = self.session(unit_code="ZZZ 999", department={"smarttt_id": 9999, "code": "DX", "name": "Nowhere"})
        res = self.post(self.payload([orphan]))
        self.assertEqual((res.status_code, res.data["code"]), (422, "unknown_department"))

        self.assertFalse(AcademicTerm.objects.exists())
        self.assertFalse(Unit.objects.filter(code="ZZZ 999").exists())
        self.assertFalse(TimetablePublication.objects.exists())

    def test_a_new_term_needs_its_dates_and_a_given_term_must_match(self):
        res = self.post(self.payload([self.session()], term_start=None, term_end=None))
        self.assertEqual((res.status_code, res.data["code"]), (422, "term_dates_required"))
        term = AcademicTerm.objects.create(academic_year="2025/2026", semester=3, start_date=date(2026, 5, 4), end_date=date(2026, 8, 21))
        res = self.post(self.payload([self.session()], term_id=str(term.pk)))
        self.assertEqual((res.status_code, res.data["code"]), (422, "term_mismatch"))

    def test_a_malformed_payload_is_a_400(self):
        bad = self.payload([self.session(day_of_week="SAT")])
        res = self.post(bad)
        self.assertEqual((res.status_code, res.data["code"]), (400, "invalid_payload"))

    def test_reads_back_what_a_publish_did(self):
        term_id = self.post(self.payload([self.session()])).data["term_id"]
        res = self.client.get(f"{URL}1/", {"term": term_id}, HTTP_X_API_KEY=KEY)
        self.assertEqual((res.status_code, res.data["version"], res.data["published_by"]), (200, 1, "Dee Director (STF/0900)"))
        self.assertEqual(self.client.get(f"{URL}2/", {"term": term_id}, HTTP_X_API_KEY=KEY).status_code, 404)
        self.assertEqual(self.client.get(f"{URL}1/", {"term": "nope"}, HTTP_X_API_KEY=KEY).status_code, 404)

    @override_settings(ATTENDANCE_BASE_URL="https://attendance.test.local", ATTENDANCE_API_KEY="att-key")
    def test_tells_attendance_once_per_lecturer_whose_class_moved(self):
        self.post(self.payload([self.session()]))
        user = User.objects.create_user(username="pk", password="x", role=User.Role.LECTURER, university_id="STF/0001")
        TimetableSlot.objects.update(lecturer=Lecturer.objects.create(user=user, department=self.cs))

        moved = copy.deepcopy(self.session(day_of_week="MON"))
        moved["class_rows"].append({**moved["class_rows"][0], "label": "BSC.COMP SCI Y2S1", "year_of_study": 2})
        with mock.patch.object(attendance_push.threading, "Thread", InlineThread), \
                mock.patch.object(attendance_push.requests, "post") as post:
            post.return_value = mock.Mock(status_code=200, text="")
            res = self.post(self.payload([moved], version=2, based_on=1))
        self.assertEqual(res.status_code, 201, res.content)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"], {"staff_number": "STF/0001", "unit_codes": ["COSC 103 GR A"]})


@override_settings(GENERATOR_API_KEY=KEY, ATTENDANCE_BASE_URL="", ATTENDANCE_API_KEY="")
class GeneratorLecturerAndTermTests(PublishCase):
    """The Generator's lecturers reach the slots by SMARTTT's own rules, and its term becomes current when due."""

    def lecturer(self, staff_number, first, last):
        user = User.objects.create_user(
            username=staff_number, password="x", role=User.Role.LECTURER,
            university_id=staff_number, first_name=first, last_name=last,
        )
        return Lecturer.objects.create(user=user, department=self.cs)

    def test_links_the_generators_lecturer_by_staff_number_and_attendance_sees_the_class(self):
        peter = self.lecturer("STF/0001", "Peter", "Kamami")
        res = self.post(self.payload([self.session(lecturer_staff_number="stf/0001", lecturer_name="Peter Kamami")]))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["lecturers"], {"assigned": 1, "unmatched": [], "left_to_allocation": 0})

        slot = TimetableSlot.objects.get()
        self.assertEqual((slot.lecturer, slot.lecturer_name_text, slot.allocation_document), (peter, "Peter Kamami", None))
        # What Smart Attendance's sync reads for the lecturer.
        units = get_lecturer_units("STF/0001").units
        self.assertEqual([u["code"] for u in units], ["COSC 103 GR A"])

    def test_falls_back_to_the_name_and_keeps_an_unknown_lecturers_name(self):
        jane = self.lecturer("STF/0002", "Jane", "Otieno")
        known = self.session(lecturer_staff_number="STF/9999", lecturer_name="Dr. Jane Otieno")
        unknown = self.session("COSC103-GRB-1", group_label="GR B", start_time="14:00", end_time="16:00", lecturer_staff_number="STF/0404", lecturer_name="Nobody Here")
        res = self.post(self.payload([known, unknown]))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.data["lecturers"]["assigned"], res.data["lecturers"]["unmatched"]), (1, ["STF/0404"]))
        a = TimetableSlot.objects.get(class_group="GR_A")
        b = TimetableSlot.objects.get(class_group="GR_B")
        self.assertEqual((a.lecturer, a.lecturer_name_text), (jane, "Dr. Jane Otieno"))
        self.assertEqual((b.lecturer, b.lecturer_name_text), (None, "Nobody Here"))

    def test_a_departments_allocation_document_wins(self):
        self.lecturer("STF/0001", "Peter", "Kamami")
        jane = self.lecturer("STF/0002", "Jane", "Otieno")
        AllocationDocument.objects.create(
            source="Computer Science", academic_year="2026/2027", file_name="cs.docx",
            rows=[{"unit_code": "COSC103", "raw_unit_code": "COSC 103", "lecturer_name": "Jane Otieno", "placeholder": False,
                   "group": "", "subgroups": [], "group_combinations": [], "year_of_study": 1, "semester": 1,
                   "odel": False, "section": "", "programme": "BACHELOR OF SCIENCE IN COMPUTER SCIENCE", "source_file": "cs.docx"}],
        )
        generator_says = self.session(lecturer_staff_number="STF/0001", lecturer_name="Peter Kamami")
        self.assertEqual(self.post(self.payload([generator_says])).status_code, 201)
        slot = TimetableSlot.objects.get()
        self.assertEqual((slot.lecturer, slot.lecturer_name_text), (jane, "Jane Otieno"))
        self.assertIsNotNone(slot.allocation_document_id)

        # A later version leaves the document's slot alone.
        res = self.post(self.payload([generator_says], version=2, based_on=1))
        self.assertEqual(res.data["lecturers"], {"assigned": 0, "unmatched": [], "left_to_allocation": 1})
        self.assertEqual(TimetableSlot.objects.get().lecturer, jane)

    def test_a_session_without_a_lecturer_leaves_the_slots_lecturer_alone(self):
        self.post(self.payload([self.session()]))
        by_hand = self.lecturer("STF/0003", "Hand", "Set")
        TimetableSlot.objects.update(lecturer=by_hand, lecturer_name_text="Hand Set")
        res = self.post(self.payload([self.session(lecturer_staff_number=None, lecturer_name="")], version=2, based_on=1))
        self.assertEqual(res.data["lecturers"]["assigned"], 0)
        self.assertEqual(TimetableSlot.objects.get().lecturer, by_hand)

    @override_settings(ATTENDANCE_BASE_URL="https://attendance.test.local", ATTENDANCE_API_KEY="att-key")
    def test_tells_attendance_about_the_lecturer_losing_and_the_one_gaining_a_class(self):
        self.lecturer("STF/0001", "Peter", "Kamami")
        self.lecturer("STF/0002", "Jane", "Otieno")
        with mock.patch.object(attendance_push.threading, "Thread", InlineThread), \
                mock.patch.object(attendance_push.requests, "post") as post:
            post.return_value = mock.Mock(status_code=200, text="")
            self.post(self.payload([self.session(lecturer_staff_number="STF/0001")]))
            self.assertEqual([c.kwargs["json"]["staff_number"] for c in post.call_args_list], ["STF/0001"])
            post.reset_mock()
            self.post(self.payload([self.session(lecturer_staff_number="STF/0002")], version=2, based_on=1))
        self.assertEqual(sorted(c.kwargs["json"]["staff_number"] for c in post.call_args_list), ["STF/0001", "STF/0002"])

    def test_the_term_becomes_current_when_none_is(self):
        res = self.post(self.payload([self.session()], term_start="2020-01-06", term_end="2020-04-30"))
        self.assertEqual((res.data["is_current"], res.data["made_current"]), (True, True))
        self.assertTrue(AcademicTerm.objects.get().is_current)

    def test_the_term_takes_over_when_today_is_within_its_dates(self):
        old = AcademicTerm.objects.create(academic_year="2025/2026", semester=3, start_date=date(2026, 5, 4), end_date=date(2026, 8, 21), is_current=True)
        today = date(2026, 10, 24)
        with mock.patch("apps.integrations.generator_publish.timezone.localdate", return_value=today):
            res = self.post(self.payload([self.session()]))  # 2026-09-07 .. 2026-12-18
        self.assertTrue(res.data["made_current"])
        old.refresh_from_db()
        self.assertFalse(old.is_current)
        self.assertEqual(AcademicTerm.objects.filter(is_current=True).count(), 1)

    def test_a_term_published_ahead_of_time_waits_for_the_administrator(self):
        current = AcademicTerm.objects.create(academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18), is_current=True)
        with mock.patch("apps.integrations.generator_publish.timezone.localdate", return_value=date(2026, 10, 24)):
            res = self.post(self.payload([self.session()], semester=2, term_start="2027-01-04", term_end="2027-04-30"))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.data["is_current"], res.data["made_current"]), (False, False))
        current.refresh_from_db()
        self.assertTrue(current.is_current)
