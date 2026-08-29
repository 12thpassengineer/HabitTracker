#!/usr/bin/env bash
# ==============================================================================
#  AdatTracker Pro — Universal 1-Click Hardened Installer
#  Compatible with: Raspberry Pi, Proxmox LXC, Ubuntu, Debian, CentOS, Oracle Linux
#
#  Usage: sudo bash install.sh
#  Or:    git clone <repo> && cd HabitTracker && sudo bash install.sh
# ==============================================================================

set -euo pipefail  # exit on error, undefined vars, pipe failures — NO silent failures

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "   _       _     _ _  _____             _              "
echo "  /_\   __| |__ _| | |_   _| _ __ _ __| |_____ _ _    "
echo " / _ \ / _' / _' | |   | || '_/ _' / _' / -_) '_|   "
echo "/_/ \_\\__,_\__,_|_|   |_||_| \__,_\__,_\___|_|     "
echo -e "${NC}"
echo -e "${GREEN}🚀 AdatTracker Pro — Passwordless Multi-User Habit Tracker${NC}"
echo "============================================================"

# ── Helpers ────────────────────────────────────────────────────
SUDO=""
if [ "$EUID" -ne 0 ]; then
    if command -v sudo &>/dev/null; then
        SUDO="sudo"
    else
        echo -e "${RED}❌ Please run as root or install sudo.${NC}"
        exit 1
    fi
fi

required_download() {
    local url="$1"
    local dest="$2"
    echo "  → Downloading $(basename "$dest")..."
    $SUDO curl -fsSL "$url" -o "$dest" || {
        echo -e "${RED}❌ FATAL: Failed to download required file: $url${NC}"
        echo -e "${RED}   Please check your internet connection and retry.${NC}"
        exit 1
    }
}

optional_download() {
    local url="$1"
    local dest="$2"
    $SUDO curl -fsSL "$url" -o "$dest" 2>/dev/null || true
}

# ── Configuration ──────────────────────────────────────────────
INSTALL_DIR="/opt/adattracker"
APP_USER="adattracker"
APP_GROUP="adattracker"
PORT="${PORT:-8000}"
REPO_BASE="https://raw.githubusercontent.com/12thpassengineer/HabitTracker/main"

# ── Step 1: System Dependencies ────────────────────────────────
echo -e "\n${YELLOW}[1/5] Installing system dependencies...${NC}"
if command -v apt-get &>/dev/null; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq python3 python3-pip python3-venv sqlite3 curl git
elif command -v dnf &>/dev/null; then
    $SUDO dnf install -y python3 python3-pip sqlite curl git
elif command -v yum &>/dev/null; then
    $SUDO yum install -y python3 python3-pip sqlite curl git
elif command -v apk &>/dev/null; then
    $SUDO apk add --no-cache python3 py3-pip sqlite curl git bash
else
    echo -e "${RED}❌ Unsupported package manager. Install python3, pip, sqlite3, curl, git manually.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ System dependencies installed${NC}"

# ── Step 2: Create Unprivileged User ───────────────────────────
echo -e "\n${YELLOW}[2/5] Creating service user '${APP_USER}'...${NC}"
if ! id -u "$APP_USER" &>/dev/null; then
    $SUDO useradd -r -s /usr/sbin/nologin -d "$INSTALL_DIR" -c "AdatTracker Service" "$APP_USER" 2>/dev/null \
        || $SUDO adduser -S -D -H -h "$INSTALL_DIR" -s /sbin/nologin "$APP_USER" 2>/dev/null \
        || { echo -e "${RED}❌ Failed to create service user.${NC}"; exit 1; }
    echo -e "${GREEN}✓ Created service user '${APP_USER}'${NC}"
else
    echo -e "${GREEN}✓ Service user '${APP_USER}' already exists${NC}"
fi

# ── Step 3: Download Application Files ────────────────────────
echo -e "\n${YELLOW}[3/5] Installing application files to ${INSTALL_DIR}...${NC}"
$SUDO mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/backups" "$INSTALL_DIR/scripts"

if [ -f "server.py" ] && [ -f "requirements.txt" ]; then
    # Running from inside a cloned repo
    echo "  → Copying from local clone..."

    # Required files — fail hard if missing
    for f in server.py config.py database.py security.py email_service.py requirements.txt; do
        [ -f "$f" ] || { echo -e "${RED}❌ Missing required file: $f${NC}"; exit 1; }
        $SUDO cp "$f" "$INSTALL_DIR/$f"
    done

    # Frontend HTML — required
    HTML_SRC=""
    [ -f "habit_tracker.html" ] && HTML_SRC="habit_tracker.html"
    [ -f "frontend/index.html" ] && HTML_SRC="frontend/index.html"
    if [ -z "$HTML_SRC" ]; then
        echo -e "${RED}❌ Missing required frontend file: habit_tracker.html or frontend/index.html${NC}"
        exit 1
    fi
    $SUDO cp "$HTML_SRC" "$INSTALL_DIR/habit_tracker.html"

    # Optional files
    [ -f "scripts/backup.sh" ] && $SUDO cp "scripts/backup.sh" "$INSTALL_DIR/scripts/backup.sh"

else
    # Downloading fresh from GitHub
    echo "  → Downloading from GitHub..."

    # Required application files — all must succeed
    required_download "$REPO_BASE/server.py"          "$INSTALL_DIR/server.py"
    required_download "$REPO_BASE/config.py"          "$INSTALL_DIR/config.py"
    required_download "$REPO_BASE/database.py"        "$INSTALL_DIR/database.py"
    required_download "$REPO_BASE/security.py"        "$INSTALL_DIR/security.py"
    required_download "$REPO_BASE/email_service.py"   "$INSTALL_DIR/email_service.py"
    required_download "$REPO_BASE/requirements.txt"   "$INSTALL_DIR/requirements.txt"
    required_download "$REPO_BASE/habit_tracker.html" "$INSTALL_DIR/habit_tracker.html"

    # Optional backup script
    optional_download "$REPO_BASE/scripts/backup.sh" "$INSTALL_DIR/scripts/backup.sh"
fi

echo -e "${GREEN}✓ Application files installed${NC}"

# ── Step 4: Python Virtual Environment ────────────────────────
echo -e "\n${YELLOW}[4/5] Setting up Python virtual environment...${NC}"
[ -d "$INSTALL_DIR/venv" ] || $SUDO python3 -m venv "$INSTALL_DIR/venv"

$SUDO "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
$SUDO "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
echo -e "${GREEN}✓ Python environment ready${NC}"

# ── Generate .env if missing ──────────────────────────────────
if [ ! -f "$INSTALL_DIR/.env" ]; then
    SECRET_KEY_GEN=$($SUDO "$INSTALL_DIR/venv/bin/python3" -c "import secrets; print(secrets.token_hex(32))")
    $SUDO tee "$INSTALL_DIR/.env" > /dev/null <<EOF
# ==============================================================================
# AdatTracker Pro — Environment Configuration
# ==============================================================================
APP_ENV=production
SECRET_KEY=${SECRET_KEY_GEN}
PORT=${PORT}
HOST=0.0.0.0
DATA_DIR=${INSTALL_DIR}/data

# ── IMPORTANT: Update these before exposing the service publicly ──────────────
# Set BASE_URL and ALLOWED_ORIGINS to your actual public domain.
# If using Cloudflare Tunnel: BASE_URL=https://habits.yourdomain.com
# Do NOT leave as localhost for a public-facing server.
# IMPORTANT: For public hosting behind Cloudflare, replace these with your public HTTPS domain.
BASE_URL=http://localhost:${PORT}
ALLOWED_ORIGINS=http://localhost:${PORT},http://127.0.0.1:${PORT}

# ── Docker bind address ──────────────────────────────────────────────────────
# Only relevant to docker-compose. Keep 0.0.0.0 for local/LAN use.
# Set BIND_HOST=127.0.0.1 for Oracle + Cloudflare Tunnel production.
BIND_HOST=0.0.0.0

# ── Email Backend ─────────────────────────────────────────────────────────────
# Local testing: console
# Production: configure resend or smtp BEFORE public launch.
EMAIL_BACKEND=console
# RESEND_API_KEY=re_your_key_here
# FROM_EMAIL=noreply@yourdomain.com
# FROM_NAME=AdatTracker Pro
EOF
    echo -e "${GREEN}✓ Generated .env with random SECRET_KEY${NC}"
fi

# Set strict permissions
$SUDO chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR" 2>/dev/null || true
$SUDO chmod 750 "$INSTALL_DIR" "$INSTALL_DIR/data"
$SUDO chmod 600 "$INSTALL_DIR/.env"
[ -f "$INSTALL_DIR/scripts/backup.sh" ] && $SUDO chmod +x "$INSTALL_DIR/scripts/backup.sh"

# ── Step 5: Systemd Service ────────────────────────────────────
echo -e "\n${YELLOW}[5/5] Configuring systemd service...${NC}"
if [ -d "/etc/systemd/system" ]; then
    $SUDO tee /etc/systemd/system/adattracker.service > /dev/null <<EOF
[Unit]
Description=AdatTracker Pro — Multi-User Habit Tracker
After=network.target
Wants=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/server.py
Restart=always
RestartSec=5
EnvironmentFile=-${INSTALL_DIR}/.env
StandardOutput=journal
StandardError=journal

# Hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable adattracker.service
    $SUDO systemctl restart adattracker.service
    echo -e "${GREEN}✓ Systemd service started and enabled on boot${NC}"

    # Verify service started
    sleep 2
    if $SUDO systemctl is-active --quiet adattracker.service; then
        echo -e "${GREEN}✓ Service is running${NC}"
    else
        echo -e "${RED}⚠  Service may have failed — check: sudo journalctl -u adattracker -n 50${NC}"
    fi
fi

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo -e "\n${GREEN}============================================================${NC}"
echo -e "${GREEN}🎉 AdatTracker Pro installed successfully!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo -e "👉 ${CYAN}Local URL:${NC}       http://localhost:${PORT}"
echo -e "👉 ${CYAN}Network URL:${NC}     http://${IP_ADDR}:${PORT}"
echo -e "👉 ${CYAN}Database:${NC}        ${INSTALL_DIR}/data/adattracker.db"
echo -e "👉 ${CYAN}Service user:${NC}    ${APP_USER} (non-root)"
echo -e "👉 ${CYAN}Config file:${NC}     ${INSTALL_DIR}/.env"
echo -e "👉 ${CYAN}Service logs:${NC}    sudo journalctl -u adattracker -f"
echo -e "👉 ${CYAN}Service status:${NC}  sudo systemctl status adattracker"
echo ""
echo -e "${YELLOW}⚠  IMPORTANT — PRODUCTION SETUP REQUIRED BEFORE GOING PUBLIC:${NC}"
echo -e "   Edit ${INSTALL_DIR}/.env and set:"
echo -e "   1. BASE_URL=https://your-actual-domain.com"
echo -e "   2. ALLOWED_ORIGINS=https://your-actual-domain.com"
echo -e "   3. EMAIL_BACKEND=resend  (and set RESEND_API_KEY)"
echo -e "   4. Set up Cloudflare Tunnel — do NOT open port ${PORT} in firewall!"
echo -e "   Then: sudo systemctl restart adattracker"
echo -e "${GREEN}============================================================${NC}"
