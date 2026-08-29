"""
AdatTracker Pro - Database Engine & Layered Repository
Handles SQLite WAL mode, connection management, schema migrations, and parameterized data access.
"""

import sqlite3
import json
import uuid
import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

from config import DB_PATH, DATA_DIR

def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with WAL mode and row factory enabled."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Configure SQLite PRAGMAs for high concurrency and data integrity
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def init_db():
    """Initializes the database schema and performs safe migrations on existing databases."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL COLLATE NOCASE,
        email TEXT UNIQUE NOT NULL COLLATE NOCASE,
        role TEXT NOT NULL DEFAULT 'user',
        is_verified INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_login TEXT NOT NULL
    );
    """)

    # 2. Email OTPs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS email_otps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL COLLATE NOCASE,
        otp_hash TEXT NOT NULL,
        purpose TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        expires_at TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0,
        ip_address TEXT,
        created_at TEXT NOT NULL
    );
    """)

    # 3. Server-Side Sessions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        csrf_token TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 4. Rate Limits Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rate_limits (
        key TEXT PRIMARY KEY,
        attempts INTEGER NOT NULL DEFAULT 0,
        window_start TEXT NOT NULL,
        blocked_until TEXT
    );
    """)

    # 5. User Data Table (Strictly isolated by user_id)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_data (
        user_id TEXT PRIMARY KEY,
        data_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        version INTEGER DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # ── Safe Schema Migrations (MUST run BEFORE indexes on new columns) ──────
    # These ALTER TABLE statements are safe to re-run — they fail silently if
    # the column already exists (i.e. fresh installs with the new schema).
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT COLLATE NOCASE;")
    except sqlite3.OperationalError:
        pass  # Column already exists — fresh install or already migrated

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user';")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 1;")
    except sqlite3.OperationalError:
        pass

    # Remove the old phone column index if it exists from a prior version
    try:
        cursor.execute("DROP INDEX IF EXISTS idx_users_phone;")
    except sqlite3.OperationalError:
        pass

    conn.commit()  # Commit migrations before creating indexes

    # ── Indexes for O(1) lookups (created AFTER migrations ensure columns exist) ──
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otps_email_used ON email_otps(email, used, expires_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")

    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════
# USER REPOSITORY
# ═══════════════════════════════════════════════════════
def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, role, is_verified, created_at, last_login FROM users WHERE id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, role, is_verified, created_at, last_login FROM users WHERE email = ?",
        (email.strip().lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, role, is_verified, created_at, last_login FROM users WHERE username = ?",
        (username.strip().lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_login_id(login_id: str) -> Optional[Dict[str, Any]]:
    """Finds user by either username or email."""
    clean_id = login_id.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, role, is_verified, created_at, last_login FROM users WHERE username = ? OR email = ?",
        (clean_id, clean_id)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(username: str, email: str, role: str = "user") -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.datetime.utcnow().isoformat()
    clean_username = username.strip().lower()
    clean_email = email.strip().lower()

    cursor.execute(
        """
        INSERT INTO users (id, username, email, role, is_verified, created_at, last_login)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        """,
        (user_id, clean_username, clean_email, role, now_iso, now_iso)
    )

    # Initialize starter habit template
    initial_data = create_default_user_data()
    cursor.execute(
        "INSERT INTO user_data (user_id, data_json, updated_at, version) VALUES (?, ?, ?, 1)",
        (user_id, json.dumps(initial_data), now_iso)
    )

    conn.commit()
    conn.close()

    return {
        "id": user_id,
        "username": clean_username,
        "email": clean_email,
        "role": role,
        "is_verified": 1,
        "created_at": now_iso,
        "last_login": now_iso
    }

def update_user_last_login(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    cursor.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_iso, user_id))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════
# EMAIL OTP REPOSITORY
# ═══════════════════════════════════════════════════════
def store_otp(email: str, otp_hash: str, purpose: str, expires_at_iso: str, ip_address: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    clean_email = email.strip().lower()

    # Invalidate previous unexpired OTPs for this email to prevent multiple valid OTPs
    cursor.execute(
        "UPDATE email_otps SET used = 1 WHERE email = ? AND used = 0",
        (clean_email,)
    )

    cursor.execute(
        """
        INSERT INTO email_otps (email, otp_hash, purpose, attempts, expires_at, used, ip_address, created_at)
        VALUES (?, ?, ?, 0, ?, 0, ?, ?)
        """,
        (clean_email, otp_hash, purpose, expires_at_iso, ip_address, now_iso)
    )
    conn.commit()
    conn.close()

def get_active_otp(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    clean_email = email.strip().lower()
    now_iso = datetime.datetime.utcnow().isoformat()

    cursor.execute(
        """
        SELECT id, email, otp_hash, purpose, attempts, expires_at, used, created_at
        FROM email_otps
        WHERE email = ? AND used = 0 AND expires_at > ?
        ORDER BY id DESC LIMIT 1
        """,
        (clean_email, now_iso)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def increment_otp_attempts(otp_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE email_otps SET attempts = attempts + 1 WHERE id = ?", (otp_id,))
    conn.commit()
    conn.close()

def mark_otp_used(otp_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE email_otps SET used = 1 WHERE id = ?", (otp_id,))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════
# SERVER-SIDE SESSIONS REPOSITORY
# ═══════════════════════════════════════════════════════
def create_session(session_id: str, user_id: str, csrf_token: str, expires_at_iso: str, ip: Optional[str] = None, ua: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()

    # Session Fixation Protection: Invalidate prior active sessions for this user if desired
    # or keep existing sessions for multi-device login (we clean up older expired ones)
    cursor.execute(
        """
        INSERT INTO sessions (id, user_id, csrf_token, expires_at, ip_address, user_agent, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, user_id, csrf_token, expires_at_iso, ip, ua, now_iso)
    )
    conn.commit()
    conn.close()

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()

    cursor.execute(
        """
        SELECT s.id as session_id, s.user_id, s.csrf_token, s.expires_at,
               u.username, u.email, u.role, u.is_verified, u.created_at, u.last_login
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.id = ? AND s.expires_at > ?
        """,
        (session_id, now_iso)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_session(session_id: str):
    if not session_id:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

def delete_all_user_sessions(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════
# RATE LIMITING REPOSITORY
# ═══════════════════════════════════════════════════════
def get_rate_limit(key: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, attempts, window_start, blocked_until FROM rate_limits WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def set_rate_limit(key: str, attempts: int, window_start_iso: str, blocked_until_iso: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO rate_limits (key, attempts, window_start, blocked_until)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            attempts = excluded.attempts,
            window_start = excluded.window_start,
            blocked_until = excluded.blocked_until
        """,
        (key, attempts, window_start_iso, blocked_until_iso)
    )
    conn.commit()
    conn.close()

def reset_rate_limit(key: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rate_limits WHERE key = ?", (key,))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════
# USER DATA REPOSITORY
# ═══════════════════════════════════════════════════════
def get_user_data(user_id: str) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT data_json, updated_at, version FROM user_data WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row["data_json"]:
        try:
            return json.loads(row["data_json"])
        except Exception:
            pass
    return create_default_user_data()

def save_user_data(user_id: str, data: dict) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    data_str = json.dumps(data)

    cursor.execute(
        """
        INSERT INTO user_data (user_id, data_json, updated_at, version)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            data_json = excluded.data_json,
            updated_at = excluded.updated_at,
            version = user_data.version + 1
        """,
        (user_id, data_str, now_iso)
    )
    conn.commit()
    conn.close()
    return {"success": True, "updated_at": now_iso}

def create_default_user_data() -> Dict[str, Any]:
    now_iso = datetime.datetime.utcnow().isoformat()
    return {
        "habits": [
            {
                "id": f"id_{uuid.uuid4().hex[:8]}",
                "name": "Morning Meditation (10 min)",
                "cat": "mind",
                "color": "#a78bfa",
                "freq": "daily",
                "target": 1,
                "unit": "times",
                "cue": "After waking up",
                "history": {}
            },
            {
                "id": f"id_{uuid.uuid4().hex[:8]}",
                "name": "Workout / Exercise",
                "cat": "health",
                "color": "#10b981",
                "freq": "daily",
                "target": 1,
                "unit": "times",
                "cue": "5:30 PM",
                "history": {}
            },
            {
                "id": f"id_{uuid.uuid4().hex[:8]}",
                "name": "Read 20 Pages",
                "cat": "mind",
                "color": "#f59e0b",
                "freq": "daily",
                "target": 20,
                "unit": "pages",
                "cue": "Before sleep",
                "history": {}
            },
            {
                "id": f"id_{uuid.uuid4().hex[:8]}",
                "name": "Deep Work Session",
                "cat": "work",
                "color": "#06b6d4",
                "freq": "weekdays",
                "target": 2,
                "unit": "hours",
                "cue": "9 AM Focus block",
                "history": {}
            }
        ],
        "tasks": [],
        "notes": [
            {
                "id": f"id_{uuid.uuid4().hex[:8]}",
                "title": "💡 Welcome to AdatTracker",
                "content": "Your habits, tasks, and sticky notes are now securely synced to your cloud database!\n\nAccess this dashboard from any mobile or desktop device.",
                "color": "yellow",
                "pinned": True,
                "updatedAt": now_iso
            }
        ],
        "settings": {
            "freeze": False,
            "confetti": True,
            "xp": True,
            "sound": False
        },
        "bestStreak": 0
    }
