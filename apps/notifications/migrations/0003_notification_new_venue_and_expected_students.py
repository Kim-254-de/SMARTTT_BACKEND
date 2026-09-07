import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0001_initial"),
        ("notifications", "0002_classreminderdelivery_and_automated_sender"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("timetable_change", "Timetable Change"),
                    ("venue_change", "Venue Change"),
                    ("class_reminder", "Class Reminder"),
                    ("sync_reminder", "Sync Reminder"),
                    ("registration_reminder", "Registration Reminder"),
                    ("general", "General"),
                ],
                default="general",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="new_venue",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="rooms.room",
            ),
        ),
        migrations.AddField(
            model_name="notification",
            name="expected_students",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
