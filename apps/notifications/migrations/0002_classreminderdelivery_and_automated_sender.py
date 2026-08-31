import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0001_initial"),
        ("timetable", "0003_timetableslot_lecturer_name_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="sent_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sent_notifications",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("timetable_change", "Timetable Change"),
                    ("class_reminder", "Class Reminder"),
                    ("sync_reminder", "Sync Reminder"),
                    ("registration_reminder", "Registration Reminder"),
                    ("general", "General"),
                ],
                default="general",
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="ClassReminderDelivery",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("minutes_before", models.PositiveSmallIntegerField()),
                ("occurrence_date", models.DateField()),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                (
                    "slot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reminder_deliveries",
                        to="timetable.timetableslot",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="class_reminder_deliveries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-sent_at"]},
        ),
        migrations.AddConstraint(
            model_name="classreminderdelivery",
            constraint=models.UniqueConstraint(
                fields=("slot", "user", "occurrence_date", "minutes_before"),
                name="unique_class_reminder_delivery",
            ),
        ),
    ]
