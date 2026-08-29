<div align="center">

# ⚡ AdatTracker Pro

**A Hardened, Minimal, Self-Hostable, Multi-User Habit Tracker & Sticky Notes Dashboard.**  
*Built for OLED dark-mode enthusiasts, homelab owners, and high performers.*

[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker Ready](https://img.shields.io/badge/Docker-Non--Root%20UID%201001-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Cloudflare Tunnel](https://img.shields.io/badge/Cloudflare-Tunnel%20Ready-F38020.svg?logo=cloudflare&logoColor=white)](https://www.cloudflare.com/)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20Mode-003B57.svg?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

[Quick Start](#-quick-start) • [Authentication](#-authentication) • [Security Highlights](#-security-highlights) • [Cloudflare Tunnel](#-cloudflare-tunnel-production) • [Backup & Restore](#-backup--restore) • [Configuration](#-configuration)

</div>

---

## 📸 Overview

AdatTracker Pro is a self-hostable multi-user habit tracker built with a **Passwordless Email OTP authentication system**, **server-side HttpOnly cookie sessions**, **SQLite in WAL mode**, and strict **multi-tenant data isolation**. It runs on under **35 MB RAM** and is optimized for **Oracle Cloud Ampere ARM**, **Raspberry Pi**, **Proxmox**, and **Docker**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AdatTracker Pro — FULLSCREEN DESKTOP DASHBOARD                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  [🎯 Today: 100%]  [🔥 Top Streak: 18d]  [📈 Month: 94%]  [🏆 Score: 14.8] │
├─────────────────────────────────────────────────────────────────────────────┤
│  ⠿ Morning Meditation  [Mind]   [🔥14] [95%]   [✓][✓][✓][✓][✓][✓][✓][✓]  │
│  ⠿ Workout / Gym       [Health] [🔥 8] [88%]   [✓][✓][✓][✓][ ][✓][✓][✓]  │
│  ⠿ Read 20 Pages       [Mind]   [🔥21] [100%]  [✓][✓][✓][✓][✓][✓][✓][✓]  │
│  ⠿ Deep Work Session   [Work]   [🔥 5] [80%]   [✓][✓][✓][✓][✓][ ][✓][✓]  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔑 Authentication

AdatTracker uses **Passwordless Email OTP** — no passwords, no phone numbers.

### How it works:

**Enroll (first time):**
1. Click **"Enroll New User"** tab
2. Enter your username + email
3. Receive a 6-digit code in your inbox (valid 10 minutes)
4. Enter the code → account created → logged in

**Log In (returning):**
1. Click **"Log In"** tab
2. Enter your username or email
3. Receive a 6-digit code in your inbox
4. Enter the code → logged in

Sessions are stored in **secure HttpOnly cookies** that automatically expire after 30 days. There are no passwords to forget or bearer tokens stored in localStorage.

---

## 🛡️ Security Highlights

| Feature | Detail |
|---|---|
| **Passwordless OTP** | 6-digit code via HMAC-SHA256 hash, 10-min expiry, 5-attempt lockout |
| **Purpose Enforcement** | Signup OTP only works for signup; login OTP only works for login |
| **Atomic OTP Consumption** | Race condition prevented — OTP is marked used in a single DB transaction |
| **HttpOnly Cookies** | Zero tokens in `localStorage`. `Secure` + `SameSite=Lax` in production |
| **CSRF Protection** | `X-CSRF-Token` header required on all state-mutating requests including logout |
| **User Data Isolation** | `user_id` comes from the authenticated session only — never from request body |
| **Atomic Rate Limiting** | IP and email throttling in a single transaction, no race condition bypass |
| **Non-Root Execution** | Runs as `adattracker` user (UID 1001) in Docker and systemd |
| **SQLite WAL Mode** | `PRAGMA journal_mode=WAL; foreign_keys=ON; busy_timeout=5000` |
| **Port Protection** | Port 8000 is never exposed directly — Cloudflare Tunnel is the only public ingress |
| **No `/api/users`** | Public user enumeration endpoint removed entirely |

---

## ⚡ Quick Start

### Option 1 — Docker Compose (recommended for homelabs)

```bash
git clone https://github.com/12thpassengineer/HabitTracker.git
cd HabitTracker
cp .env.example .env          # edit .env with your settings
docker compose up -d
```

Open `http://localhost:8000`

> **Production note:** In `.env` set `BIND_HOST=127.0.0.1` so port 8000 is never publicly reachable. Use Cloudflare Tunnel for public access.

---

### Option 2 — One-Line Native Installer (Oracle Cloud / Raspberry Pi / VPS)

```bash
git clone https://github.com/12thpassengineer/HabitTracker.git
cd HabitTracker
sudo bash install.sh
```

The installer:
- Creates an unprivileged `adattracker` system user
- Downloads all required files (exits with a clear error if anything fails)
- Sets up a Python venv and installs dependencies
- Generates a random `SECRET_KEY`
- Registers and starts a systemd service

> **⚠️ After installing:** Edit `/opt/adattracker/.env` and set `BASE_URL`, `ALLOWED_ORIGINS`, and `EMAIL_BACKEND` before exposing the service publicly.

---

### Option 3 — Native Python (local dev)

```bash
git clone https://github.com/12thpassengineer/HabitTracker.git
cd HabitTracker
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

---

## 🌐 Cloudflare Tunnel (Production)

For Oracle Cloud or any VPS, use Cloudflare Tunnel so port 8000 is **never** publicly accessible:

```
Internet → Cloudflare → Cloudflare Tunnel → Oracle VM:127.0.0.1:8000 → AdatTracker
```

**Step-by-step:**

```bash
# 1. Install cloudflared
curl -L -o cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb

# 2. Authenticate
cloudflared tunnel login

# 3. Create tunnel
cloudflared tunnel create adattracker-tunnel

# 4. Configure
sudo tee /etc/cloudflared/config.yml > /dev/null <<EOF
tunnel: <YOUR-TUNNEL-UUID>
credentials-file: /etc/cloudflared/<YOUR-TUNNEL-UUID>.json

ingress:
  - hostname: habits.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
EOF

# 5. Enable service
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

**Then update `.env`:**
```ini
APP_ENV=production
BASE_URL=https://habits.yourdomain.com
ALLOWED_ORIGINS=https://habits.yourdomain.com
BIND_HOST=127.0.0.1         # Port 8000 binds only to localhost
EMAIL_BACKEND=resend
RESEND_API_KEY=re_your_key
FROM_EMAIL=noreply@yourdomain.com
```

**Verify protection:**
```bash
# This must FAIL (connection refused or timeout):
curl http://YOUR_ORACLE_PUBLIC_IP:8000/health

# This must SUCCEED:
curl https://habits.yourdomain.com/health
```

---

## 💾 Backup & Restore

All data lives in a single file: `/opt/adattracker/data/adattracker.db`

### Automated backup (WAL-safe):
```bash
sudo bash /opt/adattracker/scripts/backup.sh
```

### Schedule nightly backups:
```bash
crontab -e
# Add:
0 2 * * * /opt/adattracker/scripts/backup.sh
```

### Restore:
```bash
sudo systemctl stop adattracker
sudo cp /opt/adattracker/backups/adattracker_backup_YYYYMMDD_HHMMSS.db \
        /opt/adattracker/data/adattracker.db
sudo systemctl start adattracker
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `local` | `local` or `production` |
| `SECRET_KEY` | — | **Required.** Random 64-char hex. Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `BASE_URL` | `http://localhost:8000` | Your public URL. Set to your domain in production. |
| `ALLOWED_ORIGINS` | `http://localhost:8000` | CORS whitelist. Set to your domain in production. |
| `EMAIL_BACKEND` | `console` | `console` \| `resend` \| `smtp` |
| `RESEND_API_KEY` | — | Required when `EMAIL_BACKEND=resend` |
| `FROM_EMAIL` | — | Sender email address |
| `DATA_DIR` | `/app/data` | SQLite database directory |
| `BIND_HOST` | `0.0.0.0` | Set to `127.0.0.1` in production (Docker) |
| `PORT` | `8000` | Application port |

---

## 🧪 Security Test Suite

Run the automated 16-point security test suite:

```bash
pip install httpx fastapi
python tests/test_security.py
```

Tests cover: user data isolation, unauthenticated access rejection, OTP expiry, OTP single-use, OTP purpose enforcement, rate limiting, attempt lockout, CSRF protection, anti-enumeration, SQL injection, XSS payloads, payload size limits, and health endpoint metadata leakage.

---

## 🏗️ Target Architecture (Initial Launch)

```
Oracle Cloud Ampere ARM
  └── 2 OCPU / 12 GB RAM / 200 GB storage
      └── AdatTracker Pro (Python, FastAPI, SQLite WAL)
          └── Cloudflare Tunnel → habits.yourdomain.com
```

SQLite handles ~200 concurrent users comfortably. No Redis, Kubernetes, PostgreSQL, or microservices needed.
