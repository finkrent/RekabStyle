"""
Django settings for the online shop backend.

All sensitive values are read from environment variables (loaded from .env).
See .env.example and docs/configuration.md.
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default="False"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is not set. See docs/configuration.md.")

DEBUG = _env_bool("DJANGO_DEBUG", "False")
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "accounts",
    "products",
    "orders",
    "payments",
    "notifications",
    "corsheaders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "corsheaders.middleware.CorsMiddleware",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DATABASE_NAME", ""),
        "USER": os.environ.get("DATABASE_USER", ""),
        "PASSWORD": os.environ.get("DATABASE_PASSWORD", ""),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# The refresh token is delivered to the browser as an httpOnly cookie (the
# SPA only ever holds the short-lived access token in memory). Same-domain
# deployment: SameSite=Strict needs no CORS/CSRF juggling and blocks the
# cookie from ever being attached to cross-site requests.
JWT_REFRESH_COOKIE = {
    "NAME": os.environ.get("JWT_REFRESH_COOKIE_NAME", "refresh_token"),
    "PATH": "/api/v1/accounts/",
    "MAX_AGE": 60 * 60 * 24 * 30,  # matches REFRESH_TOKEN_LIFETIME
    "SECURE": not DEBUG,
    "HTTPONLY": True,
    "SAMESITE": "Strict",
}
OTP_DEBUG_RETURN_CODE = _env_bool("OTP_DEBUG_RETURN_CODE", "False")

# --- OTP configuration ---
OTP = {
    "LENGTH": _env_int("OTP_LENGTH", 6),
    "EXPIRE_SECONDS": _env_int("OTP_EXPIRE_SECONDS", 180),
    "COOLDOWN_SECONDS": _env_int("OTP_COOLDOWN_SECONDS", 90),
    "MAX_REQUESTS_PER_HOUR": _env_int("OTP_MAX_REQUESTS_PER_HOUR", 20),
    "MAX_VERIFY_ATTEMPTS": _env_int("OTP_MAX_VERIFY_ATTEMPTS", 5),
}

# --- Kavenegar (SMS) ---
KAVENEGAR_API_KEY = os.environ.get("KAVENEGAR_API_KEY", "")
KAVENEGAR_SENDER = os.environ.get("KAVENEGAR_SENDER", "")
ADMIN_PHONE_NUMBER = os.environ.get("ADMIN_PHONE_NUMBER", "")

# --- Zibal (payment) ---
ZIBAL = {
    "MERCHANT": os.environ.get("ZIBAL_MERCHANT", "zibal"),
    "BASE_URL": os.environ.get("ZIBAL_BASE_URL", "https://gateway.zibal.ir"),
    "CALLBACK_URL": os.environ.get("ZIBAL_CALLBACK_URL", ""),
}

# Optional frontend page users are redirected to after payment.
FRONTEND_PAYMENT_RESULT_URL = os.environ.get("FRONTEND_PAYMENT_RESULT_URL", "")

# --- Custom design orders ---
CUSTOM_DESIGN = {
    # Surcharge applied on top of each product's unit price (percent).
    "SURCHARGE_PERCENT": _env_int("CUSTOM_DESIGN_SURCHARGE_PERCENT", 30),
    # Uploaded design images per order.
    "MAX_IMAGES": 3,
    # Per-file size cap (bytes).
    "MAX_IMAGE_BYTES": _env_int("CUSTOM_DESIGN_MAX_IMAGE_BYTES", 5 * 1024 * 1024),
    # Per-image dimension cap (decompression-bomb guard).
    "MAX_IMAGE_DIMENSION": 6000,
    # Internal formats accepted after content sniffing (Pillow names).
    # GIF/SVG intentionally excluded.
    "ALLOWED_FORMATS": ("JPEG", "PNG", "WEBP"),
    "DESCRIPTION_MAX_LENGTH": 2000,
}

# Multipart body limits (defense in depth; the per-image cap above is the
# primary limit). Sized for 3 images + form fields.
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

# --- Production security hardening ---
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
