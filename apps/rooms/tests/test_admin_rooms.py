"""The admin's venue table, reached through the acting-admin integration."""

from datetime import date, time
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.departments.models import Department
from apps.programs.models import Program
from apps.rooms.models import Room
from apps.rooms.serializers import RoomSerializer
from apps.rooms.services.room_import import import_rooms
from apps.rooms.services.room_merge import duplicate_groups, merge_all, room_key
from apps.timetable.models import AcademicTerm, TimetableSlot
from apps.units.models import Unit

KEY = "test-attendance-key"


@override_settings(ATTENDANCE_API_KEY=KEY, GENERATOR_API_KEY="gen")
class AdminRoomTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="adm", password="x", is_staff=True, role=User.Role.ADMIN, email="a@x.ke")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.room = Room.objects.create(code="TC 1", name="TC 1", building="TC", capacity=100)
        Room.objects.create(code="TBA", name="TBA", building="", capacity=1)

    def test_lists_adds_and_edits_venues(self):
        with mock.patch("apps.integrations.acting_admin.ActingAdminAuthentication.authenticate", return_value=(self.admin, None)):
            rooms = self.client.get(reverse("admin-rooms")).data["rooms"]
            self.assertEqual([(r["code"], r["for_exams"], r["health_unit"]) for r in rooms], [("TC 1", True, False)])

            made = self.client.post(
                reverse("admin-rooms"),
                {"code": "NURS 1", "name": "Nursing 1", "building": "Health Unit", "capacity": 60, "health_unit": True},
                format="json",
            )
            self.assertEqual(made.status_code, 201, made.content)
            room = Room.objects.get(code="NURS 1")
            self.assertTrue(room.health_unit and room.for_exams and room.capacity_confirmed)

            changed = self.client.patch(reverse("admin-room", args=[self.room.pk]), {"for_exams": False, "capacity": 80}, format="json")
            self.assertEqual(changed.status_code, 200, changed.content)
            self.room.refresh_from_db()
            self.assertEqual((self.room.for_exams, self.room.capacity), (False, 80))

            taken = self.client.post(reverse("admin-rooms"), {"code": "TC 1", "name": "x", "building": "TC", "capacity": 5}, format="json")
            self.assertEqual(taken.status_code, 400)

    def test_an_upload_without_those_columns_leaves_them_alone(self):
        self.room.for_exams = False
        self.room.health_unit = True
        self.room.save()
        result = import_rooms("v.csv", b"code,name,building,floor,capacity,type,status\nTC 1,TC 1,TC,,90,lecture hall,active\n")
        self.assertEqual(result["updated"], 1)
        self.room.refresh_from_db()
        self.assertEqual((self.room.capacity, self.room.for_exams, self.room.health_unit), (90, False, True))


class DuplicateRoomTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="CS", code="CS")
        self.program = Program.objects.create(department=self.dept, code="BSC", name="BSc")
        self.unit = Unit.objects.create(code="COSC 100", name="X", credit_hours=3, department=self.dept)
        self.term = AcademicTerm.objects.create(academic_year="2026/2027", semester=1, start_date=date(2026, 9, 7), end_date=date(2026, 12, 18), is_current=True)
        self.upload = Room.objects.create(code="TC 1", name="TC 1", building="", capacity=50)  # from a timetable upload
        self.file = Room.objects.create(code="TC1", name="Tuition 1", building="TC", capacity=100, capacity_confirmed=True, for_exams=False)  # from a file

    def slot(self, room, day="mon"):
        return TimetableSlot.objects.create(
            term=self.term, unit=self.unit, program=self.program, room=room, day_of_week=day, start_time=time(8), end_time=time(9)
        )

    def test_the_key_treats_spelling_as_one_room_and_numbers_as_different(self):
        self.assertEqual(len({room_key(c) for c in ("TC 1", "tc1", "TC-1", "TC 01")}), 1)
        self.assertNotEqual(room_key("TC 1"), room_key("TC 11"))
        self.assertNotEqual(room_key("TC 10"), room_key("TC 1"))

    def test_the_preview_changes_nothing_and_says_what_merging_does(self):
        self.slot(self.upload)
        groups = duplicate_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual((groups[0]["keep"]["code"], [r["code"] for r in groups[0]["merge"]]), ("TC 1", ["TC1"]))
        self.assertEqual(groups[0]["result"], {"capacity": 100, "capacity_confirmed": True, "for_exams": False, "health_unit": False})
        self.assertEqual(Room.objects.count(), 2)

    def test_merging_moves_slots_and_keeps_the_confirmed_capacity_and_the_exam_mark(self):
        moved = self.slot(self.file, day="tue")
        kept = self.slot(self.upload, day="mon")
        twin = self.slot(self.file, day="mon")  # the same class on both codes: one stays
        self.slot(self.upload, day="wed")
        self.slot(self.upload, day="thu")
        result = merge_all()
        self.assertEqual((result["groups"], result["rooms_removed"], result["results"][0]["slots_dropped"]), (1, 1, 1))
        room = Room.objects.get(code="TC 1")
        self.assertEqual((room.capacity, room.capacity_confirmed, room.for_exams, room.building, room.name), (100, True, False, "TC", "Tuition 1"))
        self.assertFalse(Room.objects.filter(code="TC1").exists())
        moved.refresh_from_db()
        kept.refresh_from_db()
        self.assertEqual((moved.room, kept.room), (room, room))
        self.assertFalse(TimetableSlot.objects.filter(pk=twin.pk).exists())
        self.assertEqual(duplicate_groups(), [])

    def test_no_new_twin_from_a_form_a_file_or_an_upload(self):
        made = RoomSerializer(data={"code": "tc-1", "name": "x", "building": "TC", "capacity": 5})
        self.assertFalse(made.is_valid())
        self.assertIn("same room as", str(made.errors["code"]))
        self.assertTrue(RoomSerializer(self.file, data={"code": "TC1", "capacity": 90}, partial=True).is_valid() is False)
        merge_all()
        import_rooms("v.csv", b"code,capacity\nTC-01,120\n")
        self.assertEqual(Room.objects.get().capacity, 120)
