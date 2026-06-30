from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.common.models import BaseModel

class User(AbstractUser, BaseModel):
    class Role(models.TextChoices):
        STUDENT   = "student",   "Student"
        ADMIN     = "admin",     "Admin"

    role         = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    university_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    phone_number  = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.get_full_name()} ({self.university_id})"
