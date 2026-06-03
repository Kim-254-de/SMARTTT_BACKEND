from django.db import transaction

from apps.curriculum.models import Curriculum, CurriculumUnit, CurriculumVersion
from apps.curriculum.services.curriculum_versioning import CurriculumVersioningService
from apps.curriculum.validators import CurriculumDomainValidator


class CurriculumService:
    """Application service for curriculum CRUD workflows and nested units."""

    @classmethod
    @transaction.atomic
    def create_curriculum(cls, *, payload: dict, units_payload: list[dict], actor=None) -> Curriculum:
        CurriculumDomainValidator.validate_semester(payload["semester"])
        CurriculumDomainValidator.validate_duplicate_units(units_payload)
        CurriculumDomainValidator.validate_duplicate_curriculum_version(
            program_id=payload["program"],
            academic_year=payload["academic_year"],
            study_year=payload["study_year"],
            semester=payload["semester"],
            version=payload.get("version", 1),
        )

        create_payload = payload.copy()
        if "program" in create_payload:
            create_payload["program_id"] = create_payload.pop("program")
        if "department" in create_payload:
            create_payload["department_id"] = create_payload.pop("department")

        curriculum = Curriculum.objects.create(created_by=actor, **create_payload)

        cls._replace_curriculum_units(curriculum=curriculum, units_payload=units_payload)
        CurriculumDomainValidator.validate_missing_required_units(curriculum=curriculum)

        CurriculumVersioningService.create_version_entry(
            curriculum=curriculum,
            action=CurriculumVersion.Action.CREATED,
            acted_by=actor,
            summary="Initial curriculum version created.",
        )
        return curriculum

    @classmethod
    @transaction.atomic
    def update_curriculum(
        cls,
        *,
        curriculum: Curriculum,
        payload: dict,
        units_payload: list[dict] | None,
        actor=None,
    ) -> Curriculum:
        target_values = {
            "program_id": payload.get("program", curriculum.program_id),
            "academic_year": payload.get("academic_year", curriculum.academic_year),
            "study_year": payload.get("study_year", curriculum.study_year),
            "semester": payload.get("semester", curriculum.semester),
            "version": payload.get("version", curriculum.version),
        }
        CurriculumDomainValidator.validate_semester(target_values["semester"])
        CurriculumDomainValidator.validate_duplicate_curriculum_version(
            program_id=target_values["program_id"],
            academic_year=target_values["academic_year"],
            study_year=target_values["study_year"],
            semester=target_values["semester"],
            version=target_values["version"],
            exclude_curriculum_id=curriculum.id,
        )

        changed = False
        for key, value in payload.items():
            if key == "program":
                key = "program_id"
            if key == "department":
                key = "department_id"

            if getattr(curriculum, key) != value:
                setattr(curriculum, key, value)
                changed = True

        if changed:
            curriculum.save()

        if units_payload is not None:
            CurriculumDomainValidator.validate_duplicate_units(units_payload)
            cls._replace_curriculum_units(curriculum=curriculum, units_payload=units_payload)
            CurriculumDomainValidator.validate_missing_required_units(curriculum=curriculum)

        status = payload.get("status")
        if status == Curriculum.Status.ACTIVE:
            CurriculumVersioningService.activate_curriculum(
                curriculum=curriculum,
                acted_by=actor,
                summary="Curriculum activated by update.",
            )
        elif status == Curriculum.Status.INACTIVE:
            CurriculumVersioningService.deactivate_curriculum(
                curriculum=curriculum,
                acted_by=actor,
                summary="Curriculum deactivated by update.",
            )

        if changed or units_payload is not None:
            CurriculumVersioningService.create_version_entry(
                curriculum=curriculum,
                action=CurriculumVersion.Action.UPDATED,
                acted_by=actor,
                summary="Curriculum metadata and/or units updated.",
            )

        return curriculum

    @staticmethod
    def _replace_curriculum_units(*, curriculum: Curriculum, units_payload: list[dict]) -> None:
        CurriculumUnit.objects.filter(curriculum=curriculum).delete()
        created = []
        for item in units_payload:
            unit_data = {
                "curriculum": curriculum,
                "unit_id": item["unit"],
                "is_core": item.get("is_core", True),
                "is_elective": item.get("is_elective", False),
                "display_order": item.get("display_order", 1),
                "prerequisite_unit_id": item.get("prerequisite_unit"),
                "credit_hours": item.get("credit_hours", 3),
            }
            created.append(CurriculumUnit(**unit_data))

        CurriculumUnit.objects.bulk_create(created)