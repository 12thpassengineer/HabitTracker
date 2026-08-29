"""
AdatTracker Pro - Security & Cryptographic Engine
Handles OTP generation/hashing, session token management, CSRF validation, IP resolution, and rate limiting.
"""

import hmac
import hashlib
import secrets
import datetime
import re
from typing import Tuple, Optional
from fastapi import Request

from config import (
    SECRET_KEY,
    MAX_OTP_REQUESTS_EMAIL_15MIN,
    MAX_OTP_REQUESTS_IP_15MIN,
    OTP_EXPIRY_MINUTES
)
import database as db

# ═══════════════════════════════════════════════════════
# OTP CRYPTOGRAPHY
# ═══════════════════════════════════════════════════════
def generate_otp_code() -> str:
    """Generates a cryptographically random 6-digit OTP."""
    code = secrets.randbelow(1_000_000)
    return f"{code:06d}"

def hash_otp_code(otp: str, email: str) -> str:
    """Hashes the 6-digit OTP code using HMAC-SHA256 salted with the server SECRET_KEY and user email."""
    message = f"{otp}:{email.strip().lower()}".encode("utf-8")
    key = SECRET_KEY.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()

def verify_otp_code(input_otp: str, email: str, stored_hash: str) -> bool:
    """Performs a constant-time comparison of the provided OTP against the stored hash."""
    calculated_hash = hash_otp_code(input_otp, email)
    return hmac.compare_digest(calculated_hash, stored_hash)

# ═══════════════════════════════════════════════════════
# SESSION & CSRF TOKENS
# ═══════════════════════════════════════════════════════
def generate_session_id() -> str:
    """Generates a secure 256-bit session token."""
    return f"ats_{secrets.token_urlsafe(32)}"

def generate_csrf_token() -> str:
    """Generates a random CSRF token."""
    return f"csrf_{secrets.token_urlsafe(24)}"

def verify_csrf_token(provided_token: Optional[str], session_csrf_token: Optional[str]) -> bool:
    """Constant-time comparison for CSRF tokens."""
    if not provided_token or not session_csrf_token:
        return False
    return hmac.compare_digest(provided_token.strip(), session_csrf_token.strip())

# ═══════════════════════════════════════════════════════
# CLIENT IP RESOLUTION (Cloudflare Tunnel Aware)
# ═══════════════════════════════════════════════════════
def get_client_ip(request: Request) -> str:
    """
    Extracts client IP prioritizing Cloudflare headers, then X-Forwarded-For, then direct connection.
    Prevents Cloudflare Tunnel IP from masking real client IPs for rate limiting.
    """
    # 1. Cloudflare Tunnel Header
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and is_valid_ip(cf_ip.strip()):
        return cf_ip.strip()

    # 2. X-Real-IP
    real_ip = request.headers.get("x-real-ip")
    if real_ip and is_valid_ip(real_ip.strip()):
        return real_ip.strip()

    # 3. X-Forwarded-For (take the first / client IP in chain)
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first_ip = xff.split(",")[0].strip()
        if is_valid_ip(first_ip):
            return first_ip

    # 4. Direct socket connection IP
    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"

def is_valid_ip(ip: str) -> bool:
    """Basic validation for IPv4 or IPv6 string."""
    return bool(re.match(r"^[\d\.:a-fA-F]+$", ip))

# ═══════════════════════════════════════════════════════
# RATE LIMITING ENGINE
# ═══════════════════════════════════════════════════════
def check_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int,
    cooldown_seconds: int = 900
) -> Tuple[bool, int]:
    """
    Database-backed rate limiter.
    Returns: (is_allowed: bool, retry_after_seconds: int)
    """
    now = datetime.datetime.utcnow()
    record = db.get_rate_limit(key)

    if not record:
        window_start_iso = now.isoformat()
        db.set_rate_limit(key, 1, window_start_iso, None)
        return True, 0

    # Check if currently blocked by cooldown
    if record["blocked_until"]:
        try:
            blocked_until = datetime.datetime.fromisoformat(record["blocked_until"])
            if blocked_until > now:
                retry_after = int((blocked_until - now).total_seconds()) + 1
                return False, max(1, retry_after)
        except ValueError:
            pass

    # Check if window has expired
    try:
        window_start = datetime.datetime.fromisoformat(record["window_start"])
    except ValueError:
        window_start = now

    elapsed = (now - window_start).total_seconds()

    if elapsed > window_seconds:
        # Reset window
        db.set_rate_limit(key, 1, now.isoformat(), None)
        return True, 0

    # Within window - check attempts
    current_attempts = record["attempts"] + 1

    if current_attempts > max_requests:
        # Block client
        blocked_until_iso = (now + datetime.timedelta(seconds=cooldown_seconds)).isoformat()
        db.set_rate_limit(key, current_attempts, record["window_start"], blocked_until_iso)
        return False, cooldown_seconds

    # Increment attempts
    db.set_rate_limit(key, current_attempts, record["window_start"], None)
    return True, 0

# ═══════════════════════════════════════════════════════
# INPUT VALIDATION
# ═══════════════════════════════════════════════════════
def validate_username(username: str) -> Tuple[bool, str]:
    """Validates username (2-30 characters, alphanumeric, underscores, hyphens)."""
    clean = username.strip()
    if len(clean) < 2:
        return False, "Username must be at least 2 characters long."
    if len(clean) > 30:
        return False, "Username cannot exceed 30 characters."
    if not re.match(r"^[a-zA-Z0-9_-]+$", clean):
        return False, "Username can only contain letters, numbers, hyphens, and underscores."
    return True, clean.lower()

def validate_email(email: str) -> Tuple[bool, str]:
    """Validates email format."""
    clean = email.strip().lower()
    if len(clean) < 5 or len(clean) > 100:
        return False, "Please provide a valid email address."
    # Standard RFC-compliant email regex
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(pattern, clean):
        return False, "Invalid email address format."
    return True, clean
