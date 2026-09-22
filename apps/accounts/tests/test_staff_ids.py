from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import StaffIDUpload, User, ValidStaffID


class StaffIDUploadTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", role=User.Role.ADMIN,
                                              university_id="ADM1", is_staff=True)
        self.client.force_authenticate(self.admin)

    def _upload(self, name, content):
        f = SimpleUploadedFile(name, content.encode("utf-8-sig"), content_type="text/csv")
        return self.client.post(reverse("staff-id-upload"), {"file": f}, format="multipart")

    def test_upload_is_recorded_and_bom_header_skipped(self):
        res = self._upload("staff.csv", "staff_id,name\nS1,Ann\nS2,Ben\n")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sorted(ValidStaffID.objects.values_list("staff_id", flat=True)), ["S1", "S2"])
        listing = self.client.get(reverse("staff-id-upload-list")).data
        self.assertEqual(len(listing["uploads"]), 1)
        self.assertEqual(listing["uploads"][0]["ids_created"], 2)
        self.assertEqual(listing["untracked_ids"], 0)

    def _register(self, staff_id="S1", email="ann@tun.ac.ke"):
        self.client.force_authenticate(None)
        res = self.client.post(reverse("lecturer-register"), {
            "staff_id": staff_id, "email": email, "full_name": "Ann Lecturer", "password": "secret123",
        }, format="json")
        self.client.force_authenticate(self.admin)
        return res

    def test_delete_upload_removes_claimed_ids_too(self):
        self._upload("staff.csv", "S1,Ann\nS2,Ben\n")
        self.assertEqual(self._register().status_code, 201)
        upload = StaffIDUpload.objects.get()
        res = self.client.delete(reverse("staff-id-upload-delete", args=[upload.id]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual((res.data["removed"], res.data["accounts_disabled"]), (2, 1))
        self.assertFalse(ValidStaffID.objects.exists())
        self.assertFalse(StaffIDUpload.objects.exists())

    def test_deleted_claimed_id_cannot_be_used_and_account_is_disabled(self):
        self._upload("staff.csv", "S1,Ann\n")
        self.assertEqual(self._register().status_code, 201)
        sid = ValidStaffID.objects.get().id
        self.assertEqual(self.client.delete(reverse("staff-id-delete", args=[sid])).status_code, 200)

        res = self._register(email="someone.else@tun.ac.ke")
        self.assertEqual(res.status_code, 400)
        self.assertIn("does not exist", res.data["detail"])
        self.assertNotIn("already been registered", res.data["detail"])

        user = User.objects.get(email="ann@tun.ac.ke")
        self.assertFalse(user.is_active)
        self.client.force_authenticate(None)
        login = self.client.post(reverse("login"), {"email": "ann@tun.ac.ke", "password": "secret123"}, format="json")
        self.assertNotEqual(login.status_code, 200)

    def test_readded_id_lets_the_lecturer_register_again(self):
        self._upload("staff.csv", "S1,Ann\n")
        self._register()
        self.client.delete(reverse("staff-id-delete", args=[ValidStaffID.objects.get().id]))
        self._upload("staff2.csv", "S1,Ann\n")
        res = self._register()
        self.assertEqual(res.status_code, 201, res.data)
        user = User.objects.get(email="ann@tun.ac.ke")
        self.assertTrue(user.is_active)
        self.assertEqual(user.university_id, "S1")
        self.assertEqual(User.objects.filter(email="ann@tun.ac.ke").count(), 1)

    def test_id_in_use_is_still_refused(self):
        self._upload("staff.csv", "S1,Ann\n")
        self._register()
        res = self._register(email="other@tun.ac.ke")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already been registered", res.data["detail"])

    def test_delete_single_id(self):
        self._upload("staff.csv", "S1,Ann\n")
        sid = ValidStaffID.objects.get().id
        res = self.client.delete(reverse("staff-id-delete", args=[sid]))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(ValidStaffID.objects.exists())
        self.assertEqual(self.client.delete(reverse("staff-id-delete", args=[sid])).status_code, 404)

    def test_list_includes_id_and_file(self):
        self._upload("staff.csv", "S1,Ann\n")
        row = self.client.get(reverse("staff-id-list")).data[0]
        self.assertEqual((row["staff_id"], row["file_name"]), ("S1", "staff.csv"))
        self.assertIn("id", row)
        self.assertNotIn("upload__file_name", row)
