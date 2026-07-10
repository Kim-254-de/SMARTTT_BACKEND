# SMARTTT Backend — Clean Rewrite

## Apps
- `apps/accounts`   — User model, JWT auth (register, login, profile)
- `apps/core`       — Shared BaseModel, Faculty, Department, Program, Room, Lecturer
- `apps/timetable`  — AcademicTerm, TimetableSlot (master timetable), upload pipeline
- `apps/courses`    — Unit model, portal scraper, StudentUnit (enrolled units per student)
- `apps/schedule`   — Personalised timetable generation and serving

## Flow
1. Student registers → User + Student profile created
2. Student goes to "My Courses" → posts portal credentials once
3. Backend scrapes portal → saves StudentUnit records → discards credentials
4. Admin uploads Excel master timetable → TimetableSlot records created
5. Student hits /schedule/me/ → matched against master, personalised timetable returned
