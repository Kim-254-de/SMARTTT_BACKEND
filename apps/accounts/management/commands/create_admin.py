import os
from django.core.management.base import BaseCommand
from apps.accounts.models import User


class Command(BaseCommand):
    help = (
        "Creates (or repairs) the admin superuser from DJANGO_SUPERUSER_EMAIL / "
        "DJANGO_SUPERUSER_PASSWORD. Safe to run on every deploy."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Overwrite the password of an existing admin with DJANGO_SUPERUSER_PASSWORD.",
        )

    def handle(self, *args, **options):
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                "DJANGO_SUPERUSER_EMAIL or DJANGO_SUPERUSER_PASSWORD not set — skipping."
            ))
            return

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            User.objects.create_superuser(
                username=email,
                email=email,
                password=password,
                first_name="Admin",
                role=User.Role.ADMIN,
            )
            self.stdout.write(self.style.SUCCESS(f"Superuser {email} created successfully."))
            return

        # Make sure an existing account can actually reach the admin panel
        # and the admin.html dashboard (IsRegistrarOrAdmin checks role/is_staff).
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.role = User.Role.ADMIN
        if options["reset_password"] or os.getenv("DJANGO_SUPERUSER_RESET_PASSWORD") == "1":
            user.set_password(password)
            msg = f"Superuser {email} already exists — flags and password updated."
        else:
            msg = f"Superuser {email} already exists — flags ensured."
        user.save()
        self.stdout.write(self.style.SUCCESS(msg))
