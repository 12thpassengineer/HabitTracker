"""
AdatTracker Pro - High-Performance, Hardened FastAPI Backend Server
Implements Passwordless Email OTP, HttpOnly Cookie Sessions, CSRF Protection,
Strict User Data Isolation, Rate Limiting, and Security Headers.

P0/P1 Fixes Applied:
 - OTP purpose enforced (signup OTP cannot verify login and vice versa)
 - OTP consumption is atomic (race condition prevented)
 - CSRF protection on /api/auth/logout (P1 #12)
 - Rate limiting uses atomic DB operations (P1 #13)
"""

import sys
import os
import json
import datetime
from pathlib import Path

# Ensure current and backend directory are in sys.path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
BACKEND_SUBDIR = CURRENT_DIR / "backend"
if BACKEND_SUBDIR.exists() and str(BACKEND_SUBDIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_SUBDIR))

from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field

# Local modules
from config import (
    PORT,
    HOST,
    APP_ENV,
    IS_PRODUCTION,
    ALLOWED_ORIGINS,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_HTTPONLY,
    SESSION_MAX_AGE_SECONDS,
    OTP_EXPIRY_MINUTES,
    MAX_OTP_ATTEMPTS,
    MAX_OTP_REQUESTS_EMAIL_15MIN,
    MAX_OTP_REQUESTS_IP_15MIN,
    OTP_COOLDOWN_SECONDS,
    MAX_PAYLOAD_BYTES,
    STATIC_HTML_PATH,
    DB_PATH
)
import database as db
import security
import email_service
import payment_service


# ═══════════════════════════════════════════════════════
# LIFESPAN & APPLICATION STARTUP
# ═══════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite WAL database and schema
    db.init_db()
    print(f"🔒 AdatTracker Pro started in [{APP_ENV.upper()}] mode")
    print(f"📁 Database: {DB_PATH}")
    print(f"🌐 Allowed CORS Origins: {ALLOWED_ORIGINS}")
    yield

app = FastAPI(
    title="AdatTracker Pro",
    version="2.5.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None,
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
    lifespan=lifespan
)

# ═══════════════════════════════════════════════════════
# SECURITY MIDDLEWARE
# ═══════════════════════════════════════════════════════
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Payload Size Check
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_PAYLOAD_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Payload too large. Maximum allowed size is 512 KB."}
                    )
            except ValueError:
                pass

        # 2. Block direct access to database files or private paths
        path = request.url.path.lower()
        if any(path.endswith(ext) for ext in [".db", ".sqlite", ".sqlite3", ".env", ".service"]):
            return JSONResponse(status_code=403, content={"detail": "Access forbidden."})

        response = await call_next(request)

        # 3. Inject Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # Content Security Policy (allows Tailwind CDN, Google Fonts, Canvas-Confetti, Chart.js)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Strict CORS configuration (Never wildcard '*' with credentials)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Accept"],
)

# ═══════════════════════════════════════════════════════
# REQUEST SCHEMAS (Strict Pydantic Validation)
# ═══════════════════════════════════════════════════════
class SendOtpRequest(BaseModel):
    purpose: Optional[str] = Field("auth", pattern="^(signup|login|auth)$")
    email: Optional[str] = Field(None, max_length=100)
    username: Optional[str] = Field(None, max_length=30)
    login_id: Optional[str] = Field(None, max_length=100)  # username or email

class VerifyOtpRequest(BaseModel):
    email: str = Field(..., max_length=100)
    otp: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")
    purpose: Optional[str] = Field("auth", pattern="^(signup|login|auth)$")
    username: Optional[str] = Field(None, max_length=30)
    phone: Optional[str] = Field(None, max_length=25)

class UpdateProfileRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=2, max_length=30)
    phone: Optional[str] = Field(None, max_length=25)

# ═══════════════════════════════════════════════════════
# AUTHENTICATION DEPENDENCY (Session Cookie Resolver)
# ═══════════════════════════════════════════════════════
async def get_current_session(request: Request) -> Dict[str, Any]:
    """Resolves authenticated user from HttpOnly server-side session cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")

    return session

async def require_active_subscription(session: Dict[str, Any] = Depends(get_current_session)) -> Dict[str, Any]:
    """
    Validates that the authenticated user has an active subscription.
    When BILLING_ENABLED is False (self-hosted / local), always permits access.
    Allowed statuses: 'active', 'pending' (grace period during automated retries).
    """
    if not payment_service.is_billing_enabled():
        return session

    user_id = session["user_id"]
    sub = db.get_subscription_by_user_id(user_id)
    status = sub["status"] if sub else "inactive"

    if status in ("active", "pending"):
        return session

    raise HTTPException(
        status_code=402,
        detail="Subscription required. Please subscribe or renew your plan to access habit data."
    )


# ═══════════════════════════════════════════════════════
# SYSTEM & STATIC ENDPOINTS
# ═══════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    if STATIC_HTML_PATH.exists():
        return FileResponse(str(STATIC_HTML_PATH), media_type="text/html")
    return HTMLResponse("<h1>AdatTracker Pro</h1><p>Frontend file not found.</p>", status_code=404)

@app.get("/health")
async def health_check():
    """Simple health check without disclosing private database or system paths."""
    return {"status": "ok"}

# ═══════════════════════════════════════════════════════
# AUTHENTICATION ENDPOINTS
# ═══════════════════════════════════════════════════════
@app.post("/api/auth/send-otp")
async def api_send_otp(req: SendOtpRequest, request: Request):
    """
    Step 1: Validates the identity, generates a single-use 6-digit OTP,
    stores it hashed (HMAC-SHA256), and sends it via the configured email backend.
    Enforces IP and per-account rate limits.
    """
    client_ip = security.get_client_ip(request)

    # 1. IP Rate Limiting (atomic)
    ip_key = f"otp_ip:{client_ip}"
    allowed, retry_after = db.increment_rate_limit_atomic(
        ip_key, window_seconds=900, max_requests=MAX_OTP_REQUESTS_IP_15MIN,
        cooldown_seconds=OTP_COOLDOWN_SECONDS
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many OTP requests from this IP. Please wait {retry_after} seconds."
        )

    target_email = ""
    target_username = ""

    # Unified Passwordless Flow (or explicit legacy signup/login)
    input_str = (req.email or req.login_id or "").strip()
    if not input_str:
        raise HTTPException(status_code=400, detail="Please provide your email address.")

    if "@" in input_str:
        valid_e, clean_email = security.validate_email(input_str)
        if not valid_e:
            raise HTTPException(status_code=400, detail=clean_email)
        target_email = clean_email
        existing_user = db.get_user_by_email(clean_email)
        if existing_user:
            target_username = existing_user["username"]
    else:
        # User typed a username
        user = db.get_user_by_username(input_str)
        if user and user.get("email"):
            target_email = user["email"]
            target_username = user["username"]
        else:
            # Return anti-enumeration success
            return {
                "success": True,
                "email": input_str,
                "message": f"Verification code sent to {input_str}."
            }

    # 2. Email Rate Limiting (atomic)
    email_key = f"otp_email:{target_email}"
    allowed_email, retry_after_email = db.increment_rate_limit_atomic(
        email_key, window_seconds=900, max_requests=MAX_OTP_REQUESTS_EMAIL_15MIN,
        cooldown_seconds=OTP_COOLDOWN_SECONDS
    )
    if not allowed_email:
        raise HTTPException(
            status_code=429,
            detail=f"Too many OTP requests for this account. Please wait {retry_after_email} seconds."
        )

    # 3. Generate and Store Hashed OTP
    otp_code = security.generate_otp_code()
    otp_hash = security.hash_otp_code(otp_code, target_email)
    expires_at = (datetime.datetime.utcnow() + datetime.timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()
    purpose_to_store = req.purpose or "auth"

    db.store_otp(target_email, otp_hash, purpose_to_store, expires_at, client_ip)

    # 4. Dispatch Email
    sent, err_msg = email_service.send_otp_email(target_email, otp_code, target_username, purpose_to_store)
    if not sent:
        raise HTTPException(status_code=500, detail="Could not deliver verification email. Please try again.")

    return {
        "success": True,
        "email": target_email,
        "message": f"Verification code sent to {target_email}."
    }

@app.post("/api/auth/verify-otp")
async def api_verify_otp(req: VerifyOtpRequest, request: Request, response: Response):
    """
    Step 2: Verifies 6-digit OTP.
    - If user exists: logs in immediately.
    - If user is new: automatically sets up initial account and flags `is_new_user: true`
      so frontend can present optional display name and phone number prompt.
    """
    client_ip = security.get_client_ip(request)
    user_agent = request.headers.get("user-agent", "Unknown")[:200]

    valid_e, clean_email = security.validate_email(req.email)
    if not valid_e:
        raise HTTPException(status_code=400, detail=clean_email)

    active_otps = db.get_active_otps_for_email(clean_email, purpose=req.purpose if req.purpose != "auth" else None)
    if not active_otps:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code. Please request a new one.")

    # Match against active unexpired OTP
    matched_otp = None
    for otp_rec in active_otps:
        if otp_rec["attempts"] >= MAX_OTP_ATTEMPTS:
            continue
        if security.verify_otp_code(req.otp, clean_email, otp_rec["otp_hash"]):
            matched_otp = otp_rec
            break

    if not matched_otp:
        db.increment_otp_attempts(active_otps[0]["id"])
        remaining = MAX_OTP_ATTEMPTS - (active_otps[0]["attempts"] + 1)
        raise HTTPException(status_code=400, detail=f"Incorrect verification code. {max(0, remaining)} attempt(s) remaining.")

    # Atomically consume OTP
    consumed = db.consume_otp_atomic(clean_email, matched_otp["id"])
    if not consumed:
        raise HTTPException(status_code=400, detail="Verification code was already used. Please request a new one.")

    # Resolve or create user account
    user = db.get_user_by_email(clean_email)
    is_new_user = False

    if user:
        db.update_user_last_login(user["id"])
    else:
        # New User Registration
        is_new_user = True
        if req.username:
            valid_u, clean_username = security.validate_username(req.username)
            if not valid_u:
                clean_username = clean_email.split("@")[0][:20]
        else:
            # Auto-derive friendly starter username from email
            raw_prefix = clean_email.split("@")[0]
            clean_prefix = "".join(c for c in raw_prefix if c.isalnum() or c == "_")[:20] or "user"
            clean_username = clean_prefix

        # Ensure username uniqueness
        if db.get_user_by_username(clean_username):
            clean_username = f"{clean_username[:15]}_{security.generate_otp_code()[:4]}"

        user = db.create_user(clean_username, clean_email, phone=req.phone)

    # Session Fixation Protection: Invalidate prior sessions
    db.delete_all_user_sessions(user["id"])

    # Create new cryptographically secure session
    session_id = security.generate_session_id()
    csrf_token = security.generate_csrf_token()
    session_expires_iso = (datetime.datetime.utcnow() + datetime.timedelta(seconds=SESSION_MAX_AGE_SECONDS)).isoformat()

    db.create_session(session_id, user["id"], csrf_token, session_expires_iso, client_ip, user_agent)

    # Set secure HttpOnly cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=SESSION_COOKIE_HTTPONLY,
        secure=SESSION_COOKIE_SECURE,
        samesite=SESSION_COOKIE_SAMESITE,
        path="/"
    )

    user_data = db.get_user_data(user["id"])

    return {
        "success": True,
        "is_new_user": is_new_user,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "phone": user.get("phone"),
            "role": user["role"]
        },
        "csrf_token": csrf_token,
        "subscription": payment_service.get_billing_config(user["id"]),
        "data": user_data
    }

@app.post("/api/auth/profile")
async def api_update_profile(
    req: UpdateProfileRequest,
    session: Dict[str, Any] = Depends(get_current_session),
    x_csrf_token: Optional[str] = Header(None)
):
    """Allows an authenticated user to update their display name / username and optional phone number."""
    if not security.verify_csrf_token(x_csrf_token, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")

    user_id = session["user_id"]
    clean_username = None
    if req.username:
        valid_u, clean_username = security.validate_username(req.username)
        if not valid_u:
            raise HTTPException(status_code=400, detail=clean_username)
        existing = db.get_user_by_username(clean_username)
        if existing and existing["id"] != user_id:
            raise HTTPException(status_code=409, detail="Username is already taken.")

    user = db.update_user_profile(user_id, username=clean_username, phone=req.phone)
    return {"success": True, "user": user}

@app.get("/api/auth/me")
async def api_me(session: Dict[str, Any] = Depends(get_current_session)):
    """Returns profile information, CSRF token, and billing status for the authenticated session."""
    user_id = session["user_id"]
    return {
        "user": {
            "id": user_id,
            "username": session["username"],
            "email": session["email"],
            "phone": session.get("phone"),
            "role": session["role"]
        },
        "csrf_token": session["csrf_token"],
        "subscription": payment_service.get_billing_config(user_id)
    }

@app.post("/api/auth/logout")
async def api_logout(
    request: Request,
    response: Response,
    x_csrf_token: Optional[str] = Header(None)
):
    """
    Invalidates the server-side session and clears the session cookie.
    CSRF token is validated for defense-in-depth (P1 #12).
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session = db.get_session(session_id)
        # Validate CSRF whenever an active session exists.
        if session:
            if not security.verify_csrf_token(x_csrf_token, session["csrf_token"]):
                raise HTTPException(status_code=403, detail="Invalid CSRF token.")
        db.delete_session(session_id)

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=SESSION_COOKIE_SAMESITE
    )
    return {"success": True, "message": "Logged out successfully."}

# ═══════════════════════════════════════════════════════
# BILLING & SUBSCRIPTION ENDPOINTS (Razorpay UPI AutoPay)
# ═══════════════════════════════════════════════════════
@app.get("/api/subscription")
async def api_get_subscription(session: Dict[str, Any] = Depends(get_current_session)):
    """
    Returns current subscription status and Razorpay metadata for the authenticated user.
    Always accessible regardless of whether subscription is active or expired.
    """
    user_id = session["user_id"]
    billing_data = payment_service.get_billing_config(user_id)
    return {
        "success": True,
        "subscription": billing_data
    }

@app.post("/api/billing/create-subscription")
async def api_create_subscription(
    session: Dict[str, Any] = Depends(get_current_session),
    x_csrf_token: Optional[str] = Header(None)
):
    """
    Step 1: Initializes a recurring ₹21/month subscription on Razorpay for UPI AutoPay.
    Returns checkout parameters for client-side Razorpay modal.
    """
    if not security.verify_csrf_token(x_csrf_token, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")

    user_dict = {
        "id": session["user_id"],
        "username": session["username"],
        "email": session["email"],
        "phone": session.get("phone")
    }

    success, checkout_data, msg = payment_service.create_razorpay_subscription(user_dict)
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "success": True,
        "checkout": checkout_data,
        "message": msg
    }

@app.post("/api/billing/cancel-subscription")
async def api_cancel_subscription(
    session: Dict[str, Any] = Depends(get_current_session),
    x_csrf_token: Optional[str] = Header(None)
):
    """
    Cancels the user's active recurring subscription on Razorpay and updates local state.
    """
    if not security.verify_csrf_token(x_csrf_token, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")

    success, msg = payment_service.cancel_razorpay_subscription(session["user_id"])
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    return {
        "success": True,
        "message": msg
    }

@app.post("/api/billing/webhook")
async def api_billing_webhook(request: Request):
    """
    Authoritative webhook ingress for Razorpay subscription lifecycle events.
    Verifies HMAC-SHA256 signature against RAZORPAY_WEBHOOK_SECRET.
    Idempotent: Duplicate webhook events are safely acknowledged without state corruption.
    """
    raw_body = await request.body()
    signature_header = request.headers.get("x-razorpay-signature")

    if not payment_service.verify_webhook_signature(raw_body, signature_header):
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    success, msg = payment_service.process_razorpay_webhook(payload)
    return {
        "status": "ok",
        "message": msg
    }

# ═══════════════════════════════════════════════════════
# USER DATA ENDPOINTS (Strict Isolation & Subscription Gated)
# ═══════════════════════════════════════════════════════
@app.get("/api/data")
async def api_get_data(session: Dict[str, Any] = Depends(require_active_subscription)):
    """
    Retrieves habits, tasks, and notes payload strictly for the authenticated user.
    Requires active subscription when hosted billing is enabled.
    """
    user_id = session["user_id"]
    data = db.get_user_data(user_id)
    return {
        "user": {
            "id": user_id,
            "username": session["username"],
            "email": session["email"],
            "phone": session.get("phone"),
            "role": session["role"]
        },
        "csrf_token": session["csrf_token"],
        "subscription": payment_service.get_billing_config(user_id),
        "data": data
    }

@app.post("/api/data")
async def api_save_data(
    payload: Dict[str, Any],
    request: Request,
    session: Dict[str, Any] = Depends(require_active_subscription),
    x_csrf_token: Optional[str] = Header(None)
):
    """
    Saves habits, tasks, and notes payload strictly under the authenticated user's ID.
    Validates CSRF double-submit header. Requires active subscription.
    """
    # 1. CSRF Protection Check
    if not security.verify_csrf_token(x_csrf_token, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")

    # 2. Save Data Isolated by user_id (never from client payload)
    user_id = session["user_id"]
    res = db.save_user_data(user_id, payload)
    return res

# ═══════════════════════════════════════════════════════
# MAIN ENTRYPOINT
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    print(f"🚀 Launching AdatTracker Pro on http://{HOST}:{PORT}")
    uvicorn.run("server:app", host=HOST, port=PORT, reload=not IS_PRODUCTION)

