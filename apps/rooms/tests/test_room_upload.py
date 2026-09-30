import io

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.rooms.models import Room

URL = "/api/v1/rooms/rooms/upload/"
SUMMARY_URL = "/api/v1/rooms/rooms/capacity-summary/"


def csv_file(text, name="rooms.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


def xlsx_file(rows, name="rooms.xlsx"):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


class RoomCapacityUploadTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", role=User.Role.ADMIN, university_id="ADM1", is_staff=True, is_superuser=True)
        self.lecturer = User.objects.create_user(username="lec", password="x", role=User.Role.LECTURER, university_id="LEC1")
        # As created by a timetable upload: placeholder capacity.
        self.lh1 = Room.objects.create(code="LH1", name="LH1", building="", capacity=50)

    def upload(self, file):
        self.client.force_authenticate(self.admin)
        return self.client.post(URL, {"file": file}, format="multipart")

    def test_csv_updates_existing_and_creates_new_rooms(self):
        response = self.upload(csv_file("Room Code,Capacity,Building\nlh1,120,Main\nLAB 2,40,Science\n"))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data["created"], response.data["updated"]), (1, 1))
        self.lh1.refresh_from_db()
        self.assertEqual((self.lh1.capacity, self.lh1.building, self.lh1.capacity_confirmed), (120, "Main", True))
        lab = Room.objects.get(code="LAB 2")
        self.assertEqual((lab.capacity, lab.capacity_confirmed, lab.name), (40, True, "LAB 2"))

    def test_xlsx_with_title_rows_above_header(self):
        rows = [
            ["UNIVERSITY VENUE CAPACITIES"],
            [],
            ["Venue", "No. of Seats", "Type"],
            ["LH1", 200.0, "Lecture Hall"],
            ["SEM1", 25, "seminar"],
        ]
        response = self.upload(xlsx_file(rows))

        self.assertEqual(response.status_code, 200, response.data)
        self.lh1.refresh_from_db()
        self.assertEqual(self.lh1.capacity, 200)
        self.assertEqual(Room.objects.get(code="SEM1").room_type, Room.Type.SEMINAR)

    def test_bad_rows_are_reported_without_blocking_good_ones(self):
        response = self.upload(csv_file("code,capacity\nLH1,abc\nLH2,0\n,30\nLH3,60\nlh3,70\n"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 1)
        self.assertEqual([e["row"] for e in response.data["errors"]], [2, 3, 4, 6])
        self.assertEqual(Room.objects.get(code="LH3").capacity, 60)
        self.lh1.refresh_from_db()
        self.assertEqual(self.lh1.capacity, 50)

    def test_missing_capacity_column_is_rejected(self):
        response = self.upload(csv_file("code,building\nLH1,Main\n"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("capacity", response.data["detail"])

    def test_unsupported_file_type_is_rejected(self):
        response = self.upload(SimpleUploadedFile("rooms.pdf", b"%PDF"))

        self.assertEqual(response.status_code, 400)

    def test_lecturer_cannot_upload(self):
        self.client.force_authenticate(self.lecturer)
        response = self.client.post(URL, {"file": csv_file("code,capacity\nLH1,999\n")}, format="multipart")

        self.assertEqual(response.status_code, 403)
        self.lh1.refresh_from_db()
        self.assertEqual(self.lh1.capacity, 50)

    def test_capacity_summary_lists_unconfirmed_rooms(self):
        Room.objects.create(code="TBA", name="To Be Announced", building="", capacity=50)
        Room.objects.create(code="LH9", name="LH9", building="", capacity=80, capacity_confirmed=True)
        self.client.force_authenticate(self.admin)

        response = self.client.get(SUMMARY_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unconfirmed_codes"], ["LH1"])
        self.assertEqual((response.data["total"], response.data["confirmed"]), (2, 1))

    def test_editing_capacity_via_api_confirms_it(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(f"/api/v1/rooms/rooms/{self.lh1.pk}/", {"capacity": 90}, format="json")

        self.assertEqual(response.status_code, 200)
        self.lh1.refresh_from_db()
        self.assertTrue(self.lh1.capacity_confirmed)
