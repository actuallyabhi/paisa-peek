import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _secret_key():
    """SECRET_KEY from env, else generated once and kept in the data dir."""
    if key := os.environ.get("SECRET_KEY"):
        return key
    path = DATA_DIR / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(50))
        path.chmod(0o600)
    return path.read_text().strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("DEBUG") == "1"
# DOMAIN (e.g. "paisapeek.example.com") = served over HTTPS there: hosts, CSRF origin and secure cookies follow from it.
DOMAIN = os.environ.get("DOMAIN", "").strip()
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", f"{DOMAIN},localhost,127.0.0.1" if DOMAIN else "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o] + (
    [f"https://{DOMAIN}"] if DOMAIN else [])
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = bool(DOMAIN)
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90  # stay logged in on your phone for 90 days

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ledger",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",  # picks the language: switcher cookie, else the browser's
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
                "ledger.views.pending_count",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            # IMMEDIATE makes atomic() take the write lock up front, so ingest dedupe is safe across gunicorn workers.
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# Languages: standard Django i18n. Strings are marked with {% translate %} / gettext, extracted with
# `manage.py makemessages -l <code>` into ledger/locale/<code>/LC_MESSAGES/django.po, compiled with compilemessages.
# Add a language = add it here + its .po file.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("hi", "हिन्दी")]
LOCALE_PATHS = [BASE_DIR / "ledger" / "locale"]
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365
TIME_ZONE = os.environ.get("TZ", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

# CSV import review posts ~11 fields per row; Django's default cap of 1000 fields would stop at ~90 rows.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 15000

STATIC_URL = "static/"
WHITENOISE_MIMETYPES = {".webmanifest": "application/manifest+json"}  # PWA installs expect this type
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Optional LLM for ramble parsing: any OpenAI-compatible endpoint. Unset LLM_MODEL = built-in heuristic parser.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")  # Ollama
LLM_MODEL = os.environ.get("LLM_MODEL", "")  # e.g. qwen2.5:7b
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))

# Web Push "subject": a mailto: or https: contact the push services can reach you at (Apple rejects placeholders).
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
