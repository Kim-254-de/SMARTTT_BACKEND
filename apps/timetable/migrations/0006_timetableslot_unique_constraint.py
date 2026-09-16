from django.db import migrations, models


def dedupe_timetable_slots(apps, schema_editor):
    """
    TimetableSlot has never had a DB-level uniqueness guarantee, so
    persistence.py's bulk_create(..., ignore_conflicts=True) has had
    nothing to actually ignore - every (re-)upload of the same timetable
    has been inserting the same rows again instead of being deduplicated.
    Collapse those duplicates (keeping the earliest of each group) before
    the constraint below is added, or the migration would fail outright on
    a database that already has them.
    """
    TimetableSlot = apps.get_model('timetable', 'TimetableSlot')
    seen = {}
    duplicate_ids = []
    for slot in TimetableSlot.objects.order_by('created_at').iterator():
        key = (
            slot.term_id, slot.program_id, slot.unit_id, slot.year_of_study,
            slot.day_of_week, slot.start_time, slot.end_time, slot.room_id,
            slot.class_group, slot.stream,
        )
        if key in seen:
            duplicate_ids.append(slot.id)
        else:
            seen[key] = slot.id
    if duplicate_ids:
        TimetableSlot.objects.filter(id__in=duplicate_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('timetable', '0005_timetableslot_stream'),
    ]

    operations = [
        migrations.RunPython(dedupe_timetable_slots, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='timetableslot',
            constraint=models.UniqueConstraint(
                fields=[
                    'term', 'program', 'unit', 'year_of_study', 'day_of_week',
                    'start_time', 'end_time', 'room', 'class_group', 'stream',
                ],
                name='unique_timetable_slot',
            ),
        ),
    ]
