"""
AdatTracker Pro - High-Performance, Hardened FastAPI Backend Server
Implements Passwordless Email OTP, HttpOnly Cookie Sessions, CSRF Protection,
Strict User Data Isolation, Rate Limiting, and Security Headers.
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
    MAX_PAYLOAD_BYTES,
    STATIC_HTML_PATH,
    DB_PATH
)
import database as db
import security
import email_service

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
    version="2.0.0",
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
    purpose: str = Field(..., pattern="^(signup|login)$")
    email: Optional[str] = Field(None, max_length=100)
    username: Optional[str] = Field(None, max_length=30)
    login_id: Optional[str] = Field(None, max_length=100)  # username or email for login

class VerifyOtpRequest(BaseModel):
    email: str = Field(..., max_length=100)
    otp: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")
    purpose: str = Field(..., pattern="^(signup|login)$")
    username: Optional[str] = Field(None, max_length=30)

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
    Generates and sends a single-use 6-digit OTP code to the verified email.
    Applies IP and Email rate limiting. Prevents user enumeration.
    """
    client_ip = security.get_client_ip(request)

    # 1. IP Rate Limiting (5 requests per 15 minutes)
    ip_key = f"otp_ip:{client_ip}"
    allowed, retry_after = security.check_rate_limit(
        ip_key, MAX_OTP_REQUESTS_IP_15MIN, window_seconds=900, cooldown_seconds=900
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many OTP requests from this IP. Please wait {retry_after} seconds."
        )

    target_email = ""
    target_username = ""

    if req.purpose == "signup":
        # Validate signup inputs
        if not req.username or not req.email:
            raise HTTPException(status_code=400, detail="Username and email are required for signup.")

        valid_u, clean_username = security.validate_username(req.username)
        if not valid_u:
            raise HTTPException(status_code=400, detail=clean_username)

        valid_e, clean_email = security.validate_email(req.email)
        if not valid_e:
            raise HTTPException(status_code=400, detail=clean_email)

        # Check if username or email is already registered
        if db.get_user_by_username(clean_username):
            raise HTTPException(status_code=409, detail="Username is already taken.")
        if db.get_user_by_email(clean_email):
            raise HTTPException(status_code=409, detail="Email is already registered. Please log in.")

        target_email = clean_email
        target_username = clean_username

    elif req.purpose == "login":
        login_id = req.login_id or req.email or req.username
        if not login_id:
            raise HTTPException(status_code=400, detail="Username or email is required.")

        user = db.get_user_by_login_id(login_id)
        if user:
            target_email = user["email"]
            target_username = user["username"]
        else:
            # Anti-Enumeration: Return identical success message without generating OTP
            return {
                "success": True,
                "message": "If an account exists with this email or username, a verification code has been sent."
            }

    # 2. Email Rate Limiting (3 requests per 15 minutes)
    email_key = f"otp_email:{target_email}"
    allowed_email, retry_after_email = security.check_rate_limit(
        email_key, MAX_OTP_REQUESTS_EMAIL_15MIN, window_seconds=900, cooldown_seconds=900
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

    db.store_otp(target_email, otp_hash, req.purpose, expires_at, client_ip)

    # 4. Dispatch Email
    sent, err_msg = email_service.send_otp_email(target_email, otp_code, target_username, req.purpose)
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
    Verifies the 6-digit OTP, creates the account if signing up, and establishes
    a secure HttpOnly session cookie.
    """
    client_ip = security.get_client_ip(request)
    user_agent = request.headers.get("user-agent", "Unknown")[:200]

    valid_e, clean_email = security.validate_email(req.email)
    if not valid_e:
        raise HTTPException(status_code=400, detail=clean_email)

    active_otps = db.get_active_otps_for_email(clean_email)
    if not active_otps:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code. Please request a new one.")

    # Check against any active unexpired OTP for this email
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

    # Mark all OTPs for this email as used (Single-Use enforcement)
    db.mark_all_otps_used(clean_email)

    # Resolve or create user account
    if req.purpose == "signup":
        if not req.username:
            raise HTTPException(status_code=400, detail="Username is required for enrollment.")
        valid_u, clean_username = security.validate_username(req.username)
        if not valid_u:
            raise HTTPException(status_code=400, detail=clean_username)

        # Re-check uniqueness before creation
        if db.get_user_by_username(clean_username) or db.get_user_by_email(clean_email):
            user = db.get_user_by_email(clean_email)
            if not user:
                raise HTTPException(status_code=409, detail="Account already exists.")
        else:
            user = db.create_user(clean_username, clean_email)
    else:
        user = db.get_user_by_email(clean_email)
        if not user:
            raise HTTPException(status_code=404, detail="User account not found.")
        db.update_user_last_login(user["id"])

    # Session Fixation Protection: Invalidate prior sessions for this user
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
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"]
        },
        "csrf_token": csrf_token,
        "data": user_data
    }

@app.get("/api/auth/me")
async def api_me(session: Dict[str, Any] = Depends(get_current_session)):
    """Returns profile information and CSRF token for the authenticated session."""
    return {
        "user": {
            "id": session["user_id"],
            "username": session["username"],
            "email": session["email"],
            "role": session["role"]
        },
        "csrf_token": session["csrf_token"]
    }

@app.post("/api/auth/logout")
async def api_logout(request: Request, response: Response):
    """Invalidates the server-side session and clears the session cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
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
# USER DATA ENDPOINTS (Strict Isolation & CSRF Protected)
# ═══════════════════════════════════════════════════════
@app.get("/api/data")
async def api_get_data(session: Dict[str, Any] = Depends(get_current_session)):
    """
    Retrieves the habits, tasks, and notes payload strictly for the authenticated user.
    Never accepts or trusts a user_id from query parameters.
    """
    user_id = session["user_id"]
    data = db.get_user_data(user_id)
    return {
        "user": {
            "id": user_id,
            "username": session["username"],
            "email": session["email"],
            "role": session["role"]
        },
        "csrf_token": session["csrf_token"],
        "data": data
    }

@app.post("/api/data")
async def api_save_data(
    payload: Dict[str, Any],
    request: Request,
    session: Dict[str, Any] = Depends(get_current_session),
    x_csrf_token: Optional[str] = Header(None)
):
    """
    Saves habits, tasks, and notes payload strictly under the authenticated user's ID.
    Validates CSRF double-submit header for all state-mutating requests.
    """
    # 1. CSRF Protection Check
    if not security.verify_csrf_token(x_csrf_token, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")

    # 2. Save Data Isolated by user_id
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
