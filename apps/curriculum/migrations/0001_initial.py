from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "__first__"),
        ("departments", "__first__"),
        ("programs", "__first__"),
        ("units", "__first__"),
    ]

    operations = [
        migrations.CreateModel(
            name="Curriculum",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("academic_year", models.CharField(max_length=20)),
                ("study_year", models.PositiveSmallIntegerField()),
                ("semester", models.PositiveSmallIntegerField()),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("inactive", "Inactive")],
                        default="active",
                        max_length=20,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_curricula",
                        to="accounts.user",
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="curricula",
                        to="departments.department",
                    ),
                ),
                (
                    "program",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="curricula",
                        to="programs.program",
                    ),
                ),
            ],
            options={
                "ordering": [
                    "program__code",
                    "academic_year",
                    "study_year",
                    "semester",
                    "-version",
                ],
            },
        ),
        migrations.CreateModel(
            name="CurriculumVersion",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version", models.PositiveIntegerField()),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("activated", "Activated"),
                            ("deactivated", "Deactivated"),
                            ("updated", "Updated"),
                        ],
                        max_length=20,
                    ),
                ),
                ("change_summary", models.TextField(blank=True)),
                (
                    "acted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="curriculum_version_actions",
                        to="accounts.user",
                    ),
                ),
                (
                    "curriculum",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="version_history",
                        to="curriculum.curriculum",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="CurriculumUnit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_core", models.BooleanField(default=True)),
                ("is_elective", models.BooleanField(default=False)),
                ("display_order", models.PositiveIntegerField(default=1)),
                ("credit_hours", models.PositiveSmallIntegerField(default=3)),
                (
                    "curriculum",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="curriculum_units",
                        to="curriculum.curriculum",
                    ),
                ),
                (
                    "prerequisite_unit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dependent_curriculum_units",
                        to="units.unit",
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="curriculum_mappings",
                        to="units.unit",
                    ),
                ),
            ],
            options={"ordering": ["curriculum", "display_order", "unit__code"]},
        ),
        migrations.AddIndex(
            model_name="curriculum",
            index=models.Index(fields=["department", "status"], name="idx_curriculum_dept_status"),
        ),
        migrations.AddIndex(
            model_name="curriculum",
            index=models.Index(
                fields=["program", "study_year", "semester"], name="idx_curriculum_program_y_s"
            ),
        ),
        migrations.AddConstraint(
            model_name="curriculum",
            constraint=models.UniqueConstraint(
                fields=("program", "academic_year", "study_year", "semester", "version"),
                name="uq_curriculum_program_term_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="curriculum",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "active")),
                fields=("program", "academic_year", "study_year", "semester"),
                name="uq_curriculum_single_active_per_term",
            ),
        ),
        migrations.AddIndex(
            model_name="curriculumversion",
            index=models.Index(fields=["curriculum", "version"], name="idx_curriculum_version_lookup"),
        ),
        migrations.AddConstraint(
            model_name="curriculumunit",
            constraint=models.UniqueConstraint(
                fields=("curriculum", "unit"),
                name="uq_curriculumunit_curriculum_unit",
            ),
        ),
        migrations.AddIndex(
            model_name="curriculumunit",
            index=models.Index(fields=["curriculum", "display_order"], name="idx_curriculumunit_order"),
        ),
        migrations.AddIndex(
            model_name="curriculumunit",
            index=models.Index(fields=["unit"], name="idx_curriculumunit_unit"),
        ),
    ]