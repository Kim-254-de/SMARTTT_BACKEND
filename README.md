# SMARTTT Backend

Django REST API for the SMARTTT timetable and student scheduling platform.

This backend powers authentication, student and lecturer management, timetable uploads, schedule generation, notifications, and the APIs consumed by the frontend application.

## Project overview

- Framework: Django + Django REST Framework
- Database: PostgreSQL
- Auth: JWT via `djangorestframework-simplejwt`
- Storage: local media/static files with WhiteNoise
- Main app modules:
  - `apps/accounts` — users, auth, profile, JWT login/register flows
  - `apps/students` — student records and enrollment data
  - `apps/lecturers` — lecturer profiles and assignments
  - `apps/programs`, `apps/departments`, `apps/rooms`, `apps/units` — academic metadata
  - `apps/timetable` — master timetable uploads and timetable slots
  - `apps/schedule` — personalized timetable generation
  - `apps/courses` — unit and portal integration logic
  - `apps/notifications` — notification APIs and delivery

## Requirements

- Python 3.11+
- PostgreSQL 15+
- pip
- Optional: Docker and Docker Compose

## Quick start

### 1) Create a virtual environment

```bash
cd SMARTTT_BACKEND
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Configure environment variables

The project reads environment variables from the shell or a local `.env` file. At minimum, set:

```bash
export DJANGO_SECRET_KEY="change-me"
export DJANGO_DEBUG="True"
export DJANGO_ALLOWED_HOSTS="127.0.0.1,localhost"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export POSTGRES_DB="smarttt_db"
export POSTGRES_USER="smarttt_user"
export POSTGRES_PASSWORD="smarttt_password"
export CORS_ALLOW_ALL_ORIGINS="True"
```

If you are using the included local Docker database, these values match the defaults in `docker-compose.yml`.

### 4) Create the database

Start PostgreSQL locally or via Docker, then run:

```bash
python manage.py migrate
```

### 5) Run the development server

```bash
python manage.py runserver 0.0.0.0:8000
```

The API will be available at:

- http://127.0.0.1:8000/
- http://127.0.0.1:8000/admin/

## Docker setup

A Docker Compose setup is included for local development:

```bash
docker compose up --build
```

This starts:

- PostgreSQL container on port `5432`
- Django app on port `8000`

## Useful Django commands

Create a superuser:

```bash
python manage.py createsuperuser
```

Collect static files:

```bash
python manage.py collectstatic --noinput
```

Run tests:

```bash
python manage.py test
```

Create migrations after model changes:

```bash
python manage.py makemigrations
python manage.py migrate
```

## API structure

The project exposes API routes under the `api/v1` namespace, including:

- `api/v1/auth/`
- `api/v1/departments/`
- `api/v1/programs/`
- `api/v1/rooms/`
- `api/v1/lecturers/`
- `api/v1/units/`
- `api/v1/students/`
- `api/v1/enrollments/`
- `api/v1/timetable/`
- `api/v1/courses/`
- `api/v1/schedule/`
- `api/v1/notifications/`

## Default settings

The backend uses `config.settings.development` for local development. In production, configure the appropriate settings module and environment variables for your deployment.

## Notes

- The project uses JWT-based auth with Bearer tokens.
- Password hashing is configured to prefer Argon2.
- Media files are stored under `media/` and static files under `staticfiles/`.
- CORS is configurable through `CORS_ALLOW_ALL_ORIGINS` and `CORS_ALLOWED_ORIGINS`.

## Troubleshooting

If Django cannot import the app or database connection fails:

1. Confirm your virtual environment is active.
2. Confirm PostgreSQL is running and the `POSTGRES_*` values match your database.
3. Run `python manage.py check`.
4. Re-run migrations via `python manage.py migrate`.

## Related files

- `manage.py` — Django app entry point
- `config/settings/` — settings modules
- `config/urls.py` — root API routing
- `requirements.txt` — Python dependencies
- `docker-compose.yml` — local database and app orchestration
