# 🦈 Shark Quant — Institutional BTC/USDT Algorithmic Trading Terminal

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20%2B-green.svg)](https://nodejs.org/)
[![React 18](https://img.shields.io/badge/React-18-cyan.svg)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-teal.svg)](https://fastapi.tiangolo.com/)

An institutional-grade algorithmic trading terminal and real-time execution dashboard for **BTC/USDT Perpetual Futures** on **Shark Exchange**.

Built with a modular, path-agnostic architecture: runs seamlessly on **Localhost (Windows/macOS/Linux)** and is fully **AWS EC2 production-ready**.

---

## 🌟 Key Features

* **Multi-Timeframe Engine**: 15m macro structure alignment with 5m trigger execution. Zero look-ahead bias (strict completed-bar signals).
* **Donchian Breakout Strategy**: 25-period Donchian Channel expansion filtered with ADX(14) $\ge 20.0$ momentum verification.
* **Dynamic Ratcheting Trailing Stop**: 3.0× ATR trailing stop that dynamically locks in floating profit and never widens.
* **50% Partial Scale-Out**: Automatically takes 50% profit off the table at 1:1 R and moves remaining stop to Break-Even.
* **Multi-Level Circuit Breakers**:
  * **Consecutive Loss Cooldown**: Automatically pauses execution for 90 minutes after 3 consecutive losses.
  * **Daily Loss Cap**: Halts bot and flattens positions if daily drawdown breaches 2.5%–3.0%.
  * **Pre-Trade Spread Filter**: Blocks market orders if the top-of-book spread exceeds 0.05%.
  * **Single Concurrent Position**: Strictly prevents averaging down or double exposure.
* **TradingView Lightweight Charts**: Interactive dark-mode candlestick chart with live Donchian bands, volume histogram, entry markers, and dynamic trailing SL lines.
* **Capital Compounding & Lot Sizing Station**:
  * Real-time position sizing for accounts starting as low as **$100**.
  * Auto risk-based compounding mode ($100 → $200 → $500 → $1,000+).
  * Manual lot size override with 1-click steppers (`0.001 BTC` minimum contract size).
* **Instant HTML Telegram Alerts**: Rich real-time trade notifications with entry, SL, TP, P&L, and circuit breaker status.
* **Emergency Kill Switch**: One-click **Flatten All** action to instantly liquidate positions and halt the bot.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────┐
│            React + Vite + Tailwind Dashboard           │
│                 http://localhost:5000                  │
└───────────────────────────┬────────────────────────────┘
                            │ WebSocket / REST
                            ▼
┌────────────────────────────────────────────────────────┐
│           Python FastAPI Strategy Engine (:5001)       │
│   • Donchian Breakout Strategy                         │
│   • Multi-level Risk Circuit Breakers                  │
│   • Telegram Alert Dispatcher                          │
│   • REST & WebSocket State Feed                        │
└───────────────────────────┬────────────────────────────┘
                            │ HTTP Relay
                            ▼
┌────────────────────────────────────────────────────────┐
│             Node.js Exchange Data Bridge (:3001)       │
│   • Official Shark Exchange SDK (`shark-exchange-sdk`) │
│   • Authenticated REST & WebSocket endpoints           │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Localhost)

### 1. Prerequisites
* **Node.js** v20+
* **Python** 3.11+
* PowerShell (Windows) or Bash (Linux/macOS)

### 2. Installation
Clone the repository and install dependencies:

```bash
git clone https://github.com/<your-username>/shark-algo-portal.git
cd shark-algo-portal

# Install Node bridge dependencies
cd shark-algo-portal/backend-node
npm install

# Install Frontend dependencies
cd ../frontend
npm install

# Install Python strategy engine dependencies
cd ../backend-python
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env` inside `shark-algo-portal/`:

```bash
cp shark-algo-portal/.env.example shark-algo-portal/.env
```

Configure your credentials in `shark-algo-portal/.env`:

```ini
SHARK_API_KEY=your_shark_api_key
SHARK_API_SECRET=your_shark_api_secret
SHARK_BASE_URL=https://api.sharkexchange.in

# Safety: start in PAPER mode
DRY_RUN=true
LIVE=false

# Risk parameters
CAPITAL_BASE=100.0
RISK_PER_TRADE_PCT=1.0
LEVERAGE=10

# Telegram alerts
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 4. One-Click Launch (Windows)
Run the automated launcher from the project root:

```powershell
.\start_terminal.ps1
```

Or start each service manually:
* **Node Bridge**: `cd shark-algo-portal/backend-node && node server.mjs`
* **FastAPI Engine**: `cd shark-algo-portal/backend-python && python -m uvicorn api_server:app --port 5001`
* **React Dashboard**: `cd shark-algo-portal/frontend && npm run dev`

Open your browser at **[http://localhost:5000](http://localhost:5000)**.

---

## 🧪 Zero-Risk Canary Connectivity Test

Verify credentials, public market depth, paper execution, and Telegram delivery:

```bash
cd shark-algo-portal
python test_broker_connectivity.py
```

---

## 🛡️ Risk Disclaimer

This software is for algorithmic trading research and execution. Cryptocurrency futures trading involves significant financial risk and leverage. Always test thoroughly in **PAPER mode** before risking live capital.
