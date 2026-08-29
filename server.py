"""
Habit Codex Pro - Multi-User Cloud & Self-Hosted Backend Server
Supports both FastAPI (if installed) and Built-in Python Standard Library (Zero Dependencies).
Database: SQLite (stored in ./data/habit_codex.db)
"""

import os
import sys
import json
import sqlite3
import uuid
import datetime
import re
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "habit_codex.db"
STATIC_HTML_PATH = BASE_DIR / "habit_tracker.html"
if not STATIC_HTML_PATH.exists():
    STATIC_HTML_PATH = BASE_DIR / "frontend" / "index.html"
if not STATIC_HTML_PATH.exists():
    STATIC_HTML_PATH = BASE_DIR / "frontend" / "habit_tracker.html"

# ═══════════════════════════════════════════════════════
# DATABASE INITIALIZATION & REPOSITORY
# ═══════════════════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL COLLATE NOCASE,
        phone TEXT NOT NULL,
        token TEXT UNIQUE NOT NULL,
        created_at TEXT NOT NULL,
        last_login TEXT NOT NULL
    );
    """)

    # User Data table (Stores each user's isolated habits, tasks, notes, settings)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_data (
        user_id TEXT PRIMARY KEY,
        data_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        version INTEGER DEFAULT 1,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
    
    conn.commit()
    conn.close()
    print(f"✅ Database initialized at: {DB_PATH}")

def normalize_phone(phone: str) -> str:
    # Strip spaces, hyphens, parentheses
    return re.sub(r'[\s\-\(\)\+]', '', str(phone).strip())

def normalize_username(username: str) -> str:
    return str(username).strip().lower()

def create_default_user_data():
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
                "title": "💡 Welcome to Habit Codex",
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
# AUTHENTICATION & DATA SERVICE LOGIC
# ═══════════════════════════════════════════════════════
def register_user(username: str, phone: str):
    username_clean = normalize_username(username)
    phone_clean = normalize_phone(phone)

    if not username_clean or len(username_clean) < 2:
        return {"error": "Username must be at least 2 characters", "status": 400}
    if not phone_clean or len(phone_clean) < 4:
        return {"error": "Please enter a valid phone number", "status": 400}

    conn = get_db()
    cursor = conn.cursor()

    # Check if username exists
    cursor.execute("SELECT id FROM users WHERE username = ?", (username_clean,))
    if cursor.fetchone():
        conn.close()
        return {"error": "Username already exists. Please log in instead.", "status": 409}

    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    token = f"hct_{uuid.uuid4().hex}"
    now_iso = datetime.datetime.utcnow().isoformat()

    cursor.execute(
        "INSERT INTO users (id, username, phone, token, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username_clean, phone_clean, token, now_iso, now_iso)
    )

    # Initialize starter user data
    initial_data = create_default_user_data()
    cursor.execute(
        "INSERT INTO user_data (user_id, data_json, updated_at, version) VALUES (?, ?, ?, 1)",
        (user_id, json.dumps(initial_data), now_iso)
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "token": token,
        "user": {
            "id": user_id,
            "username": username_clean,
            "phone": phone_clean
        },
        "data": initial_data
    }

def login_user(username: str, phone: str):
    username_clean = normalize_username(username)
    phone_clean = normalize_phone(phone)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, username, phone, token FROM users WHERE username = ?", (username_clean,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return {"error": "User not found. Please enroll / register first.", "status": 404}

    stored_phone = normalize_phone(row["phone"])
    if stored_phone != phone_clean:
        conn.close()
        return {"error": "Invalid phone number for this username.", "status": 401}

    # Generate a fresh token or use existing token
    new_token = f"hct_{uuid.uuid4().hex}"
    now_iso = datetime.datetime.utcnow().isoformat()

    cursor.execute("UPDATE users SET token = ?, last_login = ? WHERE id = ?", (new_token, now_iso, row["id"]))
    conn.commit()

    # Fetch user data
    cursor.execute("SELECT data_json FROM user_data WHERE user_id = ?", (row["id"],))
    data_row = cursor.fetchone()
    user_data = json.loads(data_row["data_json"]) if data_row else create_default_user_data()

    conn.close()

    return {
        "success": True,
        "token": new_token,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "phone": row["phone"]
        },
        "data": user_data
    }

def get_user_by_token(token: str):
    if not token:
        return None
    token_clean = token.replace("Bearer ", "").strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, phone, created_at, last_login FROM users WHERE token = ?", (token_clean,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_user_data(user_id: str):
    conn = get_db()
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

def save_user_data(user_id: str, data: dict):
    conn = get_db()
    cursor = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    data_str = json.dumps(data)

    cursor.execute("""
    INSERT INTO user_data (user_id, data_json, updated_at, version)
    VALUES (?, ?, ?, 1)
    ON CONFLICT(user_id) DO UPDATE SET
        data_json = excluded.data_json,
        updated_at = excluded.updated_at,
        version = user_data.version + 1
    """, (user_id, data_str, now_iso))

    conn.commit()
    conn.close()
    return {"success": True, "updated_at": now_iso}

def get_all_users_summary():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, phone, created_at, last_login FROM users ORDER BY last_login DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ═══════════════════════════════════════════════════════
# FASTAPI BACKEND IMPLEMENTATION (IF INSTALLED)
# ═══════════════════════════════════════════════════════
def run_fastapi_app(port=8000, host="0.0.0.0"):
    import uvicorn
    from fastapi import FastAPI, Header, HTTPException, Response
    from fastapi.responses import HTMLResponse, FileResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    app = FastAPI(title="Habit Codex Pro Server", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class AuthRequest(BaseModel):
        username: str
        phone: str

    @app.on_event("startup")
    def startup_event():
        init_db()

    @app.get("/", response_class=HTMLResponse)
    def index():
        if STATIC_HTML_PATH.exists():
            return FileResponse(str(STATIC_HTML_PATH))
        return HTMLResponse("<h1>Habit Codex Pro</h1><p>Frontend file habit_tracker.html not found.</p>")

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "Habit Codex Pro", "version": "2.0.0"}

    @app.post("/api/auth/register")
    def api_register(req: AuthRequest):
        res = register_user(req.username, req.phone)
        if "error" in res:
            raise HTTPException(status_code=res.get("status", 400), detail=res["error"])
        return res

    @app.post("/api/auth/login")
    def api_login(req: AuthRequest):
        res = login_user(req.username, req.phone)
        if "error" in res:
            raise HTTPException(status_code=res.get("status", 400), detail=res["error"])
        return res

    @app.get("/api/auth/me")
    def api_me(authorization: str = Header(None)):
        user = get_user_by_token(authorization)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized / Invalid token")
        return {"user": user}

    @app.post("/api/auth/logout")
    def api_logout(authorization: str = Header(None)):
        user = get_user_by_token(authorization)
        if user:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET token = ? WHERE id = ?", (f"revoked_{uuid.uuid4().hex}", user["id"]))
            conn.commit()
            conn.close()
        return {"success": True}

    @app.get("/api/data")
    def api_get_data(authorization: str = Header(None)):
        user = get_user_by_token(authorization)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized / Invalid token")
        data = get_user_data(user["id"])
        return {"user": user, "data": data}

    @app.post("/api/data")
    def api_save_data(payload: dict, authorization: str = Header(None)):
        user = get_user_by_token(authorization)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized / Invalid token")
        res = save_user_data(user["id"], payload)
        return res

    @app.get("/api/users")
    def api_list_users():
        users = get_all_users_summary()
        return {"count": len(users), "users": users}

    print(f"🚀 Habit Codex Pro FastAPI running on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)

# ═══════════════════════════════════════════════════════
# ZERO-DEPENDENCY STANDARD LIBRARY BACKEND (FALLBACK)
# ═══════════════════════════════════════════════════════
def run_stdlib_server(port=8000, host="0.0.0.0"):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
    from urllib.parse import urlparse, parse_qs

    init_db()

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    class HabitHandler(BaseHTTPRequestHandler):
        def _send_json(self, data, status=200):
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, message, status=400):
            self._send_json({"error": message, "detail": message}, status=status)

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            # Serve static frontend
            if path in ["/", "/index.html", "/habit_tracker.html"]:
                if STATIC_HTML_PATH.exists():
                    content = STATIC_HTML_PATH.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                else:
                    self._send_error("Frontend file not found", 404)
                    return

            if path == "/health":
                self._send_json({"status": "ok", "version": "2.0.0"})
                return

            auth_header = self.headers.get("Authorization")
            if not auth_header:
                qs = parse_qs(parsed.query)
                if "token" in qs:
                    auth_header = qs["token"][0]

            if path == "/api/auth/me":
                user = get_user_by_token(auth_header)
                if not user:
                    self._send_error("Unauthorized", 401)
                    return
                self._send_json({"user": user})
                return

            if path == "/api/data":
                user = get_user_by_token(auth_header)
                if not user:
                    self._send_error("Unauthorized", 401)
                    return
                data = get_user_data(user["id"])
                self._send_json({"user": user, "data": data})
                return

            if path == "/api/users":
                users = get_all_users_summary()
                self._send_json({"count": len(users), "users": users})
                return

            self._send_error("Not found", 404)

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path

            content_length = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
            try:
                body = json.loads(body_raw)
            except Exception:
                body = {}

            auth_header = self.headers.get("Authorization")

            if path == "/api/auth/register":
                username = body.get("username", "")
                phone = body.get("phone", "")
                res = register_user(username, phone)
                if "error" in res:
                    self._send_error(res["error"], res.get("status", 400))
                else:
                    self._send_json(res, 200)
                return

            if path == "/api/auth/login":
                username = body.get("username", "")
                phone = body.get("phone", "")
                res = login_user(username, phone)
                if "error" in res:
                    self._send_error(res["error"], res.get("status", 400))
                else:
                    self._send_json(res, 200)
                return

            if path == "/api/auth/logout":
                user = get_user_by_token(auth_header)
                if user:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET token = ? WHERE id = ?", (f"revoked_{uuid.uuid4().hex}", user["id"]))
                    conn.commit()
                    conn.close()
                self._send_json({"success": True})
                return

            if path == "/api/data":
                user = get_user_by_token(auth_header)
                if not user:
                    self._send_error("Unauthorized", 401)
                    return
                res = save_user_data(user["id"], body)
                self._send_json(res)
                return

            self._send_error("Not found", 404)

    server = ThreadedHTTPServer((host, port), HabitHandler)
    print(f"🚀 Habit Codex Pro Standard Server running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()

# ═══════════════════════════════════════════════════════
# MAIN ENTRYPOINT
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    try:
        import fastapi
        import uvicorn
        run_fastapi_app(port=port, host=host)
    except ImportError:
        print("💡 FastAPI/Uvicorn not found in current environment. Running built-in zero-dependency Python server.")
        run_stdlib_server(port=port, host=host)
