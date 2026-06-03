from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.students.models import Student


class RegisterViewTests(APITestCase):
    def test_register_accepts_slash_registration_number(self):
        url = reverse("auth_register")
        payload = {
            "email": "ebt1@example.com",
            "password": "secret123",
            "full_name": "Test Student",
            "admission_number": "Ebt1/09919/23",
            "course": "BSc Computer Science",
            "department": "Computer Science",
            "year_of_study": 1,
        }

        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Student.objects.filter(registration_number="EBT1/09919/23").exists())

    def test_register_returns_400_for_invalid_registration_number(self):
        url = reverse("auth_register")
        payload = {
            "email": "badreg@example.com",
            "password": "secret123",
            "full_name": "Bad Reg",
            "admission_number": "EBT1/09919_23",
            "course": "BSc Computer Science",
            "department": "Computer Science",
            "year_of_study": 1,
        }

        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("registration_number", response.data)
