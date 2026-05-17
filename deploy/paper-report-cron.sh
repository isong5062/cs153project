#!/usr/bin/env bash
# Weekly paper-trading report. Writes a timestamped JSON to
# /var/log/trading-bot/reports/ and a human-readable log alongside it.

set -euo pipefail
cd /root/trading-bot
mkdir -p /var/log/trading-bot/reports
STAMP=$(date +%Y%m%d)
/root/.local/bin/uv run python -m scripts.paper_report \
  --days 7 \
  --json-out "/var/log/trading-bot/reports/week-${STAMP}.json" \
  >> "/var/log/trading-bot/paper-report-${STAMP}.log" 2>&1
