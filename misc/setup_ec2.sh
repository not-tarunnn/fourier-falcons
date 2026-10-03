#!/usr/bin/env bash
# One-shot setup for a fresh AWS EC2 instance (Ubuntu or Amazon Linux).
# Usage:  bash misc/setup_ec2.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo ">> Installing Python..."
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip
elif command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3 python3-pip
fi

echo ">> Creating virtualenv + installing requirements..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo ">> Created .env - EDIT IT with your Roostoo API key/secret before starting."
fi

echo ">> Installing systemd service..."
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__USER__|$(whoami)|g" misc/quantbot.service \
  | sudo tee /etc/systemd/system/quantbot.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable quantbot

cat <<MSG

Done. Next steps:
  1. nano .env                         # add ROOSTOO_API_KEY / ROOSTOO_API_SECRET
  2. ./venv/bin/python main.py --dry-run --once   # optional smoke test
  3. sudo systemctl start quantbot     # start trading (auto-restarts, survives reboot)
  4. journalctl -u quantbot -f         # watch live logs
MSG
