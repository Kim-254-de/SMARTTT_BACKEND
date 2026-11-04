# Gaps between frontend and backend

A two-way list between the frontend lead and the backend team. Each side adds what it finds;
neither side deletes the other's entries. How to use it is in `CLAUDE.md`.

Entry format:

```
### B-<n> · <High|Medium|Low> · <one-line title>
- **Raised:** <YYYY-MM-DD>, <who>   **Status:** open | in progress | done (<commit>) | won't do (<why>)
- **Seen:** what is missing or different, with file paths, endpoints, commits.
- **Why it matters:** which screen or user is affected.
- **Done when:** the check that closes it.
```

Use `B-` for items the backend should act on, and `F-` for items the frontend should act on.

---

## For the backend team (raised by the frontend)

### B-1 · Medium · The Generator's term list and SMARTTT import call endpoints `main` doesn't have
- **Raised:** 2026-10-25, frontend (Wayler)   **Status:** open
- **Seen:** Timetable-Generator `origin/main` (`backend/app/clients/smarttt.py`) calls
  `GET /api/v1/integrations/generator/terms/` (`routes.py:128`) and `GET .../snapshot/`
  (`services/setup.py:288`). SMARTTT `origin/main` (`2e6903c`) only serves `generator/publish/`
  and `generator/publish/<int:version>/`. Both are on the unmerged
  `origin/feature/timetabling-integrations` (`b559290`). Sign-in no longer needs SMARTTT: the
  Generator now signs the timetabling office in through Smart Attendance (`62533da`).
- **Why it matters:** in the Director's Generator UI, the list of SMARTTT terms and
  "Import from SMARTTT" (rooms and master data) fail against `main`.
- **Done when:** `terms/` and `snapshot/` are on `main`, or the Generator stops calling them
  and this file says what replaces them.

### B-2 · Medium · Exams: nothing in SMARTTT yet
- **Raised:** 2026-10-25, frontend (Wayler)   **Status:** open
- **Seen:** the list in Timetable-Allocator `README.md` → "Exams: needs from SMARTTT and
  Smart Attendance" is not built on `origin/main`: there's no exam publication endpoint, no
  term `mode` (`teaching | exams`) with the Generator's `exam-mode` endpoints, no exam view
  per student or lecturer, and no exam push to Attendance.
- **Why it matters:** the SMARTTT app needs an **Exams** tab (shown first during the exam
  period) and lecturers need to see their invigilation duties. The Generator UI already has
  an exam switch (`frontend/src/components/ExamSwitch.tsx`) waiting for this.
- **Done when:** the endpoints exist, and their response shapes (an example JSON each) are
  added below under "For the frontend", so the app screens can be built against them.

### B-3 · High · Rooms can be reserved for health only: let the admin set up other reserved groups
- **Raised:** 2026-11-03, frontend (Wayler)   **Status:** open
- **Seen:** a room has one yes/no field for this, `health_unit`
  (`apps/rooms/models/room.py:33`). It is merged in `apps/rooms/services/room_merge.py:45`,
  and sent to the Generator in `apps/integrations/unit_enrolment.py:257`. There is nowhere to
  say "these rooms belong to another course".
  **Example to test against:** the university starts a new Bachelor of Engineering. Its papers
  (codes starting `BENG`) must be sat only in the engineering workshops, W1 and W2, and no
  other course's paper may be put in W1 or W2.
- **What we ask for:** a **venue group** that a room can belong to, in place of the yes/no
  `health_unit`. The admin creates groups and puts rooms in them; health becomes the first
  group, and the migration moves every room with `health_unit = true` into it. The shape is
  yours; one way:
  ```
  GET  /api/v1/integrations/admin/rooms/groups/  -> { "groups": [ { "id": 1, "code": "health", "name": "Health unit", "rooms": 6 } ] }
  POST /api/v1/integrations/admin/rooms/groups/  { "name": "Engineering workshops" }  -> the group
  PATCH /api/v1/integrations/admin/rooms/:id/    { "group": "engineering" }   (null takes it out)
  rooms in lists and in the Generator's room data: "group": "health" | "engineering" | null
  ```
  Please keep `health_unit` in responses for one release (true when `group == "health"`), so
  the Generator and the Attendance Venues page keep working while they switch over. Merging
  rooms keeps the group of the room kept, and refuses to merge rooms from different groups.
- **Why it matters:** without it, the Generator can't keep a new course's papers in its own
  rooms (Timetable-Generator `GAPS.md` B-4), and the Venues page can only offer the health switch.
- **Done when:** the example works end to end: W1 and W2 are in "Engineering workshops"; the
  Generator receives `"group": "engineering"` for them; existing health rooms have
  `"group": "health"` and `health_unit: true`; the shapes are written under "For the
  frontend team" in Smart Attendance's `GAPS.md`.

### Checked and fine (2026-10-25)
- Every path the Flutter app calls exists on `origin/main`.
- Every SMARTTT path that the Attendance admin console proxies
  (`/api/v1/integrations/admin/*`) exists on `origin/main`.
- `generator/publish/` already takes `lecturer_staff_number` and `unit_code`.

---

## For the frontend team (raised by the backend)

<!-- Add F-<n> entries here: endpoints or fields added, renamed or removed; changed error codes,
     enums, auth or limits; anything a screen now shows wrongly; anything you noticed in the UI. -->

_Nothing yet._
