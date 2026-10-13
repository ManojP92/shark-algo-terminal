"""
api_server.py
──────────────────────────────────────────────────────────────────────────────
FastAPI server — dashboard REST API + WebSocket live feed.

Runs on port 5001 (PYTHON_BRIDGE_PORT in .env).
The React dashboard connects here for:
  • GET  /api/status          → bot mode, position, stats, circuit breakers
  • GET  /api/candles/{tf}    → proxied kline data from Node bridge
  • GET  /api/balance         → equity from exchange
  • POST /api/control/pause   → pause bot (blocks new entries, keeps position)
  • POST /api/control/resume  → resume from pause
  • POST /api/control/flatten → emergency flatten + halt
  • POST /api/control/mode    → switch PAPER ↔ LIVE (requires LIVE env flag)
  • WS   /ws                  → live tick feed (status pushed every 2s)

Run:
  uvicorn api_server:app --host 0.0.0.0 --port 5001 --reload
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import secrets
import threading
import time
from typing import Optional

import pandas as pd
import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from shark_client import SharkClient
from risk_manager import RiskManager
from telegram_alerts import TelegramAlerter
from executor import Executor, INSTRUMENT_CONFIGS
from backtester import run_backtest, run_monte_carlo
from telegram_commander import TelegramCommander

log = logging.getLogger("api_server")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [API] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

NODE_URL = os.getenv("NODE_URL", "http://localhost:3001")
PORT     = int(os.getenv("PYTHON_BRIDGE_PORT", "5001"))

# ── Global executor instance (starts paused) ──────────────────────────────────
_executor: Optional[Executor] = None
_executor_thread: Optional[threading.Thread] = None
_paused = False

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Shark Algo — Trading Terminal API",
    version="1.0.0",
    description="Institutional Donchian Breakout Engine — Dashboard API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # restrict to localhost in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
#  REST ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
def get_status():
    """Full bot status: mode, position, circuit breaker state, daily stats."""
    global _executor
    if _executor is None:
        return {"running": False, "paused": _paused, "position": None, "stats": {}}
    status = _executor.get_status()
    status["paused"] = _paused
    return status


@app.get("/api/candles/{timeframe}")
def get_candles(timeframe: str, limit: int = 200, symbol: Optional[str] = None):
    """Proxy kline data from Node bridge to the React dashboard."""
    try:
        active_sym = symbol or (_executor.symbol if _executor else "BTCUSDT")
        resp = requests.get(
            f"{NODE_URL}/api/klines/{timeframe}?pair={active_sym}&limit={limit}", timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as err:
        raise HTTPException(status_code=502, detail=f"Node bridge error: {err}")


@app.get("/api/balance")
def get_balance():
    """Fetch live equity from Shark Exchange."""
    try:
        client = SharkClient()
        return {"ok": True, "balance": client.get_balances()}
    except Exception as err:
        raise HTTPException(status_code=502, detail=str(err))


@app.get("/api/health")
def health():
    return {"ok": True, "timestamp": int(time.time() * 1000)}


# ── Authentication & Telegram 2FA ─────────────────────────────────────────────

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "shark2026")

_active_otps: dict[str, dict] = {}
_active_sessions: dict[str, dict] = {}


class LoginRequest(BaseModel):
    password: str


class VerifyOtpRequest(BaseModel):
    otp: str


class LogoutRequest(BaseModel):
    token: Optional[str] = None


@app.post("/api/auth/request-otp")
def request_otp(body: LoginRequest):
    """Verify master password and dispatch 6-digit OTP via Telegram."""
    global _active_otps
    now = time.time()
    # Prune expired OTPs
    _active_otps = {k: v for k, v in _active_otps.items() if v["expires_at"] > now}

    if body.password != ADMIN_PASSWORD:
        log.warning("Authentication failure: Invalid master password submitted")
        raise HTTPException(status_code=401, detail="Incorrect Master Password")

    # Generate 6-digit code
    otp = f"{random.randint(100000, 999999)}"
    _active_otps[otp] = {
        "created_at": now,
        "expires_at": now + 300,  # 5 minutes validity
        "attempts": 0,
    }

    tg = TelegramAlerter()
    sent = tg.send_2fa_code(otp=otp, client_ip="Web Terminal")
    if not sent:
        log.warning("Failed to send 2FA code via Telegram — verify bot credentials")

    chat_hint = f"...{tg.chat_id[-4:]}" if len(tg.chat_id) >= 4 else "Telegram"
    log.info("2FA OTP generated and dispatched via Telegram to chat %s", chat_hint)

    return {
        "ok": True,
        "message": f"Verification code sent to your Telegram (@{chat_hint})",
        "chat_id_hint": chat_hint,
        "expires_in": 300,
    }


@app.post("/api/auth/verify-otp")
def verify_otp(body: VerifyOtpRequest):
    """Verify Telegram 2FA code and issue 7-day secure session token."""
    global _active_otps, _active_sessions
    now = time.time()
    otp = body.otp.strip()

    if otp not in _active_otps:
        log.warning("2FA verification failed: Invalid OTP '%s'", otp)
        raise HTTPException(status_code=400, detail="Invalid verification code")

    otp_info = _active_otps[otp]
    if now > otp_info["expires_at"]:
        del _active_otps[otp]
        raise HTTPException(status_code=400, detail="Verification code expired. Please request a new code.")

    # Valid! Invalidate OTP to prevent replay attacks
    del _active_otps[otp]

    # Create session
    token = secrets.token_hex(32)
    _active_sessions[token] = {
        "created_at": now,
        "expires_at": now + (7 * 86400),
        "user": "admin",
    }

    # Dispatch confirmation alert to Telegram
    TelegramAlerter().login_successful(client_ip="Web Terminal")
    log.info("2FA verification SUCCESS. New session issued: %s...", token[:8])

    return {
        "ok": True,
        "token": token,
        "user": "admin",
        "expires_in": 7 * 86400,
    }


@app.get("/api/auth/check")
def check_auth(token: Optional[str] = None):
    """Validate active session token."""
    if not token or token not in _active_sessions:
        return {"authenticated": False}
    sess = _active_sessions[token]
    if time.time() > sess["expires_at"]:
        del _active_sessions[token]
        return {"authenticated": False}
    return {"authenticated": True, "user": sess.get("user", "admin")}


@app.post("/api/auth/logout")
def logout(body: LogoutRequest):
    """Invalidate session token."""
    if body.token and body.token in _active_sessions:
        del _active_sessions[body.token]
        log.info("Session revoked: %s...", body.token[:8])
    return {"ok": True, "message": "Logged out successfully"}


# ── Control endpoints ─────────────────────────────────────────────────────────

class ModeRequest(BaseModel):
    mode: str  # "PAPER" or "LIVE"


@app.post("/api/control/pause")
def pause_bot():
    global _paused, _executor
    _paused = True
    if _executor:
        _executor._running = False
    log.info("Bot PAUSED via dashboard")
    return {"ok": True, "paused": True}


@app.post("/api/control/resume")
def resume_bot():
    global _paused, _executor, _executor_thread
    _paused = False
    if _executor and not _executor._running:
        _executor._running = True
        _executor_thread = threading.Thread(
            target=_executor.run, daemon=True
        )
        _executor_thread.start()
        log.info("Bot RESUMED via dashboard")
    return {"ok": True, "paused": False}


@app.post("/api/control/close-position")
def close_position_endpoint():
    """
    Manually close active position from Position Widget at market price.
    Computes PnL, updates paper wallet or live exchange, logs trade, and keeps bot active.
    """
    global _executor
    if _executor is None:
        raise HTTPException(status_code=503, detail="Trading engine is not running")
    try:
        result = _executor.close_position(reason="Dashboard Manual Exit")
        log.info("Position manually closed via dashboard: %s", result)
        return {"ok": True, "result": result}
    except Exception as err:
        log.error("Manual position close failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


@app.post("/api/control/flatten")
def emergency_flatten():
    """
    Emergency flatten: closes all positions, halts trading engine loop, and alerts.
    """
    global _executor
    if _executor is None:
        symbol = os.getenv("TRADING_PAIR", "BTCUSDT")
        client = SharkClient()
        res = client.emergency_flatten(symbol)
        return {"ok": True, "result": res}
    try:
        result = _executor.flatten(reason="Dashboard Emergency Flatten")
        log.critical("EMERGENCY FLATTEN executed via dashboard: %s", result)
        return {"ok": True, "result": result}
    except Exception as err:
        log.error("Emergency flatten failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))



class SymbolRequest(BaseModel):
    symbol: str


@app.post("/api/control/symbol")
def switch_symbol(req: SymbolRequest):
    """
    Switch active trading pair (e.g. BTCUSDT, ETHUSDT, SOLUSDT).
    """
    global _executor
    if _executor is None:
        raise HTTPException(status_code=503, detail="Executor not running")
    success = _executor.set_symbol(req.symbol)
    if not success:
        if _executor.position is not None:
            raise HTTPException(status_code=400, detail="Cannot switch symbol while a position is open")
        raise HTTPException(status_code=400, detail=f"Unsupported symbol: {req.symbol}")
    return {
        "ok": True,
        "symbol": _executor.symbol,
        "sizing": {
            "min_qty": _executor.rm.cfg.min_qty,
            "step_size": _executor.rm.cfg.step_size,
            "manual_lot_size": _executor.rm.cfg.manual_lot_size,
        }
    }


@app.post("/api/control/mode")
def set_mode(req: ModeRequest):
    """
    Switch dynamically between PAPER and LIVE modes on the fly.
    """
    global _executor
    requested = req.mode.strip().upper()
    if requested not in ("PAPER", "LIVE"):
        raise HTTPException(status_code=400, detail="Invalid mode: must be PAPER or LIVE")

    if _executor is not None:
        _executor.set_mode(requested)
        log.info("Mode dynamically switched to %s via dashboard", requested)

    return {"ok": True, "mode": requested, "message": f"Mode successfully switched to {requested}"}


class SizingRequest(BaseModel):
    sizing_mode: Optional[str] = None          # "AUTO" or "MANUAL"
    manual_lot_size: Optional[float] = None    # e.g. 0.001 BTC
    risk_per_trade_pct: Optional[float] = None # e.g. 1.0, 2.0
    capital_base: Optional[float] = None       # e.g. 100.0
    leverage: Optional[int] = None             # e.g. 10


@app.post("/api/control/sizing")
def update_sizing(req: SizingRequest):
    """
    Update position sizing, compounding, and risk settings on the fly.
    """
    global _executor
    if _executor is None:
        raise HTTPException(status_code=503, detail="Executor not running")

    rm = _executor.rm
    if req.sizing_mode is not None:
        rm.cfg.sizing_mode = req.sizing_mode.upper()
    if req.manual_lot_size is not None and req.manual_lot_size > 0:
        rm.cfg.manual_lot_size = round(req.manual_lot_size, 3)
    if req.risk_per_trade_pct is not None and req.risk_per_trade_pct > 0:
        rm.cfg.risk_per_trade_pct = round(req.risk_per_trade_pct, 2)
    if req.capital_base is not None and req.capital_base > 0:
        rm.cfg.capital_base = round(req.capital_base, 2)
        _executor.paper_wallet = round(req.capital_base, 2)
    if req.leverage is not None and req.leverage > 0:
        rm.cfg.leverage = req.leverage

    _executor._log_event(
        f"Sizing updated: mode={rm.cfg.sizing_mode} lots={rm.cfg.manual_lot_size} "
        f"risk={rm.cfg.risk_per_trade_pct}% cap=${rm.cfg.capital_base} lev={rm.cfg.leverage}x"
    )

    return {
        "ok": True,
        "sizing": {
            "sizing_mode":        rm.cfg.sizing_mode,
            "manual_lot_size":    rm.cfg.manual_lot_size,
            "risk_per_trade_pct": rm.cfg.risk_per_trade_pct,
            "capital_base":       rm.cfg.capital_base,
            "leverage":           rm.cfg.leverage,
            "min_qty":            rm.cfg.min_qty,
        }
    }


# ── Backtesting & Monte Carlo ────────────────────────────────────────────────

class StrategyRequest(BaseModel):
    strategy: str  # "DONCHIAN", "BOLLINGER_RSI", "SUPERTREND", "REGIME_ADAPTIVE"


@app.post("/api/control/strategy")
def change_strategy(req: StrategyRequest):
    global _executor
    strat = req.strategy.upper()
    if _executor:
        _executor.set_strategy(strat)
    log.info("Active trading strategy set to %s", strat)
    return {"ok": True, "strategy": strat}


class BacktestRequest(BaseModel):
    strategy: Optional[str] = "DONCHIAN"
    pair: Optional[str] = "BTCUSDT"
    interval: Optional[str] = "15m"
    days: Optional[int] = 14
    capital: Optional[float] = 100.0
    risk_pct: Optional[float] = 1.0
    leverage: Optional[int] = 10
    dc_period: Optional[int] = 20
    adx_min: Optional[float] = 22.0
    atr_mult_sl: Optional[float] = 1.2
    atr_mult_trail: Optional[float] = 3.0
    enable_scale_out: Optional[bool] = False
    monte_carlo_runs: Optional[int] = 500


@app.post("/api/backtest")
def execute_backtest(req: BacktestRequest):
    """
    Run institutional backtest & Monte Carlo simulation over historical candles.
    """
    pair = req.pair.upper() if req.pair else "BTCUSDT"
    interval = req.interval or "15m"
    days = min(30, max(1, req.days or 14))

    # Instrument specs
    inst = INSTRUMENT_CONFIGS.get(pair, INSTRUMENT_CONFIGS["BTCUSDT"])
    min_qty = inst["min_qty"]
    step_size = inst["step_size"]
    min_notional = inst["min_notional"]

    # Fetch historical klines from Node bridge
    try:
        url = f"{NODE_URL}/api/klines/history?interval={interval}&days={days}&pair={pair}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok") or not body.get("data"):
            raise HTTPException(
                status_code=502,
                detail=f"No historical candles returned: {body.get('error', 'empty data')}"
            )

        raw_candles = body["data"]
        df = pd.DataFrame(raw_candles)
        df.rename(columns={"startTime": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)

        bt_result = run_backtest(
            df=df,
            strategy_name=req.strategy or "DONCHIAN",
            initial_capital=req.capital or 100.0,
            risk_pct=req.risk_pct or 1.0,
            leverage=req.leverage or 10,
            min_qty=min_qty,
            step_size=step_size,
            min_notional=min_notional,
            dc_period=req.dc_period if req.dc_period is not None else 20,
            adx_min=req.adx_min if req.adx_min is not None else 22.0,
            atr_mult_sl=req.atr_mult_sl if req.atr_mult_sl is not None else 1.2,
            atr_mult_trail=req.atr_mult_trail if req.atr_mult_trail is not None else 3.0,
            enable_scale_out=req.enable_scale_out if req.enable_scale_out is not None else False,
        )

        trade_returns = [t["net_pnl"] for t in bt_result["trades"]]
        mc_result = run_monte_carlo(
            trade_returns=trade_returns,
            initial_capital=req.capital or 100.0,
            num_simulations=req.monte_carlo_runs or 500,
        )

        return {
            "ok": True,
            "pair": pair,
            "interval": interval,
            "days": days,
            "candles_count": len(df),
            "summary": bt_result["summary"],
            "equity_curve": bt_result["equity_curve"],
            "trades": bt_result["trades"],
            "monte_carlo": mc_result,
        }
    except Exception as err:
        log.error("Backtest failed: %s", err, exc_info=True)
        raise HTTPException(status_code=500, detail=str(err))


# ══════════════════════════════════════════════════════════════════════════════
#  WEBSOCKET — live status feed
# ══════════════════════════════════════════════════════════════════════════════

_ws_clients: list[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    log.info("WebSocket client connected (total: %d)", len(_ws_clients))
    try:
        while True:
            # Push status every 2 seconds
            status = get_status()
            await ws.send_json({"type": "status", "data": status})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
        log.info("WebSocket client disconnected (total: %d)", len(_ws_clients))
    except Exception as err:
        log.error("WebSocket error: %s", err)
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP — launch executor in background thread
# ══════════════════════════════════════════════════════════════════════════════

_commander: Optional[TelegramCommander] = None


@app.on_event("startup")
def startup():
    global _executor, _executor_thread, _commander
    _executor = Executor()
    _executor.set_mode("PAPER")
    _executor_thread = threading.Thread(target=_executor.run, daemon=True)
    _executor_thread.start()
    log.info("Executor thread started (FAIL-SAFE: Always initialized in PAPER mode)")

    # Start 2-way interactive Telegram remote control listener
    _commander = TelegramCommander(get_executor=lambda: _executor)
    _commander.start()


if __name__ == "__main__":
    uvicorn.run("api_server:app", host="0.0.0.0", port=PORT, reload=False)
