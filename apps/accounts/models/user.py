from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.common.models import BaseModel


class User(AbstractUser, BaseModel):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        LECTURER = "lecturer", "Lecturer"
        REGISTRAR = "registrar", "Registrar"
        ADMIN = "admin", "Admin"

    role = models.CharField(max_length=20, choices=Role.choices)
    university_id = models.CharField(max_length=30, unique=True)
    phone_number = models.CharField(max_length=30, blank=True)

    def __str__(self) -> str:
        return f"{self.get_full_name()} ({self.university_id})"
