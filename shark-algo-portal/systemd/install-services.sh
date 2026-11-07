#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# install-services.sh
# ─────────────────────────────────────────────────────────────────────────────
# Registers and enables all 3 Shark Algo Portal services under systemd on GCP.
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo "=========================================================="
echo "🦈 SHARK ALGO PORTAL — SYSTEMD SERVICE INSTALLER (GCP)"
echo "=========================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTAL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "▶ Installing systemd units from ${SCRIPT_DIR}..."

sudo cp "${SCRIPT_DIR}/shark-node.service" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/shark-python.service" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/shark-frontend.service" /etc/systemd/system/

# Adjust user / paths dynamically if not 'ubuntu'
CURRENT_USER=$(whoami)
if [ "$CURRENT_USER" != "ubuntu" ]; then
    echo "▶ Adapting service user from 'ubuntu' to '${CURRENT_USER}'..."
    sudo sed -i "s/User=ubuntu/User=${CURRENT_USER}/g" /etc/systemd/system/shark-*.service
    sudo sed -i "s|/home/ubuntu/shark-algo-portal|${PORTAL_DIR}|g" /etc/systemd/system/shark-*.service
fi

echo "▶ Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "▶ Enabling services to auto-start on boot..."
sudo systemctl enable shark-node.service
sudo systemctl enable shark-python.service
sudo systemctl enable shark-frontend.service

echo "▶ Starting services..."
sudo systemctl restart shark-node.service
sudo systemctl restart shark-python.service
sudo systemctl restart shark-frontend.service

echo ""
echo "=========================================================="
echo "✅ ALL SERVICES INSTALLED & RUNNING!"
echo "=========================================================="
echo ""
echo "Commands to manage:"
echo "  Check status : sudo systemctl status shark-python.service"
echo "  View logs    : sudo journalctl -u shark-python.service -f"
echo "  Restart all  : sudo systemctl restart shark-node shark-python shark-frontend"
echo "  Stop all     : sudo systemctl stop shark-node shark-python shark-frontend"
echo ""
