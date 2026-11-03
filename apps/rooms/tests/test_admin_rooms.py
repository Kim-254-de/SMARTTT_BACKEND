"""The admin's venue table, reached through the acting-admin integration."""

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.rooms.models import Room
from apps.rooms.services.room_import import import_rooms
from rest_framework.test import APIClient

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
