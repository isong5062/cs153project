#!/usr/bin/env bash
# Nightly reconciliation. Logs to /var/log/trading-bot/. Exits non-zero on
# drift so cron's MAILTO (or a systemd timer's OnFailure hook) can notify.

set -euo pipefail
cd /root/trading-bot
mkdir -p /var/log/trading-bot
LOG="/var/log/trading-bot/reconcile-$(date +%Y%m%d).log"
echo "── reconcile $(date -u +%FT%TZ)" >> "$LOG"
/root/.local/bin/uv run python -m scripts.reconcile --strict >> "$LOG" 2>&1
