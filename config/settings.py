"""Project settings."""
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-route-fuel-optimizer-secret")
DEBUG = os.getenv("DJANGO_DEBUG", "1").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "route_planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

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
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ROUTE_PLANNER = {
    "OSRM_BASE_URL": os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org"),
    "NOMINATIM_BASE_URL": os.getenv(
        "NOMINATIM_BASE_URL",
        "https://nominatim.openstreetmap.org",
    ),
    "NOMINATIM_USER_AGENT": os.getenv(
        "NOMINATIM_USER_AGENT",
        "route-fuel-optimizer/1.0",
    ),
    "NOMINATIM_EMAIL": os.getenv("NOMINATIM_EMAIL", "route-fuel-optimizer@example.com"),
    "REQUEST_TIMEOUT_SECONDS": float(os.getenv("REQUEST_TIMEOUT_SECONDS", "12")),
    "MAX_RANGE_MILES": float(os.getenv("MAX_RANGE_MILES", "500")),
    "MPG": float(os.getenv("MPG", "10")),
    "CORRIDOR_MILES": float(os.getenv("CORRIDOR_MILES", "25")),
    "STARTING_RANGE_MILES": float(os.getenv("STARTING_RANGE_MILES", "500")),
}
