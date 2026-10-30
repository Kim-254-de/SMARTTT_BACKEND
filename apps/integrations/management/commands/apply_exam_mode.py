"""Switches terms to exam mode, and closes exam periods, whose scheduled time has passed. Run every minute."""

from django.core.management.base import BaseCommand

from apps.integrations.exam_mode import apply_due


class Command(BaseCommand):
    help = "Apply scheduled switches to exam mode and closes of exam periods (safe to run again)."

    def handle(self, *args, **options):
        done = apply_due()
        self.stdout.write(
            self.style.SUCCESS(f"Switched {len(done['switched'])} term(s); closed {len(done['closed'])} exam period(s).")
        )
