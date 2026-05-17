#!/usr/bin/env bash
# One-shot VM bootstrap: run once on a fresh Ubuntu 24.04 server as root.
# Installs Docker, uv, and the system firewall. Does NOT clone the repo or
# start the bot — do those steps manually after reviewing the output.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "run as root (sudo -i)" >&2
  exit 1
fi

echo "── apt update + base packages"
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl git ufw

echo "── docker (official repo)"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

echo "── uv (Astral)"
curl -LsSf https://astral.sh/uv/install.sh | sh
# uv lands in /root/.local/bin — make sure future shells find it.
grep -q 'HOME/.local/bin' /root/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> /root/.bashrc

echo "── firewall: SSH only"
ufw allow OpenSSH
ufw --force enable

echo "── timezone → UTC (scheduler handles US/Eastern internally)"
timedatectl set-timezone UTC

echo "── done. next steps:"
echo "  1. git clone <your-repo> /root/trading-bot"
echo "  2. cd /root/trading-bot && cp .env.example .env && edit .env"
echo "  3. ln -s deploy/docker-compose.override.yml docker-compose.override.yml"
echo "  4. docker compose up -d"
echo "  5. source ~/.bashrc && uv sync --all-extras"
echo "  6. uv run alembic upgrade head && uv run python -m scripts.seed_bars"
echo "  7. uv run python -m scripts.preflight"
echo "  8. cp deploy/trading-bot.service /etc/systemd/system/ && systemctl enable --now trading-bot"
echo "  9. crontab deploy/crontab.example"
