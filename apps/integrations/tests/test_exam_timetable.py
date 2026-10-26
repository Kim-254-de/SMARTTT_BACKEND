"""The exam timetable: the Generator publishes it, the Director switches the term to exams, students and lecturers see it."""

import copy
from datetime import date, datetime, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.departments.models import Department
from apps.integrations import attendance_push
from apps.integrations.exam_mode import apply_due, close_for_next_teaching
from apps.integrations.exam_notifications import send_exam_reminders
from apps.lecturers.models import Lecturer
from apps.notifications.models import StudentNotification
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.students.models import Student
from apps.timetable.models import AcademicTerm, ExamModeChange, ExamPublication
from apps.units.models import Unit

KEY = "test-generator-key"
BASE = "/api/v1/integrations/generator"
MONDAY = date(2026, 11, 23)


class InlineThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@override_settings(GENERATOR_API_KEY=KEY, ATTENDANCE_BASE_URL="", ATTENDANCE_API_KEY="")
class ExamCase(APITestCase):
    def setUp(self):
        self.cs = Department.objects.create(name="Computer Science", code="CS")
        self.bsc = Program.objects.create(department=self.cs, code="BSC.CS", name="BSc Computer Science")
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18), is_current=True
        )
        for code, capacity in (("UTC 1", 300), ("STB 1", 120), ("STB 2", 120)):
            Room.objects.create(code=code, name=code, building=code.split()[0], capacity=capacity)
        # Four first-years; the paper splits them two and two by registration number.
        self.students = [self._student(f"CS/{n:04d}/26", f"s{n}@students.tharaka.ac.ke") for n in (4, 1, 3, 2)]
        self.jane = self._lecturer("STF/0001", "jane")
        self.tom = self._lecturer("STF/0002", "tom")
        self.sam = self._lecturer("STF/0003", "sam")

    def _student(self, reg, email, year=1, units=("COSC 130", "COSC 200"), **extra):
        user = User.objects.create_user(username=email, email=email, password="x", role=User.Role.STUDENT, university_id=reg)
        student = Student.objects.create(
            user=user, registration_number=reg, program=self.bsc, department=self.cs, admission_year=2026,
            first_name="S", last_name=reg, email=email, current_study_year=year, current_semester=1, **extra,
        )
        self.sync(student, *units)
        return student

    def sync(self, student, *codes):
        """The units the student synced this term: only their exams show."""
        for code in codes:
            unit, _ = Unit.objects.get_or_create(code=code, defaults={"department": self.cs, "name": code, "credit_hours": 3})
            StudentUnit.objects.get_or_create(user=student.user, unit=unit, term=self.term)

    def _lecturer(self, staff, name):
        user = User.objects.create_user(
            username=f"{name}@tharaka.ac.ke", email=f"{name}@tharaka.ac.ke", password="x",
            role=User.Role.LECTURER, university_id=staff, first_name=name.title(), last_name="L",
        )
        Lecturer.objects.create(user=user, department=self.cs, rank="Dr.")
        return user

    ROW = {"program": "BSC.CS", "year_of_study": 1, "study_semester": 1, "stream": ""}

    def paper(self, key="p-130", day=MONDAY, start="08:30", end="10:30", seating=None, **over):
        p = {
            "key": key,
            "unit_codes": ["BITE 131", "COSC 130"],
            "title": "Programming",
            "date": day.isoformat(),
            "start_time": start,
            "end_time": end,
            "examiner_staff_number": "STF/0001",
            "seating": seating
            or [
                {"room_code": "STB 1", "class_rows": [self.ROW], "part": 1, "parts": 2, "students": 2,
                 "invigilator_staff_number": "STF/0001", "role": "main"},
                {"room_code": "STB 2", "class_rows": [self.ROW], "part": 2, "parts": 2, "students": 2,
                 "invigilator_staff_number": "STF/0002", "role": "extra"},
            ],
        }
        p.update(over)
        return p

    def payload(self, papers=None, version=1, based_on=None, **over):
        p = {
            "term_id": str(self.term.pk),
            "version": version,
            "based_on_version": based_on,
            "published_by": "Dee Director (STF/0900)",
            "exam_start": MONDAY.isoformat(),
            "exam_end": (MONDAY + timedelta(days=11)).isoformat(),
            "papers": papers or [self.paper()],
            "practicals": [
                {"unit_codes": ["COSC 200"], "title": "Data", "date": "2026-11-20", "start_time": "09:00", "end_time": "11:00"}
            ],
        }
        p.update(over)
        return p

    def publish(self, payload, key=KEY):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"{BASE}/exam-publish/", payload, format="json", HTTP_X_API_KEY=key)

    def act(self, path, method="post", **body):
        with self.captureOnCommitCallbacks(execute=True):
            if method == "delete":
                return self.client.delete(f"{BASE}/{path}/?term={self.term.pk}&by=Dee", HTTP_X_API_KEY=KEY)
            return self.client.post(f"{BASE}/{path}/", {"term_id": str(self.term.pk), **body}, format="json", HTTP_X_API_KEY=KEY)


class ExamPublishTests(ExamCase):
    def test_needs_the_generators_key(self):
        self.assertEqual(self.publish(self.payload(), key="wrong").status_code, 403)
        with override_settings(GENERATOR_API_KEY=""):
            self.assertEqual(self.publish(self.payload(), key="").status_code, 403)

    def test_publish_and_send_again(self):
        res = self.publish(self.payload())
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["papers"], 1)
        self.assertEqual(res.data["changes"]["added"], ["p-130"])
        again = self.publish(self.payload())
        self.assertEqual(again.status_code, 200)
        self.assertEqual(ExamPublication.objects.count(), 1)
        other = self.publish(self.payload([self.paper(start="11:30", end="13:30")]))
        self.assertEqual((other.status_code, other.data["code"]), (409, "version_taken"))
        stale = self.publish(self.payload(version=2, based_on=None))
        self.assertEqual((stale.status_code, stale.data["code"]), (409, "stale_base"))

    def test_validation_lists_the_problems(self):
        bad = [
            self.paper("p-1", start="09:00", end="11:00"),  # not a session
            self.paper("p-2", day=date(2026, 11, 28)),  # a Saturday
            self.paper("p-3", day=date(2027, 1, 4)),  # outside the period
            self.paper(
                "p-4",
                day=MONDAY + timedelta(days=1),
                seating=[  # two mains, and STB 1 over its 120 seats
                    {"room_code": "STB 1", "class_rows": [self.ROW], "students": 121, "invigilator_staff_number": "STF/0001", "role": "main"},
                    {"room_code": "STB 2", "class_rows": [self.ROW], "students": 2, "invigilator_staff_number": "STF/0002", "role": "main"},
                ],
            ),
            self.paper(  # STF/0003 in two rooms at once
                "p-5",
                day=MONDAY + timedelta(days=2),
                seating=[
                    {"room_code": "STB 1", "class_rows": [self.ROW], "students": 2, "invigilator_staff_number": "STF/0003", "role": "main"},
                    {"room_code": "STB 2", "class_rows": [self.ROW], "students": 2, "invigilator_staff_number": "STF/0003", "role": "extra"},
                ],
            ),
        ]
        res = self.publish(self.payload(bad))
        self.assertEqual((res.status_code, res.data["code"]), (422, "invalid"))
        text = " ".join(res.data["problems"])
        for expected in ("not one of the exam sessions", "Saturday", "outside the exam period",
                         "exactly one main invigilator", "121 on", "STF/0003 invigilates in 2 rooms"):
            self.assertIn(expected, text)
        self.assertFalse(ExamPublication.objects.exists())

    def test_unknown_staff_numbers_and_rooms_are_named(self):
        seating = copy.deepcopy(self.paper()["seating"])
        seating[1]["invigilator_staff_number"] = "STF/9999"
        res = self.publish(self.payload([self.paper(seating=seating)]))
        self.assertEqual((res.status_code, res.data["code"], res.data["staff_numbers"]), (422, "unknown_lecturer", ["STF/9999"]))
        seating = copy.deepcopy(self.paper()["seating"])
        seating[0]["room_code"] = "NEW 1"
        res = self.publish(self.payload([self.paper(seating=seating)]))
        self.assertEqual((res.status_code, res.data["code"]), (422, "unknown_room"))
        # A room sent with its capacity is created.
        res = self.publish(self.payload([self.paper(seating=seating)], rooms=[{"code": "NEW 1", "capacity": 50, "exam_seats": 45}]))
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(Room.objects.filter(code="NEW 1", capacity=50).exists())


class StudentAndLecturerTests(ExamCase):
    def test_each_student_gets_their_own_room_split_by_registration_number(self):
        self.assertEqual(self.publish(self.payload()).status_code, 201)
        rooms = {}
        for student in self.students:
            self.client.force_authenticate(student.user)
            body = self.client.get("/api/v1/exams/my/").data
            [paper] = body["papers"]
            self.assertEqual((paper["codes"], paper["start_time"]), ("BITE 131/COSC 130", "08:30"))
            rooms[student.registration_number] = paper["room"]
            self.assertEqual(body["practicals"][0]["unit_codes"], ["COSC 200"])
        # Registration numbers in order: the first two in part 1 (STB 1), the next two in part 2.
        self.assertEqual(
            rooms, {"CS/0001/26": "STB 1", "CS/0002/26": "STB 1", "CS/0003/26": "STB 2", "CS/0004/26": "STB 2"}
        )

    def test_a_registration_range_sent_by_the_generator_wins(self):
        seating = copy.deepcopy(self.paper()["seating"])
        seating[0].update(reg_from="CS/0003/26", reg_to="CS/0004/26")
        seating[1].update(reg_from="CS/0001/26", reg_to="CS/0002/26")
        self.publish(self.payload([self.paper(seating=seating)]))
        self.client.force_authenticate(self.students[1].user)  # CS/0001/26
        self.assertEqual(self.client.get("/api/v1/exams/my/").data["papers"][0]["room"], "STB 2")

    def test_only_synced_units_show(self):
        self.publish(self.payload())
        other = self._student("CS/0100/26", "x@students.tharaka.ac.ke", units=("MATH 101",))
        self.client.force_authenticate(other.user)
        body = self.client.get("/api/v1/exams/my/").data
        self.assertEqual((body["papers"], body["practicals"]), ([], []))

    def test_a_synced_unit_whose_class_row_isnt_seated_shows_without_a_room(self):
        self.publish(self.payload())
        other = self._student("CS/0100/25", "x@students.tharaka.ac.ke", year=2, units=("COSC 130",))
        self.client.force_authenticate(other.user)
        [paper] = self.client.get("/api/v1/exams/my/").data["papers"]
        self.assertEqual((paper["units"], paper["room"], paper["room_confirmed"]), (["COSC 130"], None, False))

    def test_odel_students_get_the_odel_paper(self):
        odel_row = {"program": "BSC.CS", "year_of_study": 2, "study_semester": 1, "stream": "ODEL"}
        odel = self.paper(
            key="p-130-odel", start="14:30", end="16:30", sitting="odel",
            seating=[{"room_code": "UTC 1", "class_rows": [odel_row], "students": 1,
                      "invigilator_staff_number": "STF/0003", "role": "main"}],
        )
        self.assertEqual(self.publish(self.payload([self.paper(), odel])).status_code, 201)
        # Seated by class row: the ODEL stream gets the ODEL paper.
        seated = self._student("CS/0200/25", "o@students.tharaka.ac.ke", year=2, units=("COSC 130",), timetable_group="ODEL")
        self.client.force_authenticate(seated.user)
        [paper] = self.client.get("/api/v1/exams/my/").data["papers"]
        self.assertEqual((paper["sitting"], paper["room"]), ("odel", "UTC 1"))
        # Seated nowhere: the enrollment decides (part-time and distance learning sit the ODEL paper).
        part_time = self._student(
            "CS/0300/24", "p@students.tharaka.ac.ke", year=3, units=("COSC 130",),
            enrollment_type=Student.EnrollmentType.PART_TIME,
        )
        self.client.force_authenticate(part_time.user)
        [paper] = self.client.get("/api/v1/exams/my/").data["papers"]
        self.assertEqual((paper["sitting"], paper["room_confirmed"]), ("odel", False))
        # The regular students still get the regular paper only.
        self.client.force_authenticate(self.students[0].user)
        [paper] = self.client.get("/api/v1/exams/my/").data["papers"]
        self.assertEqual(paper["sitting"], "regular")

    def test_the_lecturer_gets_their_duties(self):
        self.publish(self.payload())
        self.client.force_authenticate(self.jane)
        body = self.client.get("/api/v1/exams/my-duties/").data
        self.assertEqual([p["codes"] for p in body["examiner"]], ["BITE 131/COSC 130"])
        [duty] = body["duties"]
        self.assertEqual((duty["role"], duty["room"], duty["collect_from"]), ("main", "STB 1", ["STB 2"]))
        self.client.force_authenticate(self.tom)
        [duty] = self.client.get("/api/v1/exams/my-duties/").data["duties"]
        self.assertEqual((duty["role"], duty["room"]), ("extra", "STB 2"))
        self.assertNotIn("collect_from", duty)


class ExamModeTests(ExamCase):
    def soon(self, minutes=60):
        return (timezone.now() + timedelta(minutes=minutes)).isoformat()

    def test_switch_refused_without_an_exam_publication(self):
        res = self.act("exam-switch", now=True)
        self.assertEqual((res.status_code, res.data["code"]), (409, "no_exam_publication"))

    def test_schedule_move_cancel_and_now(self):
        self.publish(self.payload())
        first = self.soon(60)
        res = self.act("exam-switch", at=first, by="Dee")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.data["mode"], res.data["exam_switch_at"] is not None), ("teaching", True))
        moved = self.act("exam-switch", at=self.soon(120), by="Dee")
        self.assertNotEqual(moved.data["exam_switch_at"], res.data["exam_switch_at"])
        self.assertEqual(self.act("exam-switch", at="2020-01-01T00:00:00Z").data["code"], "in_the_past")
        self.assertIsNone(self.act("exam-switch", method="delete").data["exam_switch_at"])
        now = self.act("exam-switch", now=True, by="Dee")
        self.assertEqual((now.data["mode"], now.data["switched_by"]), ("exams", "Dee"))
        late = self.act("exam-switch", method="delete")
        self.assertEqual((late.status_code, late.data["code"]), (409, "already_switched"))
        actions = list(ExamModeChange.objects.order_by("created_at").values_list("action", flat=True))
        self.assertEqual(actions, ["schedule_switch", "schedule_switch", "cancel_switch", "switch_now"])
        self.assertEqual(ExamModeChange.objects.last().before["mode"], "teaching")

    def test_the_scheduled_switch_fires_once_and_close_follows(self):
        self.publish(self.payload())
        self.act("exam-switch", at=self.soon(5), by="Dee")
        self.assertEqual(apply_due(timezone.now()), {"switched": [], "closed": []})  # not yet
        later = timezone.now() + timedelta(minutes=10)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(len(apply_due(later)["switched"]), 1)
        self.assertEqual(apply_due(later), {"switched": [], "closed": []})  # safe to run again
        self.term.refresh_from_db()
        self.assertEqual((self.term.mode, self.term.switched_by), ("exams", "Dee (scheduled)"))
        # Close scheduled, then due; the command applies it.
        self.term.exam_close_at = timezone.now() - timedelta(minutes=1)
        self.term.save()
        call_command("apply_exam_mode", stdout=mock.MagicMock())
        self.term.refresh_from_db()
        self.assertEqual((self.term.mode, self.term.closed_by), ("teaching", "Timetable Generator (scheduled)"))

    def test_close_now_and_scheduled(self):
        self.publish(self.payload())
        self.assertEqual(self.act("exam-close", now=True).data["code"], "not_switched")
        self.act("exam-switch", now=True)
        scheduled = self.act("exam-close", at=self.soon(600))
        self.assertIsNotNone(scheduled.data["exam_close_at"])
        self.assertIsNone(self.act("exam-close", method="delete").data["exam_close_at"])
        closed = self.act("exam-close", now=True, by="Dee")
        self.assertEqual((closed.data["mode"], closed.data["closed_by"]), ("teaching", "Dee"))

    def test_teaching_is_hidden_in_exam_mode_and_back_after_close(self):
        self.publish(self.payload())
        self.client.force_authenticate(self.students[0].user)
        self.assertEqual(self.client.get("/api/v1/terms/current/").data["mode"], "teaching")
        self.act("exam-switch", now=True)
        schedule = self.client.get("/api/v1/schedule/me/").data
        self.assertEqual((schedule["mode"], schedule["summary"]["message"]), ("exams", "Exams are on: see your exam timetable."))
        self.assertEqual(self.client.get("/api/v1/terms/current/").data["mode"], "exams")
        self.act("exam-close", now=True)
        self.assertEqual(self.client.get("/api/v1/schedule/me/").data.get("mode"), "teaching")

    def test_next_terms_teaching_closes_the_exam_period(self):
        self.publish(self.payload())
        self.act("exam-switch", now=True)
        nxt = AcademicTerm.objects.create(academic_year="2026/2027", semester=2, start_date=date(2027, 1, 4), end_date=date(2027, 4, 16))
        self.assertEqual(close_for_next_teaching(nxt), [str(self.term)])
        self.term.refresh_from_db()
        self.assertEqual(self.term.mode, "teaching")


class NotificationTests(ExamCase):
    def test_the_switch_tells_everyone_with_an_exam(self):
        self.publish(self.payload())
        self.act("exam-switch", now=True)
        told = set(StudentNotification.objects.values_list("user__university_id", flat=True))
        self.assertEqual(told, {s.registration_number for s in self.students} | {"STF/0001", "STF/0002"})

    def test_changes_reach_only_the_people_affected(self):
        self.publish(self.payload())
        self.act("exam-switch", now=True)
        StudentNotification.objects.all().delete()
        seating = copy.deepcopy(self.paper()["seating"])
        seating[1]["room_code"] = "UTC 1"  # part 2 moves room
        seating[1]["invigilator_staff_number"] = "STF/0003"  # and gets another invigilator
        res = self.publish(self.payload([self.paper(seating=seating)], version=2, based_on=1))
        self.assertEqual(res.data["changes"]["rooms_changed"], ["p-130"])
        told = set(StudentNotification.objects.values_list("user__university_id", flat=True))
        # The two students who moved, the invigilator taken off and the one put on; not the others.
        self.assertEqual(told, {"CS/0003/26", "CS/0004/26", "STF/0002", "STF/0003"})

    def test_reminders_the_evening_before_and_an_hour_before(self):
        self.publish(self.payload())
        self.act("exam-switch", now=True)
        StudentNotification.objects.all().delete()
        tz = timezone.get_current_timezone()
        evening = timezone.make_aware(datetime.combine(MONDAY - timedelta(days=1), datetime.min.time()).replace(hour=19), tz)
        sent = send_exam_reminders(evening)
        self.assertEqual(sent, 4 + 2)  # four students and two invigilators
        self.assertEqual(send_exam_reminders(evening), 0)  # once only
        hour = timezone.make_aware(datetime.combine(MONDAY, datetime.min.time()).replace(hour=7, minute=45), tz)
        self.assertEqual(send_exam_reminders(hour), 6)
        messages = StudentNotification.objects.filter(user=self.students[0].user).values_list("notification__message", flat=True)
        self.assertTrue(any("in STB 2" in m for m in messages))


@override_settings(GENERATOR_API_KEY=KEY, ATTENDANCE_BASE_URL="http://attendance.test", ATTENDANCE_API_KEY="att-key")
class AttendancePushTests(ExamCase):
    def test_the_switch_sends_the_mode_and_the_exam_sessions(self):
        self.publish(self.payload())
        with mock.patch.object(attendance_push.threading, "Thread", InlineThread), mock.patch.object(
            attendance_push.requests, "post", return_value=mock.Mock(status_code=200)
        ) as post:
            self.act("exam-switch", now=True)
        urls = [c.args[0] for c in post.call_args_list]
        self.assertIn("http://attendance.test/api/v1/integrations/smarttt/term-mode", urls)
        self.assertIn("http://attendance.test/api/v1/integrations/smarttt/exam-sessions", urls)
        sessions = next(c.kwargs["json"] for c in post.call_args_list if c.args[0].endswith("exam-sessions"))["sessions"]
        self.assertEqual([(s["room"], s["role"]) for s in sessions], [("STB 1", "main"), ("STB 2", "extra")])
        self.assertEqual(sessions[0]["candidates"][0]["reg_from"], "CS/0001/26")
        self.assertEqual(sessions[1]["candidates"][0]["reg_to"], "CS/0004/26")
        self.assertEqual(sessions[1]["main_invigilator_staff_number"], "STF/0001")
        self.assertEqual(sessions[0]["registration_numbers"], ["CS/0001/26", "CS/0002/26"])
        self.assertEqual(sessions[1]["registration_numbers"], ["CS/0003/26", "CS/0004/26"])
