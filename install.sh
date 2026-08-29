#!/usr/bin/env bash
# ==============================================================================
#  AdatTracker Pro - Universal 1-Click Hardened Installer
#  Compatible with: Raspberry Pi, Proxmox LXC, Ubuntu, Debian, CentOS, Oracle Linux
# ==============================================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  _    _       _     _ _      _____          _             _____             "
echo " | |  | |     | |   (_) |    / ____|        | |           |  __ \            "
echo " | |__| | __ _| |__  _| |_  | |     ___   __| | _____  __ | |__) | __ ___    "
echo " |  __  |/ _\` | '_ \| | __| | |    / _ \ / _\` |/ _ \ \/ / |  ___/ '__/ _ \   "
echo " | |  | | (_| | |_) | | |_  | |___| (_) | (_| |  __/>  <  | |   | | | (_) |  "
echo " |_|  |_|\__,_|_.__/|_|\__|  \_____\___/ \__,_|\___/_/\_\ |_|   |_|  \___/   "
echo -e "${NC}"
echo -e "${GREEN}🚀 AdatTracker Pro — Passwordless Multi-User Cloud & Self-Hosted Engine${NC}"
echo "=============================================================================="

# Check if run as root or with sudo
SUDO=""
if [ "$EUID" -ne 0 ]; then
    if command -v sudo &>/dev/null; then
        SUDO="sudo"
    else
        echo -e "${RED}❌ Please run this script as root or install sudo.${NC}"
        exit 1
    fi
fi

INSTALL_DIR="/opt/adattracker"
APP_USER="adattracker"
APP_GROUP="adattracker"
PORT=${PORT:-8000}

# 1. Install System Dependencies
echo -e "\n${YELLOW}1/5 Installing System Dependencies...${NC}"
if command -v apt-get &>/dev/null; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq python3 python3-pip python3-venv sqlite3 curl git
elif command -v yum &>/dev/null; then
    $SUDO yum install -y python3 python3-pip sqlite3 curl git
elif command -v dnf &>/dev/null; then
    $SUDO dnf install -y python3 python3-pip sqlite3 curl git
elif command -v apk &>/dev/null; then
    $SUDO apk add --no-cache python3 py3-pip sqlite curl git bash
fi

# 2. Create Unprivileged Application User
echo -e "\n${YELLOW}2/5 Creating unprivileged service user '${APP_USER}'...${NC}"
if ! id -u "$APP_USER" &>/dev/null; then
    $SUDO useradd -r -s /usr/sbin/nologin -d "$INSTALL_DIR" -c "AdatTracker Service User" "$APP_USER" 2>/dev/null || $SUDO adduser -S -D -H -h "$INSTALL_DIR" -s /sbin/nologin "$APP_USER" 2>/dev/null || true
    echo -e "${GREEN}✓ Created service user '${APP_USER}'${NC}"
fi

# 3. Setup Install Directory & Files
echo -e "\n${YELLOW}3/5 Setting up Application Files in ${INSTALL_DIR}...${NC}"
$SUDO mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/backups" "$INSTALL_DIR/backend" "$INSTALL_DIR/frontend" "$INSTALL_DIR/scripts"

REPO_RAW_URL="https://raw.githubusercontent.com/12thpassengineer/HabitTracker/main"

# Download or copy application files
if [ -f "server.py" ] && [ -f "habit_tracker.html" ]; then
    echo "📄 Copying local files..."
    $SUDO cp -r backend/* "$INSTALL_DIR/backend/" 2>/dev/null || true
    $SUDO cp -r frontend/* "$INSTALL_DIR/frontend/" 2>/dev/null || true
    $SUDO cp server.py "$INSTALL_DIR/server.py"
    $SUDO cp habit_tracker.html "$INSTALL_DIR/habit_tracker.html"
    $SUDO cp requirements.txt "$INSTALL_DIR/requirements.txt"
    $SUDO cp scripts/backup.sh "$INSTALL_DIR/scripts/backup.sh" 2>/dev/null || true
else
    echo "🌐 Downloading latest release from GitHub..."
    $SUDO curl -sSL "$REPO_RAW_URL/server.py" -o "$INSTALL_DIR/server.py"
    $SUDO curl -sSL "$REPO_RAW_URL/habit_tracker.html" -o "$INSTALL_DIR/habit_tracker.html"
    $SUDO curl -sSL "$REPO_RAW_URL/requirements.txt" -o "$INSTALL_DIR/requirements.txt"
    $SUDO curl -sSL "$REPO_RAW_URL/backend/config.py" -o "$INSTALL_DIR/backend/config.py" 2>/dev/null || true
    $SUDO curl -sSL "$REPO_RAW_URL/backend/database.py" -o "$INSTALL_DIR/backend/database.py" 2>/dev/null || true
    $SUDO curl -sSL "$REPO_RAW_URL/backend/security.py" -o "$INSTALL_DIR/backend/security.py" 2>/dev/null || true
    $SUDO curl -sSL "$REPO_RAW_URL/backend/email_service.py" -o "$INSTALL_DIR/backend/email_service.py" 2>/dev/null || true
    $SUDO curl -sSL "$REPO_RAW_URL/backend/server.py" -o "$INSTALL_DIR/backend/server.py" 2>/dev/null || true
    $SUDO curl -sSL "$REPO_RAW_URL/frontend/index.html" -o "$INSTALL_DIR/frontend/index.html" 2>/dev/null || true
fi

# 4. Setup Python Virtual Environment
echo -e "\n${YELLOW}4/5 Setting up Python virtual environment and dependencies...${NC}"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    $SUDO python3 -m venv "$INSTALL_DIR/venv"
fi

$SUDO "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
$SUDO "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# Generate .env with random SECRET_KEY if not present
if [ ! -f "$INSTALL_DIR/.env" ]; then
    SECRET_KEY_GEN=$($SUDO "$INSTALL_DIR/venv/bin/python3" -c "import secrets; print(secrets.token_hex(32))")
    cat <<EOF | $SUDO tee "$INSTALL_DIR/.env" >/dev/null
APP_ENV=production
SECRET_KEY=$SECRET_KEY_GEN
PORT=$PORT
HOST=0.0.0.0
BASE_URL=http://localhost:$PORT
ALLOWED_ORIGINS=http://localhost:$PORT,http://127.0.0.1:$PORT
EMAIL_BACKEND=console
FROM_EMAIL=noreply@adattracker.local
EOF
fi

# Permissions
$SUDO chown -R "$APP_USER:$APP_GROUP" "$INSTALL_DIR" 2>/dev/null || true
$SUDO chmod 750 "$INSTALL_DIR" "$INSTALL_DIR/data" 2>/dev/null || true
$SUDO chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true

# 5. Setup Systemd Service
echo -e "\n${YELLOW}5/5 Configuring Systemd Service for 24/7 Background Operation...${NC}"
if [ -d "/etc/systemd/system" ]; then
    cat <<EOF | $SUDO tee /etc/systemd/system/adattracker.service >/dev/null
[Unit]
Description=AdatTracker Pro Multi-User Application
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/server.py
Restart=always
RestartSec=5
EnvironmentFile=-$INSTALL_DIR/.env
Environment=PORT=$PORT
Environment=HOST=0.0.0.0

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
    echo -e "${GREEN}✓ Systemd service configured and started!${NC}"
fi

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo -e "\n${GREEN}==============================================================================${NC}"
echo -e "${GREEN}🎉 AdatTracker Pro successfully installed and running!${NC}"
echo -e "${GREEN}==============================================================================${NC}"
echo -e "👉 ${CYAN}Access URL:${NC}      http://${IP_ADDR}:${PORT}"
echo -e "👉 ${CYAN}Localhost URL:${NC}   http://localhost:${PORT}"
echo -e "👉 ${CYAN}Database Path:${NC}   ${INSTALL_DIR}/data/adattracker.db (SQLite WAL Mode)"
echo -e "👉 ${CYAN}Service User:${NC}    ${APP_USER} (Non-Root)"
echo -e "👉 ${CYAN}Service Status:${NC}  sudo systemctl status adattracker"
echo -e "👉 ${CYAN}Live Logs:${NC}       sudo journalctl -u adattracker -f"
echo -e "${GREEN}==============================================================================${NC}\n"
