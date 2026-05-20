# Timetable Upload System - API Documentation

## Overview

Production-level timetable Excel upload and processing system for a smart university backend. The system validates, processes, and stores timetable data with comprehensive conflict detection.

## Quick Start

### 1. Setup & Installation

```bash
# Install dependencies (if not already installed)
pip install django djangorestframework pandas openpyxl

# Run migrations (timetable models should already be migrated)
python manage.py migrate timetable

# Create a superuser (if needed)
python manage.py createsuperuser
```

### 2. Access Points

- **Admin Interface**: `http://localhost:8000/admin/`
- **API Root**: `http://localhost:8000/api/timetable/`
- **Swagger/OpenAPI** (if installed): `http://localhost:8000/api/docs/`

---

## API Endpoints

### Upload Timetable File

**POST** `/api/timetable/upload/`

Upload an Excel file containing timetable data for processing.

#### Request

```bash
# Using curl with session authentication
curl -X POST \
  -H "X-CSRFToken: <csrf_token>" \
  -F "file=@timetable.xlsx" \
  http://localhost:8000/api/v1/uploads/upload/ \
  -b "sessionid=<session_id>"
```

#### Request Headers
- `X-CSRFToken: {csrf_token}` - Required for POST requests (session authentication)
- `Content-Type: multipart/form-data` - Automatically set by curl with -F flag
- Session cookie must be included (automatically handled by browsers/clients)

#### Request Body
- `file` (required): Excel file (.xlsx or .xls) with timetable data

#### Response - Success (201 Created)

```json
{
  "status": "success",
  "upload_batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "summary": {
    "rows_received": 150,
    "rows_saved": 150,
    "rows_failed": 0,
    "success_rate": 100.0,
    "conflicts_detected": 5
  },
  "errors": [],
  "message": "Upload processed: 150 of 150 rows saved."
}
```

#### Response - Partial Success (200 OK)

```json
{
  "status": "partial",
  "upload_batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "summary": {
    "rows_received": 150,
    "rows_saved": 145,
    "rows_failed": 5,
    "success_rate": 96.67,
    "conflicts_detected": 8
  },
  "errors": [
    "Row 5: Missing required field 'room_code'",
    "Row 12: Invalid semester value '4' (expected 1-3)",
    "Row 23: Lecturer not found: SCI001",
    "Row 45: Invalid time format",
    "Row 67: Duplicate session"
  ],
  "message": "Upload processed: 145 of 150 rows saved."
}
```

#### Response - Failure (400 Bad Request)

```json
{
  "status": "error",
  "error": {
    "code": "FILE_VALIDATION_ERROR",
    "message": "File validation failed",
    "details": [
      "File size exceeds 10.0MB limit. Got: 15.25MB"
    ]
  }
}
```

---

### List Upload History

**GET** `/api/timetable/uploads/`

Retrieve list of all timetable uploads with filtering and pagination.

#### Request

```bash
curl -X GET \
  "http://localhost:8000/api/v1/uploads/" \
  -b "sessionid=<session_id>"
```

#### Query Parameters
- `status` - Filter by upload status: `received`, `validated`, `failed`, `processed`
- `uploaded_by` - Filter by uploader user ID
- `page` - Page number (default: 1)
- `page_size` - Items per page (default: 50, max: 100)
- `ordering` - Sort field: `created_at`, `status`, `rows_saved` (prefix with `-` for descending)

#### Response (200 OK)

```json
{
  "count": 23,
  "next": "http://localhost:8000/api/timetable/uploads/?page=2",
  "previous": null,
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "uploaded_by": 5,
      "uploaded_by_name": "Dr. Smith",
      "source_file": "/media/timetable_uploads/2024/01/15/timetable.xlsx",
      "status": "processed",
      "rows_received": 150,
      "rows_saved": 150,
      "validation_error_count": 0,
      "success_rate": 100.0,
      "created_at": "2024-01-15T10:30:45Z",
      "updated_at": "2024-01-15T10:35:20Z"
    }
  ]
}
```

---

### Get Upload Details

**GET** `/api/timetable/uploads/{id}/`

Get detailed information about a specific upload batch including all created slots.

#### Request

```bash
curl -X GET \
  "http://localhost:8000/api/v1/uploads/550e8400-e29b-41d4-a716-446655440000/" \
  -b "sessionid=<session_id>"
```

#### Response (200 OK)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "uploaded_by": 5,
  "uploaded_by_name": "Dr. Smith",
  "source_file": "/media/timetable_uploads/2024/01/15/timetable.xlsx",
  "status": "processed",
  "rows_received": 150,
  "rows_saved": 150,
  "validation_errors": [],
  "slots": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440000",
      "term": "550e8400-e29b-41d4-a716-446655440001",
      "curriculum_unit": "550e8400-e29b-41d4-a716-446655440002",
      "lecturer": "550e8400-e29b-41d4-a716-446655440003",
      "room": "550e8400-e29b-41d4-a716-446655440004",
      "day_of_week": "mon",
      "start_time": "09:00:00",
      "end_time": "10:30:00",
      "class_group": "MAIN",
      "upload_batch": "550e8400-e29b-41d4-a716-446655440000",
      "created_at": "2024-01-15T10:30:45Z"
    }
  ],
  "created_at": "2024-01-15T10:30:45Z",
  "updated_at": "2024-01-15T10:35:20Z"
}
```

---

### List Timetable Slots

**GET** `/api/timetable/slots/`

Retrieve all timetable slots with advanced filtering.

#### Request

```bash
curl -X GET \
  "http://localhost:8000/api/v1/timetable/slots/?term=550e8400&day_of_week=mon&room=550e8400" \
  -b "sessionid=<session_id>"
```

#### Query Parameters
- `term` - Filter by academic term ID
- `day_of_week` - Filter by day: `mon`, `tue`, `wed`, `thu`, `fri`, `sat`
- `room` - Filter by room ID
- `lecturer` - Filter by lecturer ID
- `upload_batch` - Filter by upload batch ID
- `ordering` - Sort by: `term`, `day_of_week`, `start_time`, `end_time`

#### Response (200 OK)

```json
{
  "count": 1500,
  "next": "http://localhost:8000/api/timetable/slots/?page=2",
  "previous": null,
  "results": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440000",
      "term": "550e8400-e29b-41d4-a716-446655440001",
      "curriculum_unit": "550e8400-e29b-41d4-a716-446655440002",
      "lecturer": "550e8400-e29b-41d4-a716-446655440003",
      "room": "550e8400-e29b-41d4-a716-446655440004",
      "day_of_week": "mon",
      "start_time": "09:00:00",
      "end_time": "10:30:00",
      "class_group": "MAIN",
      "upload_batch": "550e8400-e29b-41d4-a716-446655440000",
      "created_at": "2024-01-15T10:30:45Z"
    }
  ]
}
```

---

### Get Slot Details (with related info)

**GET** `/api/timetable/slots/{id}/detailed/`

Get detailed information about a specific slot with all related data.

#### Request

```bash
curl -X GET \
  "http://localhost:8000/api/v1/timetable/slots/660e8400-e29b-41d4-a716-446655440000/detailed/" \
  -b "sessionid=<session_id>"
```

#### Response (200 OK)

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "term": "550e8400-e29b-41d4-a716-446655440001",
  "term_display": "2023-2024 S1",
  "curriculum_unit": "550e8400-e29b-41d4-a716-446655440002",
  "curriculum_unit_display": "COMP101 (Computer Science)",
  "lecturer": "550e8400-e29b-41d4-a716-446655440003",
  "lecturer_display": "Dr. John Smith",
  "room": "550e8400-e29b-41d4-a716-446655440004",
  "room_display": "A101",
  "day_of_week": "mon",
  "day_display": "Monday",
  "start_time": "09:00:00",
  "end_time": "10:30:00",
  "class_group": "MAIN",
  "upload_batch": "550e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-01-15T10:30:45Z",
  "updated_at": "2024-01-15T10:30:45Z"
}
```

---

### List Conflicts

**GET** `/api/timetable/conflicts/`

Retrieve all detected timetable conflicts with filtering.

#### Request

```bash
curl -X GET \
  "http://localhost:8000/api/v1/timetable/conflicts/?conflict_type=room&term=550e8400" \
  -b "sessionid=<session_id>"
```

#### Query Parameters
- `conflict_type` - Filter by type: `room`, `lecturer`, `program`
- `term` - Filter by academic term ID

#### Response (200 OK)

```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440000",
      "conflict_type": "room",
      "conflict_type_display": "Room Conflict",
      "term": "550e8400-e29b-41d4-a716-446655440001",
      "slot_a": "660e8400-e29b-41d4-a716-446655440000",
      "slot_a_details": {
        "id": "660e8400-e29b-41d4-a716-446655440000",
        "term": "550e8400-e29b-41d4-a716-446655440001",
        "term_display": "2023-2024 S1",
        "curriculum_unit": "550e8400-e29b-41d4-a716-446655440002",
        "curriculum_unit_display": "COMP101",
        "lecturer": "550e8400-e29b-41d4-a716-446655440003",
        "lecturer_display": "Dr. John Smith",
        "room": "550e8400-e29b-41d4-a716-446655440004",
        "room_display": "A101",
        "day_of_week": "mon",
        "day_display": "Monday",
        "start_time": "09:00:00",
        "end_time": "10:30:00",
        "class_group": "MAIN",
        "upload_batch": "550e8400-e29b-41d4-a716-446655440000",
        "created_at": "2024-01-15T10:30:45Z",
        "updated_at": "2024-01-15T10:30:45Z"
      },
      "slot_b": "660e8400-e29b-41d4-a716-446655440001",
      "slot_b_details": {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "curriculum_unit_display": "PHYS101",
        "lecturer_display": "Prof. Jane Doe",
        "start_time": "09:15:00",
        "end_time": "10:45:00"
      },
      "details": {
        "conflict_type": "room",
        "slot_a": {
          "id": "660e8400-e29b-41d4-a716-446655440000",
          "unit": "COMP101",
          "lecturer": "JS001",
          "room": "A101",
          "time": "09:00 - 10:30"
        },
        "slot_b": {
          "id": "660e8400-e29b-41d4-a716-446655440001",
          "unit": "PHYS101",
          "lecturer": "JD001",
          "room": "A101",
          "time": "09:15 - 10:45"
        },
        "overlap_time": "09:15 - 10:30"
      },
      "created_at": "2024-01-15T10:30:45Z"
    }
  ]
}
```

---

## Excel File Format

### Required Structure

The Excel file must have the following columns:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `academic_year` | String | Academic year in format YYYY or YYYY-YYYY | `2023-2024` |
| `semester` | Integer | Semester number (1-3) | `1` |
| `program_code` | String | Program/Course code | `CS001` |
| `unit_code` | String | Unit/Subject code | `COMP101` |
| `year_of_study` | Integer | Year of study (1-10) | `1` |
| `day_of_week` | String | Day abbreviation (mon, tue, wed, thu, fri, sat) | `mon` |
| `start_time` | Time | Session start time (HH:MM or HH:MM:SS) | `09:00` |
| `end_time` | Time | Session end time (HH:MM or HH:MM:SS) | `10:30` |
| `room_code` | String | Room/Venue code | `A101` |
| `lecturer_university_id` | String | Lecturer's unique ID | `LEC001` |
| `class_group` | String | Class group identifier (optional, default: MAIN) | `MAIN` |

### Optional Columns

- `notes` - Any additional notes
- `venue_name` - Venue name
- `session_type` - Type of session (e.g., LECTURE, PRACTICAL, TUTORIAL)

### Sample Excel Data

```
academic_year | semester | program_code | unit_code | year_of_study | day_of_week | start_time | end_time | room_code | lecturer_university_id | class_group
2023-2024     | 1        | CS001        | COMP101   | 1             | mon         | 09:00      | 10:30    | A101      | LEC001               | MAIN
2023-2024     | 1        | CS001        | COMP102   | 1             | mon         | 11:00      | 12:30    | B102      | LEC002               | GROUP_A
2023-2024     | 1        | CS001        | COMP102   | 1             | mon         | 11:00      | 12:30    | B103      | LEC003               | GROUP_B
```

---

## Error Codes & Troubleshooting

### File Validation Errors

| Error Code | Message | Solution |
|-----------|---------|----------|
| `NO_FILE_PROVIDED` | No file provided in request | Ensure file is included in multipart/form-data request |
| `FILE_VALIDATION_ERROR` | File extension or size invalid | Use .xlsx or .xls format, max 10MB |
| `EXCEL_PARSING_ERROR` | Cannot parse Excel file | Ensure file is valid Excel format |

### Data Validation Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Missing required column` | Required column not in file | Add all required columns to Excel file |
| `Invalid semester value` | Semester not 1-3 | Use values 1, 2, or 3 only |
| `Invalid day_of_week` | Day not in valid list | Use: mon, tue, wed, thu, fri, sat |
| `start_time must be before end_time` | Start time >= end time | Ensure start_time < end_time |
| `Missing required field` | Cell value is empty | Fill all required fields |

### Resource Not Found Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Academic term not found` | Term doesn't exist in database | Create the term in admin or via API first |
| `Curriculum unit not found` | Unit/Program combination not in database | Verify program_code and unit_code exist |
| `Room not found` | Room code doesn't exist | Create room in admin first |
| `Lecturer not found` | Lecturer ID doesn't exist | Verify lecturer_university_id is correct |

### Conflict Detection

When conflicts are detected, they're logged with:
- Conflict type (room, lecturer, program)
- Affected slots
- Time overlap details
- Suggestions for resolution

---

## Python Example

```python
import requests
from pathlib import Path

# Configuration
API_BASE = "http://localhost:8000/api"
SESSION_ID = "your_session_id_here"  # Get this after logging in

session = requests.Session()
session.cookies.set('sessionid', SESSION_ID)

# 1. Upload timetable file
def upload_timetable(file_path):
    with open(file_path, 'rb') as f:
        files = {'file': f}
        response = session.post(
            f"{API_BASE}/v1/uploads/upload/",
            files=files
        )
    
    if response.status_code in [200, 201]:
        result = response.json()
        print(f"Upload successful: {result['summary']}")
        return result['upload_batch_id']
    else:
        print(f"Upload failed: {response.json()}")
        return None

# 2. List conflicts
def list_conflicts(term_id=None):
    params = {}
    if term_id:
        params['term'] = term_id
    
    response = session.get(
        f"{API_BASE}/v1/timetable/conflicts/",
        params=params
    )
    
    if response.status_code == 200:
        conflicts = response.json()['results']
        for conflict in conflicts:
            print(f"Conflict: {conflict['conflict_type_display']} - "
                  f"{conflict['slot_a_details']['curriculum_unit_display']}")
    else:
        print(f"Error: {response.json()}")

# 3. Get upload details
def get_upload_details(upload_id):
    response = session.get(
        f"{API_BASE}/v1/uploads/{upload_id}/"
    )
    
    if response.status_code == 200:
        upload = response.json()
        print(f"Upload Status: {upload['status']}")
        print(f"Rows Saved: {upload['rows_saved']}/{upload['rows_received']}")
        print(f"Slots Created: {len(upload['slots'])}")
        
        if upload['validation_errors']:
            print("Errors:")
            for error in upload['validation_errors']:
                print(f"  - {error}")
    else:
        print(f"Error: {response.json()}")

# Usage
if __name__ == "__main__":
    # Upload file
    upload_id = upload_timetable("timetable.xlsx")
    
    if upload_id:
        # Check details
        get_upload_details(upload_id)
        
        # List conflicts
        list_conflicts()
```

---

## Performance Considerations

- **Batch Size**: Upload optimized for up to 10,000 rows per file
- **Database Indexes**: Ensure proper indexes on frequently queried fields
- **Duplicate Detection**: Enable to prevent duplicate sessions
- **Conflict Detection**: Automatically runs after successful upload
- **Pagination**: Use pagination for large result sets (default 50 items/page)

---

## Security

- All endpoints require Django session authentication
- Automatic session cookies handle authentication
- CSRF token required for state-changing requests (POST, PATCH, DELETE)
- Only staff/admin users can upload files
- Row-level access control for read-only endpoints
- File validation prevents malicious uploads

---

## Support

For issues or questions:
1. Check error codes in response
2. Review logs: `/logs/timetable.log`
3. Consult Django admin interface for data verification
4. Contact system administrator
