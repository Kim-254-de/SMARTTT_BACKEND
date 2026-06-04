"""Accounts utility helpers.

These helpers are intentionally small and dependency-light so they can be used
from any app (permissions, services, selectors) without import cycles.
"""


def is_super_admin(user) -> bool:
	if not user or not hasattr(user, "role"):
		return False
	return user.role == "admin" and bool(getattr(user, "is_staff", False)) and bool(getattr(user, "is_superuser", False))


def is_department_admin(user) -> bool:
	if not user or not hasattr(user, "role"):
		return False
	return user.role in {"admin", "registrar"}


def is_registrar(user) -> bool:
	if not user or not hasattr(user, "role"):
		return False
	return user.role == "registrar"


def is_lecturer(user) -> bool:
	if not user or not hasattr(user, "role"):
		return False
	return user.role == "lecturer"


def is_student(user) -> bool:
	if not user or not hasattr(user, "role"):
		return False
	return user.role == "student"
__all__ = [
	"is_super_admin",
	"is_department_admin",
	"is_registrar",
	"is_lecturer",
	"is_student",
]
