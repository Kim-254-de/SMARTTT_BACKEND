# Students API - Complete Endpoint Documentation

## Authentication

All endpoints require Django session authentication unless noted otherwise.

### Login Process

1. **Register** (if new user):
   ```bash
   POST /api/v1/accounts/auth/register/
   Content-Type: application/json

   {
     "email": "user@example.com",
     "password": "password",
     "full_name": "Full Name",
     "admission_number": "ADM001"
   }
   ```

2. **Login**:
   ```bash
   POST /api/v1/accounts/auth/login/
   Content-Type: application/json

   {
     "email": "user@example.com",
     "password": "password"
   }
   ```
   This returns a session cookie which is automatically stored by your client.

3. **Access Authenticated Endpoints**:
   ```bash
   GET /api/v1/students/
   # Session cookie is automatically sent with requests
   ```

4. **Logout**:
   ```bash
   POST /api/v1/accounts/auth/logout/
   ```

### CSRF Token Handling

For state-changing requests (POST, PATCH, DELETE), include CSRF token:
```bash
# Get CSRF token from cookies or response headers
X-CSRFToken: <csrf_token>
```

## Base URL

```
http://localhost:8000/api
```

## Student Management Endpoints

### 1. List Students

**Endpoint**: `GET /students/`

**Permissions**: Authenticated users
- Students: List all (data restricted by department)
- Department Admin: List department students
- Registrar/Super Admin: List all

**Query Parameters**:

```
?department__id={id}          # Filter by department
?program__id={id}             # Filter by program
?academic_status={status}     # Filter by status
?is_active={true/false}       # Filter by active status
?admission_year={year}        # Filter by admission year
?current_study_year={year}    # Filter by study year

?search={term}                # Search (registration_number, name, email)
?ordering={field}             # Order by field (default: -created_at)
?limit={n}                    # Pagination limit (default: 20)
?offset={n}                   # Pagination offset (default: 0)
```

**Example Request**:

```bash
curl -X GET 'http://localhost:8000/api/students/?department__id=abc123&academic_status=active&ordering=-registration_number' \
  -H "Authorization: Bearer <token>"
```

**Example Response** (200 OK):

```json
{
  "count": 45,
  "next": "http://localhost:8000/api/students/?offset=20&limit=20",
  "previous": null,
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "registration_number": "STU2024001",
      "first_name": "John",
      "last_name": "Doe",
      "email": "john.doe@example.com",
      "phone_number": "+1234567890",
      "department_name": "Computer Science",
      "program_name": "Bachelor of Science in Computer Science",
      "program_code": "CS-BSC",
      "current_study_year": 2,
      "current_semester": 1,
      "academic_status": "active",
      "status_display": "Active",
      "is_active": true,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### 2. Create Student

**Endpoint**: `POST /students/`

**Permissions**: Department Admin, Registrar, Super Admin

**Request Body**:

```json
{
  "registration_number": "STU2024045",
  "first_name": "Jane",
  "last_name": "Smith",
  "gender": "female",
  "email": "jane.smith@example.com",
  "phone_number": "+1987654321",
  "date_of_birth": "2002-05-15",
  "user_id": "550e8400-e29b-41d4-a716-446655440001",
  "department_id": "550e8400-e29b-41d4-a716-446655440002",
  "program_id": "550e8400-e29b-41d4-a716-446655440003",
  "current_study_year": 1,
  "current_semester": 1,
  "admission_year": 2024,
  "academic_status": "active",
  "enrollment_type": "full_time",
  "is_active": true
}
```

**Example Request**:

```bash
curl -X POST http://localhost:8000/api/students/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "registration_number": "STU2024045",
    "first_name": "Jane",
    "last_name": "Smith",
    "email": "jane.smith@example.com",
    "user_id": "550e8400-e29b-41d4-a716-446655440001",
    "department_id": "550e8400-e29b-41d4-a716-446655440002",
    "program_id": "550e8400-e29b-41d4-a716-446655440003",
    "admission_year": 2024
  }'
```

**Example Response** (201 Created):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440004",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440001",
    "username": "jane.smith",
    "email": "jane.smith@example.com",
    "first_name": "Jane",
    "last_name": "Smith"
  },
  "registration_number": "STU2024045",
  "first_name": "Jane",
  "last_name": "Smith",
  "full_name": "Jane Smith",
  "gender": "female",
  "gender_display": "Female",
  "email": "jane.smith@example.com",
  "phone_number": "+1987654321",
  "date_of_birth": "2002-05-15",
  "faculty_name": null,
  "department": {
    "id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "Computer Science",
    "code": "CS"
  },
  "program": {
    "id": "550e8400-e29b-41d4-a716-446655440003",
    "name": "Bachelor of Science in Computer Science",
    "code": "CS-BSC",
    "duration_years": 4
  },
  "current_study_year": 1,
  "current_semester": 1,
  "admission_year": 2024,
  "academic_status": "active",
  "academic_status_display": "Active",
  "enrollment_type": "full_time",
  "enrollment_type_display": "Full Time",
  "is_active": true,
  "profile_photo": null,
  "academic_year_string": "2024/2025",
  "is_graduated": false,
  "is_suspended": false,
  "can_enroll": true,
  "created_at": "2024-02-15T14:20:00Z",
  "updated_at": "2024-02-15T14:20:00Z"
}
```

**Error Response** (400 Bad Request):

```json
{
  "registration_number": [
    "A student with registration number 'STU2024001' already exists."
  ],
  "email": [
    "A student with email 'exists@example.com' already exists."
  ]
}
```

### 3. Retrieve Student

**Endpoint**: `GET /students/{id}/`

**Permissions**: Student (own), Department Admin (own dept), Registrar, Super Admin

**Example Request**:

```bash
curl -X GET http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/ \
  -H "Authorization: Bearer <token>"
```

**Example Response** (200 OK):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user": { ... },
  "registration_number": "STU2024001",
  "first_name": "John",
  "last_name": "Doe",
  "full_name": "John Doe",
  ... // All fields like in create response
}
```

### 4. Update Student

**Endpoint**: `PUT /students/{id}/`

**Permissions**: Department Admin (own dept), Registrar, Super Admin

**Note**: Cannot change user, department, or program associations

**Example Request**:

```bash
curl -X PUT http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "registration_number": "STU2024001-A",
    "phone_number": "+9876543210",
    "current_study_year": 3,
    "academic_status": "active"
  }'
```

### 5. Partial Update Student

**Endpoint**: `PATCH /students/{id}/`

**Permissions**: Department Admin (own dept), Registrar, Super Admin

**Example Request**:

```bash
curl -X PATCH http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+9876543210"
  }'
```

### 6. Delete Student

**Endpoint**: `DELETE /students/{id}/`

**Permissions**: Registrar, Super Admin

**Example Request**:

```bash
curl -X DELETE http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/ \
  -H "Authorization: Bearer <token>"
```

**Response**: 204 No Content

---

## Student-Specific Endpoints

### 1. My Profile

**Endpoint**: `GET /students/me/`

**Permissions**: Any authenticated student

**Description**: Get logged-in student's own profile

**Example Request**:

```bash
curl -X GET http://localhost:8000/api/students/me/ \
  -H "Authorization: Bearer <student_token>"
```

**Example Response** (200 OK):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "registration_number": "STU2024001",
  "user": { ... },
  "first_name": "John",
  "last_name": "Doe",
  "full_name": "John Doe",
  "email": "john.doe@example.com",
  ... // Complete profile
}
```

### 2. Academic Progress History

**Endpoint**: `GET /students/{id}/academic-progress/`

**Permissions**: Student (own), Department Admin (own dept), Registrar, Super Admin

**Query Parameters**:

```
?academic_status={status}  # Filter by progress status
?academic_year={year}      # Filter by year
?ordering={field}          # Order by field
?limit={n}                 # Pagination limit
?offset={n}                # Pagination offset
```

**Example Request**:

```bash
curl -X GET 'http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/academic-progress/' \
  -H "Authorization: Bearer <token>"
```

**Example Response** (200 OK):

```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440010",
      "student_registration": "STU2024001",
      "academic_year": "2024/2025",
      "study_year": 2,
      "semester": 1,
      "gpa": "3.75",
      "cgpa": "3.82",
      "total_credits": 45,
      "credits_this_semester": 15,
      "academic_status": "good_standing",
      "status_display": "Good Standing",
      "recorded_by_name": "Dr. Jane Admin",
      "created_at": "2024-02-01T10:00:00Z"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440011",
      "student_registration": "STU2024001",
      "academic_year": "2023/2024",
      "study_year": 1,
      "semester": 2,
      "gpa": "3.80",
      "cgpa": "3.85",
      "total_credits": 30,
      "credits_this_semester": 15,
      "academic_status": "good_standing",
      "status_display": "Good Standing",
      "recorded_by_name": "Dr. Jane Admin",
      "created_at": "2024-01-15T10:00:00Z"
    }
  ]
}
```

### 3. Enrollment History

**Endpoint**: `GET /students/{id}/enrollments/`

**Permissions**: Student (own), Department Admin (own dept), Registrar, Super Admin

**Example Request**:

```bash
curl -X GET 'http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/enrollments/' \
  -H "Authorization: Bearer <token>"
```

**Example Response** (200 OK):

```json
{
  "count": 2,
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440020",
      "student_registration": "STU2024001",
      "curriculum_info": {
        "id": "550e8400-e29b-41d4-a716-446655440030",
        "program": "CS-BSC",
        "academic_year": "2024/2025"
      },
      "academic_year": "2024/2025",
      "study_year": 2,
      "semester": 1,
      "enrollment_status": "enrolled",
      "status_display": "Enrolled",
      "enrollment_date": "2024-01-20T09:00:00Z",
      "notes": ""
    }
  ]
}
```

### 4. Curriculum Units

**Endpoint**: `GET /students/{id}/curriculum-units/`

**Permissions**: Student (own), Department Admin, Registrar, Super Admin

**Description**: Get required units for student's current curriculum

**Example Request**:

```bash
curl -X GET http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/curriculum-units/ \
  -H "Authorization: Bearer <token>"
```

**Example Response** (200 OK):

```json
{
  "curriculum": "550e8400-e29b-41d4-a716-446655440030",
  "units": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440031",
      "code": "CS201",
      "name": "Data Structures",
      "is_core": true,
      "is_elective": false,
      "credit_hours": 3
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440032",
      "code": "CS202",
      "name": "Algorithms",
      "is_core": true,
      "is_elective": false,
      "credit_hours": 4
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440033",
      "code": "CS301",
      "name": "Web Development",
      "is_core": false,
      "is_elective": true,
      "credit_hours": 3
    }
  ]
}
```

### 5. Personalized Timetable

**Endpoint**: `GET /students/{id}/timetable/`

**Permissions**: Student (own), Registrar, Super Admin

**Description**: Placeholder for timetable module integration

**Example Request**:

```bash
curl -X GET http://localhost:8000/api/students/550e8400-e29b-41d4-a716-446655440000/timetable/ \
  -H "Authorization: Bearer <token>"
```

**Example Response** (200 OK):

```json
{
  "student_id": "550e8400-e29b-41d4-a716-446655440000",
  "registration_number": "STU2024001",
  "program_id": "550e8400-e29b-41d4-a716-446655440003",
  "program_code": "CS-BSC",
  "department_id": "550e8400-e29b-41d4-a716-446655440002",
  "academic_year": "2024/2025",
  "study_year": 2,
  "semester": 1,
  "curriculum_id": "550e8400-e29b-41d4-a716-446655440030",
  "enrollment_id": "550e8400-e29b-41d4-a716-446655440020",
  "units": [ ... ]
}
```

### 6. Student Statistics

**Endpoint**: `GET /students/statistics/`

**Permissions**: Registrar, Super Admin

**Description**: Get overall student counts by status

**Example Request**:

```bash
curl -X GET http://localhost:8000/api/students/statistics/ \
  -H "Authorization: Bearer <admin_token>"
```

**Example Response** (200 OK):

```json
{
  "total_students": 450,
  "active_students": 420,
  "by_status": {
    "active": 420,
    "inactive": 15,
    "suspended": 8,
    "graduated": 5,
    "withdrawn": 2,
    "on_leave": 0
  }
}
```

---

## Profile Management Endpoints

### Update Own Profile

**Endpoint**: `PUT /profile/me/update/`

**Permissions**: Own student profile

**Allowed Fields**: `first_name`, `last_name`, `phone_number`, `date_of_birth`, `profile_photo`

**Example Request**:

```bash
curl -X PUT http://localhost:8000/api/profile/me/update/ \
  -H "Authorization: Bearer <student_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+1234567890",
    "date_of_birth": "2002-05-15"
  }'
```

---

## Academic Progress Endpoints

### Get Student Academic Progress

**Endpoint**: `GET /academic-progress/`

**Filters**:

```
?student__id={id}
?academic_year={year}
?academic_status={status}
```

**Example Request**:

```bash
curl -X GET 'http://localhost:8000/api/academic-progress/?student__id=550e8400-e29b-41d4-a716-446655440000' \
  -H "Authorization: Bearer <token>"
```

---

## Enrollment Endpoints

### List Enrollments

**Endpoint**: `GET /enrollments/`

**Filters**:

```
?student__id={id}
?curriculum__id={id}
?enrollment_status={status}
```

**Example Request**:

```bash
curl -X GET 'http://localhost:8000/api/enrollments/?enrollment_status=enrolled' \
  -H "Authorization: Bearer <token>"
```

### Withdraw Enrollment

**Endpoint**: `POST /enrollments/{id}/withdraw/`

**Permissions**: Registrar, Super Admin

**Request Body**:

```json
{
  "reason": "Medical leave"
}
```

**Example Request**:

```bash
curl -X POST http://localhost:8000/api/enrollments/550e8400-e29b-41d4-a716-446655440020/withdraw/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Medical leave"}'
```

**Example Response** (200 OK):

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440020",
  "student_registration": "STU2024001",
  "curriculum_info": { ... },
  "academic_year": "2024/2025",
  "study_year": 2,
  "semester": 1,
  "enrollment_status": "withdrawn",
  "status_display": "Withdrawn",
  "enrollment_date": "2024-01-20T09:00:00Z",
  "notes": "Medical leave"
}
```

---

## Error Examples

### 400 Bad Request - Validation Error

```json
{
  "registration_number": [
    "A student with registration number 'STU2024001' already exists."
  ],
  "current_study_year": [
    "Study year cannot exceed program duration of 4 years."
  ]
}
```

### 401 Unauthorized

```json
{
  "detail": "Authentication credentials were not provided."
}
```

### 403 Forbidden

```json
{
  "detail": "You do not have permission to perform this action."
}
```

### 404 Not Found

```json
{
  "detail": "Not found."
}
```

---

## Bulk Operations (Future)

These are planned for future versions:

```
POST /students/bulk-create/           # Create multiple students
POST /students/bulk-update/           # Update multiple students
PATCH /students/bulk-status-change/   # Change status for multiple
```

---

## Filtering & Searching Examples

### Search for student by name

```bash
curl -X GET 'http://localhost:8000/api/students/?search=john' \
  -H "Authorization: Bearer <token>"
```

### Get active students in a department

```bash
curl -X GET 'http://localhost:8000/api/students/?department__id=abc&academic_status=active&is_active=true' \
  -H "Authorization: Bearer <token>"
```

### Get suspended students

```bash
curl -X GET 'http://localhost:8000/api/students/?academic_status=suspended' \
  -H "Authorization: Bearer <token>"
```

### Students by admission year

```bash
curl -X GET 'http://localhost:8000/api/students/?admission_year=2024' \
  -H "Authorization: Bearer <token>"
```

### Students in specific year/semester

```bash
curl -X GET 'http://localhost:8000/api/students/?current_study_year=2&current_semester=1' \
  -H "Authorization: Bearer <token>"
```

---

## Pagination Examples

### First page

```bash
curl -X GET 'http://localhost:8000/api/students/?limit=20&offset=0' \
  -H "Authorization: Bearer <token>"
```

### Next page

```bash
curl -X GET 'http://localhost:8000/api/students/?limit=20&offset=20' \
  -H "Authorization: Bearer <token>"
```

---

## Rate Limiting (Future)

Planned throttle rates:

- **Authenticated users**: 1000 requests/hour
- **Public endpoints**: 100 requests/hour

---

## Versioning

Current API version: `v1`

Future versions will be supported at:
- `/api/v1/students/`
- `/api/v2/students/` (future)

---

## CORS Support

CORS is configured to allow:
- Origins: Configured in settings
- Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS
- Headers: Authorization, Content-Type

---

## Webhooks (Future)

Planned webhook events:

```
student.created
student.updated
student.status_changed
enrollment.created
enrollment.withdrawn
progress.recorded
```

---

## GraphQL Endpoint (Future)

Planned at: `/graphql/`
