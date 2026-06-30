import os
from django.core.management.base import BaseCommand
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Creates a superuser from environment variables if one doesn't already exist."

    def handle(self, *args, **options):
        email = os.getenv("DJANGO_SUPERUSER_EMAIL")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                "DJANGO_SUPERUSER_EMAIL or DJANGO_SUPERUSER_PASSWORD not set — skipping."
            ))
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.SUCCESS(f"Superuser {email} already exists — skipping."))
            return

        User.objects.create_superuser(
            username=email,
            email=email,
            password=password,
            first_name="Admin",
        )
        self.stdout.write(self.style.SUCCESS(f"Superuser {email} created successfully."))
