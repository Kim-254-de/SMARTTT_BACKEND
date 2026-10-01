from datetime import date, time
from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.departments.models import Department, Faculty
from apps.integrations import attendance_push
from apps.lecturers.models import Lecturer
from apps.rooms.models import Room
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.units.models import Unit

KEY = "test-attendance-key"
BASE = "https://attendance.test.local"
PUSH_URL = BASE + "/api/v1/integrations/smarttt/timetable-changes"


class InlineThread:
    """Runs the push on the test's own thread, so its effect can be asserted."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@override_settings(ATTENDANCE_API_KEY=KEY, ATTENDANCE_BASE_URL=BASE)
@mock.patch.object(attendance_push.threading, "Thread", InlineThread)
@mock.patch.object(attendance_push.requests, "post")
class AttendancePushOnRescheduleTests(APITestCase):
    def setUp(self):
        faculty = Faculty.objects.create(name="Science", code="FSC")
        dept = Department.objects.create(faculty=faculty, name="Computer Science", code="CS")
        self.room = Room.objects.create(code="LH1", name="Lecture Hall 1", building="Main", capacity=100)
        self.lab = Room.objects.create(code="LAB2", name="Lab 2", building="Main", capacity=40)
        term = AcademicTerm.objects.create(
            academic_year="2025/2026", semester=1, start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20), is_current=True,
        )
        unit = Unit.objects.create(code="COSC 103", name="Computer Applications", credit_hours=3, department=dept)
        self.user = User.objects.create_user(
            username="pkamami", password="x", role=User.Role.LECTURER,
            university_id="stf/0001", first_name="Peter", last_name="Kamami",
        )
        lecturer = Lecturer.objects.create(user=self.user, department=dept)
        self.slot = TimetableSlot.objects.create(
            term=term, unit=unit, room=self.room, day_of_week="mon",
            start_time=time(8, 0), end_time=time(10, 0), lecturer=lecturer, class_group="GR_A",
        )
        self.client.force_authenticate(self.user)

    def _reschedule(self, **data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/v1/timetable/slots/{self.slot.id}/reschedule/", data, format="json")

    def test_tells_the_attendance_backend_which_lecturer_and_class_moved(self, post):
        post.return_value = mock.Mock(status_code=200, text="")
        res = self._reschedule(day_of_week="wed", start_time="14:00", end_time="16:00", room=str(self.lab.id))
        self.assertEqual(res.status_code, 200, res.content)

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], PUSH_URL)
        self.assertEqual(kwargs["json"], {"staff_number": "STF/0001", "unit_codes": ["COSC 103 GR A"]})
        self.assertEqual(kwargs["headers"], {"X-API-Key": KEY})
        self.assertGreater(kwargs["timeout"], 0)

    def test_a_failed_push_never_fails_the_reschedule(self, post):
        post.side_effect = attendance_push.requests.ConnectionError("asleep")
        res = self._reschedule(start_time="09:00", end_time="11:00")
        self.assertEqual(res.status_code, 200, res.content)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.start_time, time(9, 0))

    @override_settings(ATTENDANCE_BASE_URL="")
    def test_off_when_the_attendance_backend_is_not_configured(self, post):
        res = self._reschedule(day_of_week="fri")
        self.assertEqual(res.status_code, 200, res.content)
        post.assert_not_called()

    def test_nothing_is_pushed_when_the_reschedule_is_refused(self, post):
        res = self._reschedule(start_time="12:00", end_time="11:00")
        self.assertEqual(res.status_code, 400)
        post.assert_not_called()

    def test_a_slot_with_no_linked_lecturer_still_names_the_class(self, post):
        self.slot.lecturer = None
        self.slot.class_group = ""
        self.assertEqual(
            attendance_push.timetable_change_payload(self.slot),
            {"staff_number": None, "unit_codes": ["COSC 103"]},
        )
