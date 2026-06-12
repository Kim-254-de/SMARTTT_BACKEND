import os
import dj_database_url
from datetime import timedelta
from pathlib import Path

# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / '.env'

if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)
else:
    # In production/Render, variables are usually injected directly into the environment
    pass

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-dev-secret-key")
DEBUG = False
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1, smarttt-backend-n44z.onrender.com, localhost").split(",")

INSTALLED_APPS = [
	"django.contrib.admin",
	"django.contrib.auth",
	"django.contrib.contenttypes",
	"django.contrib.sessions",
	"django.contrib.messages",
	"django.contrib.staticfiles",
	"corsheaders",
	"rest_framework",
	"rest_framework_simplejwt.token_blacklist",
	"django_filters",
	"apps.common",
	"apps.accounts",
	"apps.students",
	"apps.lecturers",
	"apps.departments",
	"apps.programs",
	"apps.units",
	"apps.curriculum",
	"apps.personalization",
	"apps.timetable",
	"apps.uploads",
	"apps.enrollments",
	"apps.rooms",
	"apps.analytics",
]

MIDDLEWARE = [
	"django.middleware.security.SecurityMiddleware",
	"whitenoise.middleware.WhiteNoiseMiddleware",
	"corsheaders.middleware.CorsMiddleware",
	"django.contrib.sessions.middleware.SessionMiddleware",
	"django.middleware.common.CommonMiddleware",
	"django.middleware.csrf.CsrfViewMiddleware",
	"django.contrib.auth.middleware.AuthenticationMiddleware",
	"django.contrib.messages.middleware.MessageMiddleware",
	"django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
	{
		"BACKEND": "django.template.backends.django.DjangoTemplates",
		"DIRS": [],
		"APP_DIRS": True,
		"OPTIONS": {
			"context_processors": [
				"django.template.context_processors.request",
				"django.contrib.auth.context_processors.auth",
				"django.contrib.messages.context_processors.messages",
			],
		},
	},
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    'default': dj_database_url.config(
        default=f"postgres://{os.getenv('POSTGRES_USER', 'smarttt_user')}:{os.getenv('POSTGRES_PASSWORD', 'smarttt_password')}@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'smarttt_db')}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
	{"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
	{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
	{"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
	{"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


def env_list(name, default=""):
	value = os.getenv(name, default)
	if not value:
		return []
	return [item.strip() for item in value.split(",") if item.strip()]

REST_FRAMEWORK = {
	"DEFAULT_AUTHENTICATION_CLASSES": (
		"rest_framework_simplejwt.authentication.JWTAuthentication",
	),
	"DEFAULT_PERMISSION_CLASSES": (
		"rest_framework.permissions.IsAuthenticated",
	),
	"DEFAULT_FILTER_BACKENDS": (
		"django_filters.rest_framework.DjangoFilterBackend",
		"rest_framework.filters.SearchFilter",
		"rest_framework.filters.OrderingFilter",
	),
	"DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
	"PAGE_SIZE": 25,
}

SIMPLE_JWT = {
	"ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
	"REFRESH_TOKEN_LIFETIME": timedelta(days=7),
	"ROTATE_REFRESH_TOKENS": True,
	"BLACKLIST_AFTER_ROTATION": True,
	"AUTH_HEADER_TYPES": ("Bearer",),
}

CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "False") == "True"
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
