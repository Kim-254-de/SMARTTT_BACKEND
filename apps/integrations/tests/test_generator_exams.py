from datetime import date

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.courses.models import StudentUnit
from apps.departments.models import Department
from apps.programs.models import Program
from apps.students.models import Student
from apps.timetable.models import AcademicTerm, ExamTimetable
from apps.units.models import Unit

KEY = "test-generator-key"
URL = "/api/v1/integrations/generator/exams/publish/"
MINE = "/api/v1/schedule/exams/me/"


def seat(room, row="BSC.CS Y1S1", program_code="BSC.CS", year=1, stream="", part=1, parts=1, students=120):
    return {
        "room_code": room, "class_row": row, "program_id": None, "program_code": program_code,
        "year_of_study": year, "study_semester": 1, "stream": stream, "part": part, "parts": parts,
        "students": students, "invigilator_staff_number": "STF/0002",
    }


def paper(key, codes, day, seating, start="08:30", end="10:30"):
    return {
        "key": key, "codes": codes, "title": f"Paper {key}", "date": day, "start_time": start, "end_time": end,
        "examiner_staff_number": "stf/0001", "seating": seating,
    }


def payload(papers, version=1, based_on=None, practicals=None, **over):
    p = {
        "term_id": None, "academic_year": "2026/2027", "semester": 1,
        "term_start": "2026-09-07", "term_end": "2026-12-18",
        "version": version, "based_on_version": based_on, "published_by": "Dee Director (STF/0900)",
        "papers": papers, "practicals": practicals or [],
    }
    p.update(over)
    return p


PAPERS = [
    # Shared paper: the student synced COSC 130 (spelt without a space here).
    paper("p-shared", ["BITE 131", "COSC130"], "2026-11-23", [seat("STB 1"), seat("UTC 1", "BED.SCI Y1S1", "BED.SCI")]),
    # Their class row split over two rooms: the room can't be told.
    paper("p-200", ["COSC 200"], "2026-11-24", [seat("STB 1", part=1, parts=2), seat("STB 2", part=2, parts=2)]),
    # Not one of their units.
    paper("p-301", ["COSC 301"], "2026-11-25", [seat("ADM 1", "BSC.CS Y3S1", year=3)]),
    # Their unit, but no seating for their class row: every room shown.
    paper("p-epsc", ["EPSC 121"], "2026-11-27", [seat("UTC 1", "BED.ARTS Y2S1", "BED.ARTS", year=2)], "14:30", "16:30"),
]
PRACTICALS = [
    {"codes": ["COSC 200"], "title": "Data", "department": "CS", "date": "2026-11-20", "start_time": "09:00", "end_time": "11:00"},
    {"codes": ["COSC 301"], "title": "Networks", "department": "CS", "date": "2026-11-21", "start_time": "09:00", "end_time": "11:00"},
]


@override_settings(GENERATOR_API_KEY=KEY)
class GeneratorExamPublishTests(APITestCase):
    def post(self, body, key=KEY):
        return self.client.post(URL, body, format="json", HTTP_X_API_KEY=key)

    def test_needs_the_generators_key(self):
        self.assertEqual(self.post(payload(PAPERS), key="wrong").status_code, 403)

    def test_publishes_a_version_with_papers_seating_and_practicals(self):
        res = self.post(payload(PAPERS, practicals=PRACTICALS))
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual((body["paper_count"], body["seating_count"], body["practical_count"]), (4, 6, 2))
        timetable = ExamTimetable.objects.get()
        shared = timetable.papers.get(key="p-shared")
        self.assertEqual(shared.code_keys, ["BITE131", "COSC130"])
        self.assertEqual(shared.examiner_staff_number, "STF/0001")
        self.assertEqual(shared.seating.get(room_code="STB 1").program_code, "BSC.CS")
        # The term was created from its dates.
        self.assertEqual(str(timetable.term), "2026/2027 S1")

    def test_versions_only_go_up(self):
        self.assertEqual(self.post(payload(PAPERS)).status_code, 201)
        self.assertEqual(self.post(payload(PAPERS)).status_code, 200)  # the same version again
        self.assertEqual(self.post(payload(PAPERS[:2])).json()["code"], "version_taken")
        self.assertEqual(self.post(payload(PAPERS, version=2)).json()["code"], "stale_base")
        self.assertEqual(self.post(payload(PAPERS[:2], version=2, based_on=1)).status_code, 201)
        self.assertEqual(ExamTimetable.objects.count(), 2)

    def test_old_seating_with_only_a_label_is_taken(self):
        old = paper("p-old", ["COSC 400"], "2026-11-23", [{"room_code": "STB 1", "class_row": "BSC.CS Y4S1",
                                                          "part": 1, "parts": 1, "students": 40}])
        self.assertEqual(self.post(payload([old])).status_code, 201)

    def test_refuses_a_paper_that_ends_before_it_starts(self):
        res = self.post(payload([paper("p", ["COSC 1"], "2026-11-23", [], "10:30", "08:30")]))
        self.assertEqual((res.status_code, res.json()["code"]), (422, "invalid_exam_timetable"))
        self.assertFalse(ExamTimetable.objects.exists())


@override_settings(GENERATOR_API_KEY=KEY)
class StudentExamsTests(APITestCase):
    def setUp(self):
        self.term = AcademicTerm.objects.create(
            academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18), is_current=True
        )
        cs = Department.objects.create(name="Computer Science", code="CS")
        self.program = Program.objects.create(department=cs, code="BSC.CS", name="BSc Computer Science")
        self.user = User.objects.create_user(
            username="s@example.com", email="s@example.com", password="secret123",
            role=User.Role.STUDENT, university_id="U-001", first_name="Sam", last_name="Student",
        )
        Student.objects.create(
            user=self.user, registration_number="CS/001/26", first_name="Sam", last_name="Student",
            email=self.user.email, department=cs, program=self.program, admission_year=2026,
            current_study_year=1, current_semester=1,
        )
        for code in ("COSC 130", "COSC 200", "EPSC 121", "MATH 101"):
            unit = Unit.objects.create(code=code, name=code, credit_hours=3, department=cs)
            StudentUnit.objects.create(user=self.user, unit=unit, term=self.term)
        self.client.force_authenticate(self.user)

    def publish(self, papers=PAPERS, **over):
        res = self.client.post(URL, payload(papers, term_id=str(self.term.pk), practicals=PRACTICALS, **over),
                               format="json", HTTP_X_API_KEY=KEY)
        self.assertIn(res.status_code, (200, 201), res.content)

    def test_nothing_published_yet(self):
        body = self.client.get(MINE).json()
        self.assertEqual(body["papers"], [])
        self.assertIn("hasn't been published", body["summary"]["message"])

    def test_only_the_papers_and_practicals_of_synced_units(self):
        self.publish()
        body = self.client.get(MINE).json()
        self.assertEqual([p["codes"] for p in body["papers"]], [["BITE 131", "COSC130"], ["COSC 200"], ["EPSC 121"]])
        self.assertEqual(body["papers"][0]["units"], ["COSC 130"])
        self.assertEqual([p["title"] for p in body["practicals"]], ["Data"])
        self.assertEqual(body["version"], 1)

    def test_their_own_room_when_it_can_be_told(self):
        self.publish()
        shared, split, unseated = self.client.get(MINE).json()["papers"]
        self.assertEqual([r["room"] for r in shared["rooms"]], ["STB 1"])
        self.assertTrue(shared["room_confirmed"])
        self.assertEqual([r["room"] for r in split["rooms"]], ["STB 1", "STB 2"])
        self.assertFalse(split["room_confirmed"])
        self.assertEqual([r["room"] for r in unseated["rooms"]], ["UTC 1"])
        self.assertFalse(unseated["room_confirmed"])

    def test_the_stream_narrows_the_room(self):
        self.user.student_profile.timetable_group = "2"
        self.user.student_profile.save()
        streams = [paper("p-200", ["COSC 200"], "2026-11-24", [seat("STB 1", stream="1"), seat("STB 2", stream="2")])]
        self.publish(streams)
        (only,) = self.client.get(MINE).json()["papers"]
        self.assertEqual(([r["room"] for r in only["rooms"]], only["room_confirmed"]), (["STB 2"], True))

    def test_the_latest_version_is_shown(self):
        self.publish()
        self.publish(PAPERS[:1], version=2, based_on_version=1)
        body = self.client.get(MINE).json()
        self.assertEqual((body["version"], len(body["papers"])), (2, 1))

    def test_no_synced_units(self):
        self.publish()
        StudentUnit.objects.all().delete()
        self.assertIn("Sync", self.client.get(MINE).json()["summary"]["message"])


@override_settings(GENERATOR_API_KEY=KEY)
class OdelPaperTests(StudentExamsTests):
    """A unit with a regular paper and a separate ODEL paper: each student sees the one they sit."""

    TWINS = [
        paper("p-200", ["COSC 200"], "2026-11-24", [seat("STB 1")]),
        {**paper("p-200-odel", ["COSC 200"], "2026-11-28", [seat("ODL 1", "BSC.CS Y1S1 (ODEL)", stream="ODEL")]),
         "sitting": "odel"},
    ]

    def test_the_regular_student_sees_the_regular_paper(self):
        self.publish(self.TWINS)
        (only,) = self.client.get(MINE).json()["papers"]
        self.assertEqual((only["date"], only["sitting"], only["rooms"][0]["room"]), ("2026-11-24", "regular", "STB 1"))

    def test_the_odel_student_sees_the_odel_paper(self):
        profile = self.user.student_profile
        profile.timetable_group = "ODEL"
        profile.save()
        self.publish(self.TWINS)
        (only,) = self.client.get(MINE).json()["papers"]
        self.assertEqual((only["date"], only["sitting"], only["rooms"][0]["room"]), ("2026-11-28", "odel", "ODL 1"))

    def test_by_enrollment_when_the_class_row_cant_be_told(self):
        profile = self.user.student_profile
        profile.program = Program.objects.create(department=profile.department, code="OTHER", name="Other")
        profile.enrollment_type = Student.EnrollmentType.DISTANCE_LEARNING
        profile.save()
        self.publish(self.TWINS)
        (only,) = self.client.get(MINE).json()["papers"]
        self.assertEqual(only["sitting"], "odel")
