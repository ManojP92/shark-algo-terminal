#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup-gcp-vm.sh
# ─────────────────────────────────────────────────────────────────────────────
# Automated 1-Click Bootstrap for Google Cloud VM (Ubuntu / Debian)
# Sets up Python, Node.js, PM2, dependencies, builds UI, and launches terminal.
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo "=========================================================="
echo "🦈 SHARK ALGO TERMINAL — GOOGLE CLOUD VM DEPLOYMENT SETUP"
echo "=========================================================="

# 1. Update OS & install prerequisites
echo "▶ 1/5: Updating system packages and installing build tools..."
sudo apt-get update -y
sudo apt-get install -y git curl wget build-essential python3 python3-pip python3-venv

# 2. Install Node.js (v20 LTS) & PM2
echo "▶ 2/5: Installing Node.js LTS and PM2 process supervisor..."
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

sudo npm install -g pm2

# 3. Backend Node dependencies
echo "▶ 3/5: Installing Node bridge dependencies..."
cd backend-node
npm install
cd ..

# 4. Backend Python dependencies
echo "▶ 4/5: Installing Python quantitative dependencies..."
cd backend-python
pip3 install --break-system-packages -r requirements.txt || pip3 install -r requirements.txt
cd ..

# 5. Frontend Build
echo "▶ 5/5: Building React Terminal production bundle..."
cd frontend
npm install
npm run build
cd ..

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️ .env file not found. Copying .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
    fi
    echo "❗ IMPORTANT: Edit .env (nano .env) with your SHARK API keys and TELEGRAM credentials before starting!"
else
    echo "✅ .env file detected."
fi

echo "=========================================================="
echo "🚀 SETUP COMPLETE!"
echo ""
echo "To launch 24/7 in background with PM2:"
echo "   pm2 start ecosystem.config.cjs"
echo "   pm2 save"
echo "   pm2 startup"
echo ""
echo "Access your terminal at: http://<YOUR_VM_EXTERNAL_IP>:5000"
echo "=========================================================="
