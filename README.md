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

[Quick Start](#-quick-start) • [Security & Scalability](#-security--scalability) • [Cloudflare Tunnel Setup](#-cloudflare-tunnel-deployment) • [Installation Options](#-installation-options) • [Backup & Restore](#-backup--restore)

</div>

---

## 📸 Overview

AdatTracker Pro is a self-hostable web application designed for personal productivity, habit building, and thought capture.

It is engineered with a **Passwordless Email OTP authentication system**, **server-side HttpOnly cookie sessions**, **SQLite in WAL mode**, and strict **multi-tenant data isolation**. It consumes less than **35 MB of RAM** and is optimized for deployment on **Oracle Cloud Ampere ARM**, **Raspberry Pi**, **Proxmox LXC**, and **Docker**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  AdatTracker Pro — FULLSCREEN DESKTOP DASHBOARD                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  [🎯 Today: 100%]   [🔥 Top Streak: 18d]   [📈 Month: 94%]   [🏆 Score: 14.8] │
├─────────────────────────────────────────────────────────────────────────────┤
│  ⠿ Morning Meditation  [Mind]    [🔥14] [ 95%]   [✓][✓][✓][✓][✓][✓][✓][✓]  │
│  ⠿ Workout / Gym       [Health]  [🔥 8] [ 88%]   [✓][✓][✓][✓][ ][✓][✓][✓]  │
│  ⠿ Read 20 Pages       [Mind]    [🔥21] [100%]   [✓][✓][✓][✓][✓][✓][✓][✓]  │
│  ⠿ Deep Work Session   [Work]    [🔥 5] [ 80%]   [✓][✓][✓][✓][✓][ ][✓][✓]  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛡️ Security & Scalability Highlights

- **🔑 Passwordless Email OTP**: Single-use 6-digit OTP with 10-minute expiry and max 5 attempts. OTPs are stored hashed using HMAC-SHA256 with server `SECRET_KEY` salt.
- **🍪 HttpOnly Cookie Sessions**: Session tokens are stored exclusively in `HttpOnly`, `SameSite=Lax`, and `Secure` (in production) cookies. Zero sensitive tokens in `localStorage`.
- **🛡️ CSRF Double-Submit Protection**: State-mutating API requests validate `X-CSRF-Token` headers.
- **🔒 Strict User Data Isolation**: The server resolves `current_user.id` strictly from the authenticated session. Never trusts `user_id` query params.
- **⏱️ Database-Backed Rate Limiting**: IP-based and account-based rate limits on OTP generation and authentication endpoints.
- **👤 Non-Root Execution**: Runs under an unprivileged `adattracker` user (`UID 1001`) in Docker and systemd.
- **🗄️ SQLite in WAL Mode**: Concurrency-optimized SQLite (`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;`).
- **🌐 Cloudflare Tunnel Native**: Production traffic routes through Cloudflare Tunnel. Port 8000 is never exposed directly to the public internet.

---

## ⚡ Quick Start

### 1. Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/12thpassengineer/HabitTracker.git
cd HabitTracker

# Copy environment template
cp .env.example .env

# Launch container
docker compose up -d
```
Access the application at `http://localhost:8000`.

---

### 2. One-Line Universal Install (Oracle Cloud / Raspberry Pi / Proxmox)

```bash
curl -sSL https://raw.githubusercontent.com/12thpassengineer/HabitTracker/main/install.sh | bash
```

---

### 3. Native Python Setup

```bash
git clone https://github.com/12thpassengineer/HabitTracker.git
cd HabitTracker

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python server.py
```

---

## 🌐 Cloudflare Tunnel Deployment (Oracle Cloud / VPS)

For a production deployment on Oracle Cloud Ampere ARM:

1. **Keep Port 8000 Private**: In your Oracle Cloud VCN Security List, do **NOT** open port 8000 to `0.0.0.0/0`.
2. **Install Cloudflare Tunnel (`cloudflared`)**:
   ```bash
   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
   sudo dpkg -i cloudflared.deb
   cloudflared tunnel login
   cloudflared tunnel create adattracker-tunnel
   ```
3. **Configure Ingress (`/etc/cloudflared/config.yml`)**:
   ```yaml
   tunnel: <TUNNEL_UUID>
   credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json

   ingress:
     - hostname: habits.yourdomain.com
       service: http://localhost:8000
     - service: http_status:404
   ```
4. **Start Cloudflare Tunnel Service**:
   ```bash
   sudo cloudflared service install
   sudo systemctl enable --now cloudflared
   ```
5. **Update `.env`**:
   ```ini
   APP_ENV=production
   BASE_URL=https://habits.yourdomain.com
   ALLOWED_ORIGINS=https://habits.yourdomain.com
   EMAIL_BACKEND=smtp # or console/resend
   ```

---

## 💾 Backup & Restore

AdatTracker stores all data in a single SQLite database (`./data/adattracker.db`).

### Automated Backup Script
Run the included WAL-safe backup script:
```bash
bash scripts/backup.sh
```

### Schedule Daily Backups in Cron
```bash
# Open crontab
crontab -e

# Run every night at 2:00 AM
0 2 * * * /opt/adattracker/scripts/backup.sh
```

### Restore Database
```bash
cp /opt/adattracker/backups/adattracker_backup_YYYYMMDD_HHMMSS.db /opt/adattracker/data/adattracker.db
sudo systemctl restart adattracker
```

---

## 🧪 Security & Multi-Tenant Test Suite

Run the automated test suite verifying all 16 security requirements:

```bash
python tests/test_security.py
```

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
