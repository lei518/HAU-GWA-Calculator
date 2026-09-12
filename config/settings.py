from pathlib import Path
import os
import urllib.parse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = [x for x in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if x]
if DEBUG:
    ALLOWED_HOSTS += ["127.0.0.1", "localhost"]

# Render injects the service's public hostname. Without this the first
# request to the deployed site fails with DisallowedHost, because
# ALLOWED_HOSTS is empty whenever DEBUG is False.
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)

# Render terminates TLS at its proxy and forwards the request over plain
# HTTP. Without this Django thinks the connection is insecure, so its CSRF
# origin check compares an https:// Origin against an http:// host and
# rejects every POST -- login, saving scores, asking the assistant.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS if host not in ("127.0.0.1", "localhost")]

# Production hardening. Gated on DEBUG so local development over plain HTTP
# still works -- secure cookies would otherwise never be sent to 127.0.0.1
# and every login would silently fail.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "subjects",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Must sit directly after SecurityMiddleware. Without it the deployed
    # site loads with no CSS or JavaScript at all.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

WSGI_APPLICATION = "config.wsgi.application"

if os.getenv("DATABASE_URL"):
    u = urllib.parse.urlparse(os.environ["DATABASE_URL"])
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": u.username,
        "PASSWORD": u.password,
        "HOST": u.hostname,
        "PORT": u.port or 5432,
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3",
                             "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Compressed, but deliberately NOT the manifest variant: templates link
# /static/css/app.css?v=N directly rather than through {% static %}, and
# manifest storage renames files to app.<hash>.css, which those hard-coded
# paths would not find. The ?v= query already handles cache busting.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# AI Grade Assistant (Gemini). Read server-side only -- never exposed to
# templates/JS. Empty string (not an exception) when unset, so the app can
# start normally and the assistant can fail gracefully per-request instead.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# gemini-2.5-flash was retired for new API keys (confirmed via a live 404
# from the API itself). Of the currently available models, gemini-3.1-flash-lite
# was the most reliable in live testing against this project's key (6/6
# successful calls, ~1-3s latency) -- the newer non-lite flash tiers
# (3.6/3.8) returned intermittent 5xx/400 errors under current load.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")