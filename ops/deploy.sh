#!/bin/bash
# EAP-Sports: One-command deploy to production VPS
# Usage: ./ops/deploy.sh [user@host]
set -euo pipefail

REMOTE="${1:-root@vexp.me}"
APP_DIR="/opt/eap-sports"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "[INFO] Deploying EAP-Sports to $REMOTE..."

# ─── 1. Sync project files ───────────────────────────────
echo "[INFO] Syncing files..."
rsync -azP --delete \
    --exclude='.venv' --exclude='node_modules' --exclude='__pycache__' \
    --exclude='.git' --exclude='*.pyc' --exclude='.skills' \
    --exclude='backups' --exclude='eap_sports.db' \
    "$PROJECT_DIR/" "$REMOTE:$APP_DIR/"

# ─── 2. Remote setup ─────────────────────────────────────
echo "[INFO] Running remote setup..."
ssh "$REMOTE" bash <<'EOF'
set -euo pipefail
APP_DIR="/opt/eap-sports"
cd "$APP_DIR"

# Python venv
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

# Playwright browser
.venv/bin/python -m playwright install chromium --with-deps 2>/dev/null || true

# Init DB
.venv/bin/python -c "from core.database import init_db; init_db()"

# Build TMA
cd tma && npm install --silent && npm run build && cd ..

# Build Astro site
cd web && npm install --silent && npm run build && cd ..

# Install systemd units
cp ops/eap-api.service /etc/systemd/system/
cp ops/eap-bot.service /etc/systemd/system/
cp ops/eap-content.service /etc/systemd/system/
cp ops/eap-content.timer /etc/systemd/system/
systemctl daemon-reload

# Install nginx config
cp ops/nginx.conf /etc/nginx/sites-available/eap-sports
ln -sf /etc/nginx/sites-available/eap-sports /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Make scripts executable
chmod +x ops/backup.sh ops/watchdog.sh

# Install cron jobs
(crontab -l 2>/dev/null | grep -v eap-sports; echo "0 * * * * $APP_DIR/ops/backup.sh >> /var/log/eap-backup.log 2>&1"; echo "*/5 * * * * $APP_DIR/ops/watchdog.sh >> /var/log/eap-watchdog.log 2>&1") | crontab -

# Start/restart services
systemctl enable --now eap-api eap-bot eap-content.timer
systemctl restart eap-api eap-bot

echo "[SUCCESS] Deploy complete!"
EOF

echo ""
echo "[INFO] EAP-Sports is live at https://vexp.me"
echo "   Bot: @EAPSportsBot"
echo "   API: https://vexp.me/api/health"
