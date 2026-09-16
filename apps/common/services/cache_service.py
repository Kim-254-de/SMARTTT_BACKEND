"""Optional cache layer for personalized timetable payloads."""

from __future__ import annotations

from django.core.cache import cache


class PersonalizationCacheService:
    PREFIX = "personalization:timetable"
    TTL_SECONDS = 300

    @staticmethod
    def build_key(student_id: str, academic_year: str, semester: int) -> str:
        return f"{PersonalizationCacheService.PREFIX}:{student_id}:{academic_year}:{semester}"

    @staticmethod
    def get(student_id: str, academic_year: str, semester: int):
        return cache.get(PersonalizationCacheService.build_key(student_id, academic_year, semester))

    @staticmethod
    def set(student_id: str, academic_year: str, semester: int, payload, timeout: int | None = None):
        cache.set(
            PersonalizationCacheService.build_key(student_id, academic_year, semester),
            payload,
            timeout or PersonalizationCacheService.TTL_SECONDS,
        )
        return payload

    @staticmethod
    def invalidate(student_id: str, academic_year: str, semester: int):
        cache.delete(PersonalizationCacheService.build_key(student_id, academic_year, semester))

    @staticmethod
    def clear_all():
        """Clears all personalization caches."""
        try:
            cache.clear()
        except Exception:
            pass
