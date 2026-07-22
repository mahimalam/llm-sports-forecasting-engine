#!/bin/bash
# EAP-Sports: Heartbeat watchdog — checks services, restarts, alerts via Telegram
# Add to cron: */5 * * * * /home/mahimalam2400/Fifa_project/ops/watchdog.sh
set -uo pipefail

BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
ADMIN_CHAT_ID="${ADMIN_CHAT_ID:-}"  # Set your Telegram user ID
SERVICES=("eap-api" "eap-bot")

alert() {
    local msg="[WARNING] EAP-Sports Watchdog: $1"
    if [ -n "$ADMIN_CHAT_ID" ]; then
        curl -s "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
            -d "chat_id=$ADMIN_CHAT_ID" -d "text=$msg" > /dev/null 2>&1
    fi
    echo "[$(date)] ALERT: $1"
}

for svc in "${SERVICES[@]}"; do
    if ! systemctl is-active --quiet "$svc"; then
        alert "$svc is down. Restarting..."
        systemctl restart "$svc"
        sleep 2
        if systemctl is-active --quiet "$svc"; then
            alert "$svc restarted successfully"
        else
            alert "$svc FAILED to restart - Manual intervention needed!"
        fi
    fi
done

# Health check API endpoint
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null || echo "000")
if [ "$HTTP_CODE" != "200" ]; then
    alert "API health check failed (HTTP $HTTP_CODE). Restarting eap-api..."
    systemctl restart eap-api
fi
