from rest_framework.exceptions import ValidationError

from apps.timetable.utils.constants import REQUIRED_TIMETABLE_COLUMNS


class TimetableUploadValidator:
    @staticmethod
    def validate_columns(columns):
        missing = REQUIRED_TIMETABLE_COLUMNS.difference(set(columns))
        if missing:
            raise ValidationError({"missing_columns": sorted(list(missing))})
