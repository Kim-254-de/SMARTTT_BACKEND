"""
Who someone is to the two timetabling systems (Timetable Allocator and
Timetable Generator), which have no accounts of their own: staff sign in
there with their SMARTTT account, and the system asks here whether the
password is right and what the person may do.

- Directorate of Examinations and Timetabling: members of the Django auth
  group settings.TIMETABLING_OFFICE_GROUP (and superusers). They run the
  Generator and see every department's allocation progress.
- Chair of Department (COD): the department's `head_of_department`. Allocates
  lecturers for their department and submits the allocation.
- Department staff: a DepartmentAdmin row (admin or editor). Allocates
  lecturers for that department but cannot submit.

The systems re-read this (identity_for) whenever they refresh a sign-in, so
a removed COD or a deactivated account loses access within one session
lifetime rather than keeping it until their token expires.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.accounts.models import User
from apps.departments.models import Department, DepartmentAdmin

ROLE_COD = "cod"
ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"


def is_timetabling_office(user: User) -> bool:
    if user.is_superuser:
        return True
    return user.groups.filter(name=settings.TIMETABLING_OFFICE_GROUP).exists()


def department_roles(user: User) -> list[dict]:
    """
    The departments this person may allocate for, one entry each, with their
    strongest role there: COD over a DepartmentAdmin admin over an editor.
    """
    strength = {ROLE_COD: 3, ROLE_ADMIN: 2, ROLE_EDITOR: 1}
    roles: dict[int, tuple[Department, str]] = {}

    for dept in Department.objects.filter(head_of_department=user).select_related("faculty"):
        roles[dept.id] = (dept, ROLE_COD)
    for assignment in DepartmentAdmin.objects.filter(user=user).select_related("department__faculty"):
        role = assignment.role if assignment.role in (ROLE_ADMIN, ROLE_EDITOR) else ROLE_EDITOR
        current = roles.get(assignment.department_id)
        if current is None or strength[role] > strength[current[1]]:
            roles[assignment.department_id] = (assignment.department, role)

    return [
        {
            "id": dept.id,
            "code": dept.code,
            "name": dept.name,
            "faculty": dept.faculty.name if dept.faculty_id else None,
            "role": role,
        }
        for dept, role in sorted(roles.values(), key=lambda item: item[0].name)
    ]


def identity_for(user: User) -> dict:
    """The account and what it may do in the timetabling systems."""
    return {
        "account": {
            "id": str(user.id),
            "role": user.role,
            "university_id": (user.university_id or "").strip().upper() or None,
            "email": (user.email or "").strip().lower() or None,
            "full_name": user.get_full_name().strip() or user.username,
            "is_active": bool(user.is_active),
        },
        "timetabling_office": is_timetabling_office(user),
        "departments": department_roles(user),
    }


def authenticate_staff(identifier: str, password: str) -> dict | None:
    """
    Checks a SMARTTT login (email, username or staff ID, case-insensitive) the
    same way the attendance sign-in does. None when the credentials are wrong
    or the account is inactive.
    """
    login_id = (identifier or "").strip()
    if not login_id or not password:
        return None
    user_obj = User.objects.filter(
        Q(email__iexact=login_id) | Q(username__iexact=login_id) | Q(university_id__iexact=login_id)
    ).first()
    # Unknown ids still go through authenticate(), which runs the password
    # hasher anyway, so timing doesn't reveal which accounts exist.
    user = authenticate(username=user_obj.username if user_obj else login_id, password=password)
    if user is None:
        return None
    return identity_for(user)


def find_identity(account_id: str) -> dict | None:
    """identity_for the account with this id; None when it is gone or inactive."""
    try:
        user = User.objects.get(pk=account_id, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, ValidationError):
        return None
    return identity_for(user)
