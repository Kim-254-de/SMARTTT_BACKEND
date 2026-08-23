"""
Constants for timetable operations.

Production-level constants for file validation, data format,
and business logic configuration.
"""

# Required columns in Excel file
REQUIRED_TIMETABLE_COLUMNS = {
    "academic_year",
    "semester",
    "program_code",
    "unit_code",
    "year_of_study",
    "day_of_week",
    "start_time",
    "end_time",
    "room_code",
    "class_group",
}

# Optional columns (can be missing) — lecturer_university_id is optional because
# a timetable slot can be created before a lecturer is assigned; lecturer
# assignment happens later via the separate lecturer allocation upload.
OPTIONAL_TIMETABLE_COLUMNS = {
    "lecturer_university_id",
    "notes",
    "venue_name",
    "session_type",
}

# All valid column names (for validation)
VALID_TIMETABLE_COLUMNS = REQUIRED_TIMETABLE_COLUMNS | OPTIONAL_TIMETABLE_COLUMNS

# Valid day abbreviations mapped to full names
VALID_DAYS = {
    "mon": "MONDAY",
    "tue": "TUESDAY",
    "wed": "WEDNESDAY",
    "thu": "THURSDAY",
    "fri": "FRIDAY",
    "sat": "SATURDAY",
}

# Supported file extensions for upload
SUPPORTED_FILE_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf", ".docx"}

# Maximum file size: 10MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# Maximum rows per upload
MAX_ROWS_PER_UPLOAD = 10000

# Time format validation
TIME_FORMAT = "%H:%M"  # HH:MM format

# Minimum gap between sessions (in minutes)
MIN_SESSION_GAP_MINUTES = 0  # Can be set to enforce breaks between sessions

# Maximum sessions per day per lecturer
MAX_SESSIONS_PER_DAY_PER_LECTURER = 6

# Batch processing configuration
BATCH_SIZE = 100  # For bulk operations
