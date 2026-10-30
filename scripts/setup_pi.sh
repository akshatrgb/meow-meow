#!/usr/bin/env bash
# One-time setup on the Raspberry Pi. Run from the project directory:  bash scripts/setup_pi.sh
# It installs packages and the Python environment. It does NOT edit /boot or enable
# the service; those steps are explicit in docs/ASSEMBLY.md so you stay in control.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> System packages (alsa-utils for audio, python3-pil as a fallback for Pillow)"
sudo apt-get update
sudo apt-get install -y alsa-utils python3-venv python3-pil python3-spidev python3-lgpio

echo "==> Python virtual environment (.venv, with system packages so apt-provided wheels work)"
if [ ! -d .venv ]; then
  python3 -m venv --system-site-packages .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-pi.txt

echo "==> Config"
if [ ! -f config/.env ]; then
  cp config/.env.example config/.env
  chmod 600 config/.env
  echo "Created config/.env  -> edit it and add your keys (nano config/.env)"
fi
mkdir -p logs data

echo "==> Checking configuration"
.venv/bin/python -m src.main --check-config >/dev/null && echo "Configuration OK" || \
  echo "Configuration needs attention (run: .venv/bin/python -m src.main --check-config)"

echo "Done. Next: follow docs/ASSEMBLY.md step by step."
