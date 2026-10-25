from rest_framework.exceptions import ValidationError
from apps.departments.models import Department


def validate_unique_department_code(code):
    if Department.objects.filter(code__iexact=code).exists():
        raise ValidationError(f"Department code '{code}' already exists.")


def validate_department_admin_assignment(user, department):
    # prevent assigning the same user multiple times
    if department.admins.filter(user=user).exists():
        raise ValidationError("User is already assigned as a department admin.")
