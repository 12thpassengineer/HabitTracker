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

    # 6. Subscriptions Table (₹21/mo Razorpay UPI AutoPay)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        razorpay_subscription_id TEXT UNIQUE,
        plan TEXT NOT NULL DEFAULT 'hosted_monthly',
        status TEXT NOT NULL DEFAULT 'inactive',
        current_period_start TEXT,
        current_period_end TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        cancelled_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # 7. Webhook Events Table (Idempotency Engine)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS webhook_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        processed_at TEXT NOT NULL
    );
    """)

    # ── Schema migrations (MUST run BEFORE indexes on new columns) ───────────
    # We inspect the existing schema before adding each column so unrelated
    # SQLite errors are not silently treated as "already migrated".
    existing_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(users)").fetchall()
    }

    def ensure_user_column(name: str, ddl: str) -> None:
        if name not in existing_columns:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {ddl}")
            existing_columns.add(name)

    ensure_user_column("email", "email TEXT COLLATE NOCASE")
    ensure_user_column("role", "role TEXT NOT NULL DEFAULT 'user'")
    ensure_user_column("phone", "phone TEXT")
    ensure_user_column("is_verified", "is_verified INTEGER NOT NULL DEFAULT 1")

    # Legacy pre-Email-OTP databases may contain users whose email is NULL.
    # Preserve their data and make the migration visible; those accounts need
    # an email address associated before passwordless login can be used.
    legacy_null_email = cursor.execute(
        "SELECT COUNT(*) AS count FROM users WHERE email IS NULL OR TRIM(email) = ''"
    ).fetchone()["count"]
    if legacy_null_email:
        print(
            f"⚠️ Migration notice: {legacy_null_email} legacy user(s) have no email address. "
            "Their existing data is preserved, but they must be associated with an email "
            "before passwordless Email OTP login can be used."
        )

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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_rzp_id ON subscriptions(razorpay_subscription_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);")

    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════
# USER REPOSITORY
# ═══════════════════════════════════════════════════════
def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, phone, role, is_verified, created_at, last_login FROM users WHERE id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, phone, role, is_verified, created_at, last_login FROM users WHERE email = ?",
        (email.strip().lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, email, phone, role, is_verified, created_at, last_login FROM users WHERE username = ?",
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
        "SELECT id, username, email, phone, role, is_verified, created_at, last_login FROM users WHERE username = ? OR email = ?",
        (clean_id, clean_id)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(username: str, email: str, role: str = "user", phone: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.datetime.utcnow().isoformat()
    clean_username = username.strip().lower()
    clean_email = email.strip().lower()
    clean_phone = phone.strip() if phone else None

    cursor.execute(
        """
        INSERT INTO users (id, username, email, phone, role, is_verified, created_at, last_login)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (user_id, clean_username, clean_email, clean_phone, role, now_iso, now_iso)
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
        "phone": clean_phone,
        "role": role,
        "is_verified": 1,
        "created_at": now_iso,
        "last_login": now_iso
    }

def update_user_profile(user_id: str, username: Optional[str] = None, phone: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    updates = []
    params = []
    if username:
        clean_username = username.strip().lower()
        updates.append("username = ?")
        params.append(clean_username)
    if phone is not None:
        clean_phone = phone.strip() if phone else None
        updates.append("phone = ?")
        params.append(clean_phone)
    if not updates:
        conn.close()
        return get_user_by_id(user_id)

    params.append(user_id)
    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))
    conn.commit()
    conn.close()
    return get_user_by_id(user_id)

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
    clean_email = email.strip().lower()
    now_iso = datetime.datetime.utcnow().isoformat()
    cursor.execute(
        """
        INSERT INTO email_otps (email, otp_hash, purpose, attempts, expires_at, used, ip_address, created_at)
        VALUES (?, ?, ?, 0, ?, 0, ?, ?)
        """,
        (clean_email, otp_hash, purpose, expires_at_iso, ip_address, now_iso)
    )
    conn.commit()
    conn.close()

def get_active_otp(email: str, purpose: Optional[str] = None) -> Optional[Dict[str, Any]]:
    otps = get_active_otps_for_email(email, purpose)
    return otps[0] if otps else None

def get_active_otps_for_email(email: str, purpose: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    clean_email = email.strip().lower()
    now_iso = datetime.datetime.utcnow().isoformat()

    if purpose:
        # Filter by purpose — signup OTP cannot be used to verify a login (P0 #8)
        cursor.execute(
            """
            SELECT id, email, otp_hash, purpose, attempts, expires_at, used, created_at
            FROM email_otps
            WHERE email = ? AND purpose = ? AND used = 0 AND expires_at > ?
            ORDER BY id DESC
            """,
            (clean_email, purpose, now_iso)
        )
    else:
        cursor.execute(
            """
            SELECT id, email, otp_hash, purpose, attempts, expires_at, used, created_at
            FROM email_otps
            WHERE email = ? AND used = 0 AND expires_at > ?
            ORDER BY id DESC
            """,
            (clean_email, now_iso)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

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

def mark_all_otps_used(email: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    clean_email = email.strip().lower()
    cursor.execute("UPDATE email_otps SET used = 1 WHERE email = ?", (clean_email,))
    conn.commit()
    conn.close()

def consume_otp_atomic(email: str, otp_id: int) -> bool:
    """
    Atomically marks a specific OTP as used inside a single transaction.
    Returns True if exactly one row was updated (OTP was still unused),
    False if already consumed (prevents race conditions).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    clean_email = email.strip().lower()
    now_iso = datetime.datetime.utcnow().isoformat()
    try:
        cursor.execute(
            """
            UPDATE email_otps
            SET used = 1
            WHERE id = ? AND email = ? AND used = 0 AND expires_at > ?
            """,
            (otp_id, clean_email, now_iso)
        )
        conn.commit()
        return cursor.rowcount == 1
    except Exception:
        conn.rollback()
        return False
    finally:
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
               u.username, u.email, u.phone, u.role, u.is_verified, u.created_at, u.last_login
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

def increment_rate_limit_atomic(key: str, window_seconds: int, max_requests: int, cooldown_seconds: int):
    """
    Single-transaction atomic rate limit check+increment.
    Returns (is_allowed: bool, retry_after_seconds: int)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.datetime.utcnow()
    now_iso = now.isoformat()
    try:
        # Serialize concurrent rate-limit checks so SELECT+UPDATE cannot lose increments.
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT key, attempts, window_start, blocked_until FROM rate_limits WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()

        if not row:
            cursor.execute(
                "INSERT INTO rate_limits (key, attempts, window_start, blocked_until) VALUES (?, 1, ?, NULL)",
                (key, now_iso)
            )
            conn.commit()
            return True, 0

        record = dict(row)

        if record["blocked_until"]:
            try:
                blocked_until = datetime.datetime.fromisoformat(record["blocked_until"])
                if blocked_until > now:
                    retry_after = int((blocked_until - now).total_seconds()) + 1
                    return False, max(1, retry_after)
            except ValueError:
                pass

        try:
            window_start = datetime.datetime.fromisoformat(record["window_start"])
        except ValueError:
            window_start = now

        elapsed = (now - window_start).total_seconds()

        if elapsed > window_seconds:
            cursor.execute(
                "UPDATE rate_limits SET attempts = 1, window_start = ?, blocked_until = NULL WHERE key = ?",
                (now_iso, key)
            )
            conn.commit()
            return True, 0

        current_attempts = record["attempts"] + 1

        if current_attempts > max_requests:
            blocked_until_iso = (now + datetime.timedelta(seconds=cooldown_seconds)).isoformat()
            cursor.execute(
                "UPDATE rate_limits SET attempts = ?, blocked_until = ? WHERE key = ?",
                (current_attempts, blocked_until_iso, key)
            )
            conn.commit()
            return False, cooldown_seconds

        cursor.execute(
            "UPDATE rate_limits SET attempts = ? WHERE key = ?",
            (current_attempts, key)
        )
        conn.commit()
        return True, 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return True, 0
    finally:
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

# ═══════════════════════════════════════════════════════
# SUBSCRIPTION & BILLING REPOSITORY (Razorpay Subscriptions)
# ═══════════════════════════════════════════════════════
def get_subscription_by_user_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves current subscription record for a specific user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, razorpay_subscription_id, plan, status,
               current_period_start, current_period_end, created_at, updated_at, cancelled_at
        FROM subscriptions
        WHERE user_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_subscription_by_razorpay_id(rzp_sub_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves subscription record by its Razorpay subscription ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, user_id, razorpay_subscription_id, plan, status,
               current_period_start, current_period_end, created_at, updated_at, cancelled_at
        FROM subscriptions
        WHERE razorpay_subscription_id = ?
        """,
        (rzp_sub_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def upsert_subscription(
    user_id: str,
    razorpay_sub_id: str,
    plan: str = "hosted_monthly",
    status: str = "pending",
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    cancelled_at: Optional[str] = None
) -> Dict[str, Any]:
    """Inserts or updates the user's subscription record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"

    # Check if a subscription already exists for this user
    existing = get_subscription_by_user_id(user_id)
    if existing:
        cursor.execute(
            """
            UPDATE subscriptions
            SET razorpay_subscription_id = ?,
                plan = ?,
                status = ?,
                current_period_start = COALESCE(?, current_period_start),
                current_period_end = COALESCE(?, current_period_end),
                cancelled_at = COALESCE(?, cancelled_at),
                updated_at = ?
            WHERE user_id = ?
            """,
            (razorpay_sub_id, plan, status, period_start, period_end, cancelled_at, now_iso, user_id)
        )
    else:
        cursor.execute(
            """
            INSERT INTO subscriptions (
                id, user_id, razorpay_subscription_id, plan, status,
                current_period_start, current_period_end, created_at, updated_at, cancelled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sub_id, user_id, razorpay_sub_id, plan, status, period_start, period_end, now_iso, now_iso, cancelled_at)
        )

    conn.commit()
    conn.close()
    return get_subscription_by_user_id(user_id)

def update_subscription_status(
    razorpay_sub_id: str,
    status: str,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    cancelled_at: Optional[str] = None
) -> bool:
    """Updates status and billing cycle timestamps by Razorpay subscription ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    cursor.execute(
        """
        UPDATE subscriptions
        SET status = ?,
            current_period_start = COALESCE(?, current_period_start),
            current_period_end = COALESCE(?, current_period_end),
            cancelled_at = COALESCE(?, cancelled_at),
            updated_at = ?
        WHERE razorpay_subscription_id = ?
        """,
        (status, period_start, period_end, cancelled_at, now_iso, razorpay_sub_id)
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def is_webhook_event_processed(event_id: str) -> bool:
    """Checks if a webhook event ID has already been processed (Idempotency)."""
    if not event_id:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT event_id FROM webhook_events WHERE event_id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def record_webhook_event(event_id: str, event_type: str):
    """Records a processed webhook event to prevent duplicate execution."""
    if not event_id:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO webhook_events (event_id, event_type, processed_at) VALUES (?, ?, ?)",
            (event_id, event_type, now_iso)
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

