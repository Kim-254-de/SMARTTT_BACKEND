"""
Faculties play no part any more: a department stands on its own and its code
is unique across the university (the Timetable Allocator and Generator know a
department by it).

Two departments that shared a code under different faculties would block the
new unique code, so a clashing code is renamed first ("CS" -> "CS2"), keeping
the oldest department's as it was. The faculties themselves are deleted.
"""

from django.db import migrations, models


def unique_codes(apps, schema_editor):
    Department = apps.get_model("departments", "Department")
    taken: set[str] = set()
    for department in Department.objects.order_by("created_at", "id"):
        code = department.code.strip() or "X"
        wanted, n = code[:30], 1
        while code.upper() in taken:
            n += 1
            code = f"{wanted}{n}"
        taken.add(code.upper())
        if code != department.code:
            Department.objects.filter(pk=department.pk).update(code=code)


class Migration(migrations.Migration):

    dependencies = [
        ('departments', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='department',
            options={'ordering': ['name']},
        ),
        migrations.RemoveIndex(
            model_name='department',
            name='departments_faculty_e66e8a_idx',
        ),
        migrations.AlterUniqueTogether(
            name='department',
            unique_together=set(),
        ),
        migrations.RunPython(unique_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='department',
            name='code',
            field=models.CharField(max_length=32, unique=True),
        ),
        migrations.RemoveField(
            model_name='department',
            name='faculty',
        ),
        migrations.DeleteModel(
            name='Faculty',
        ),
    ]
