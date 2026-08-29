#!/usr/bin/env bash
# ==============================================================================
#  Habit Codex Pro - Universal 1-Click Installer
#  Compatible with: Raspberry Pi, Proxmox LXC, Ubuntu, Debian, CentOS, macOS
# ==============================================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "  _    _       _     _ _      _____          _             _____             "
echo " | |  | |     | |   (_) |    / ____|        | |           |  __ \            "
echo " | |__| | __ _| |__  _| |_  | |     ___   __| | _____  __ | |__) | __ ___    "
echo " |  __  |/ _\` | '_ \| | __| | |    / _ \ / _\` |/ _ \ \/ / |  ___/ '__/ _ \   "
echo " | |  | | (_| | |_) | | |_  | |___| (_) | (_| |  __/>  <  | |   | | | (_) |  "
echo " |_|  |_|\__,_|_.__/|_|\__|  \_____\___/ \__,_|\___/_/\_\ |_|   |_|  \___/   "
echo -e "${NC}"
echo -e "${GREEN}🚀 Multi-User Cloud & Self-Hosted Habit Tracker Installer${NC}"
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

INSTALL_DIR="/opt/habit-tracker"
PORT=${PORT:-8000}

# 1. Install prerequisites
echo -e "\n${YELLOW}1/4 Checking & Installing System Dependencies...${NC}"
if command -v apt-get &>/dev/null; then
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq python3 python3-pip curl git
elif command -v yum &>/dev/null; then
    $SUDO yum install -y python3 python3-pip curl git
elif command -v dnf &>/dev/null; then
    $SUDO dnf install -y python3 python3-pip curl git
elif command -v apk &>/dev/null; then
    $SUDO apk add --no-cache python3 py3-pip curl git bash
fi

# 2. Setup install directory
echo -e "\n${YELLOW}2/4 Setting up Application Files in ${INSTALL_DIR}...${NC}"
$SUDO mkdir -p "$INSTALL_DIR/data"

# If running from cloned directory, copy local files; otherwise download from repo
if [ -f "server.py" ] && [ -f "habit_tracker.html" ]; then
    echo "📄 Copying local files to $INSTALL_DIR..."
    $SUDO cp -r server.py habit_tracker.html requirements.txt "$INSTALL_DIR/"
else
    echo "🌐 Downloading latest release from repository..."
    REPO_RAW_URL="https://raw.githubusercontent.com/12thpassengineer/HabitTracker/main"
    $SUDO curl -sSL "$REPO_RAW_URL/server.py" -o "$INSTALL_DIR/server.py"
    $SUDO curl -sSL "$REPO_RAW_URL/habit_tracker.html" -o "$INSTALL_DIR/habit_tracker.html"
    $SUDO curl -sSL "$REPO_RAW_URL/requirements.txt" -o "$INSTALL_DIR/requirements.txt"
fi

# Optional: Install Python dependencies for FastAPI (falls back automatically to stdlib if fails)
if command -v pip3 &>/dev/null; then
    echo "📦 Installing optional FastAPI dependencies (for maximum performance)..."
    $SUDO pip3 install -r "$INSTALL_DIR/requirements.txt" --break-system-packages 2>/dev/null || $SUDO pip3 install -r "$INSTALL_DIR/requirements.txt" 2>/dev/null || true
fi

# 3. Setup systemd service
echo -e "\n${YELLOW}3/4 Configuring Systemd Service for 24/7 Background Startup...${NC}"
if [ -d "/etc/systemd/system" ]; then
    cat <<EOF | $SUDO tee /etc/systemd/system/habit-tracker.service >/dev/null
[Unit]
Description=Habit Codex Pro Multi-User Application
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/server.py
Restart=always
RestartSec=5
Environment=PORT=$PORT
Environment=HOST=0.0.0.0

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable habit-tracker.service
    $SUDO systemctl restart habit-tracker.service
    echo -e "${GREEN}✓ Systemd service configured and running!${NC}"
fi

# 4. Display Access Details
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo -e "\n${GREEN}==============================================================================${NC}"
echo -e "${GREEN}🎉 Habit Codex Pro successfully installed and running!${NC}"
echo -e "${GREEN}==============================================================================${NC}"
echo -e "👉 ${CYAN}Local Access URL:${NC}   http://${IP_ADDR}:${PORT}"
echo -e "👉 ${CYAN}Localhost URL:${NC}      http://localhost:${PORT}"
echo -e "👉 ${CYAN}Database Path:${NC}      ${INSTALL_DIR}/data/habit_codex.db"
echo -e "👉 ${CYAN}Service Status:${NC}     sudo systemctl status habit-tracker"
echo -e "👉 ${CYAN}Service Restart:${NC}    sudo systemctl restart habit-tracker"
echo -e "${GREEN}==============================================================================${NC}"
echo -e "Enjoy leveling up your habits every day! 🚀\n"
