"""
AdatTracker Pro - Configuration & Environment Loader
Loads environment variables and sets sensible security defaults for Local and Production (Oracle Cloud / Cloudflare).
"""

import os
import secrets
from pathlib import Path

# Try loading .env file if available
try:
    from dotenv import load_dotenv
    # Search for .env in current directory, backend dir, and parent dir
    env_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env"
    ]
    for ep in env_paths:
        if ep.exists():
            load_dotenv(dotenv_path=ep)
            break
except ImportError:
    pass

# Paths
BASE_DIR = Path(__file__).resolve().parent

if "DATA_DIR" in os.environ:
    DATA_DIR = Path(os.environ["DATA_DIR"])
elif (BASE_DIR / "data").exists():
    DATA_DIR = BASE_DIR / "data"
elif (BASE_DIR.parent / "data").exists():
    DATA_DIR = BASE_DIR.parent / "data"
else:
    DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "adattracker.db"

# Determine static HTML path (check all potential locations)
potential_paths = [
    BASE_DIR / "habit_tracker.html",
    BASE_DIR / "frontend" / "index.html",
    BASE_DIR / "frontend" / "habit_tracker.html",
    BASE_DIR.parent / "frontend" / "index.html",
    BASE_DIR.parent / "habit_tracker.html",
    Path("/app/habit_tracker.html"),
    Path("/app/frontend/index.html")
]
STATIC_HTML_PATH = BASE_DIR / "habit_tracker.html"
for p in potential_paths:
    if p.exists():
        STATIC_HTML_PATH = p
        break

# Environment
APP_ENV = os.environ.get("APP_ENV", "local").lower().strip()
IS_PRODUCTION = APP_ENV == "production"

# Network
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")
BASE_URL = os.environ.get("BASE_URL", f"http://localhost:{PORT}").rstrip("/")

# Secret Key (used for OTP HMAC & CSRF)
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ValueError("CRITICAL: SECRET_KEY environment variable MUST be set in production!")
    # Deterministic fallback for dev if not provided
    SECRET_KEY = "adattracker_dev_secret_key_change_in_production_32bytes"

# CORS Configuration
raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
if raw_origins:
    ALLOWED_ORIGINS = [orig.strip() for orig in raw_origins.split(",") if orig.strip()]
else:
    ALLOWED_ORIGINS = [
        f"http://localhost:{PORT}",
        f"http://127.0.0.1:{PORT}",
        f"http://localhost:3000",
        BASE_URL
    ]
# Deduplicate while preserving order
ALLOWED_ORIGINS = list(dict.fromkeys(ALLOWED_ORIGINS))

# Session & Cookie Security
SESSION_COOKIE_NAME = "at_session"
SESSION_COOKIE_SECURE = IS_PRODUCTION or os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", 30))
SESSION_MAX_AGE_SECONDS = SESSION_MAX_AGE_DAYS * 24 * 3600

# OTP & Rate Limiting Rules
OTP_EXPIRY_MINUTES = 10
MAX_OTP_ATTEMPTS = 5
MAX_OTP_REQUESTS_EMAIL_15MIN = 3
MAX_OTP_REQUESTS_IP_15MIN = 5
MAX_PAYLOAD_BYTES = 512 * 1024  # 512 KB

# Email Dispatcher
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "console").lower().strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_TLS = os.environ.get("SMTP_TLS", "true").lower() == "true"
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@adattracker.local")
FROM_NAME = os.environ.get("FROM_NAME", "AdatTracker Pro")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
