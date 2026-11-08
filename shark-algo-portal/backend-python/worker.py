"""
worker.py
──────────────────────────────────────────────────────────────────────────────
TenantWorker — Autonomous, Isolated Execution Pod for a Single Tenant.

Key Capabilities:
  1. Isolated Risk Sandboxing (independent capital, sizing, circuit breakers).
  2. JIT Exchange Credential Decryption (AES-256 decrypted in RAM for LIVE orders,
     then immediately discarded).
  3. Seamless PAPER / LIVE mode switching.
  4. Real-time Trailing Stop & Ratchet evaluation.
  5. Multi-Tenant Ledger & State Persistence (tenant_trades & tenant_state).
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import tenant_db
from events import SignalEvent
from risk_manager import RiskConfig, RiskManager
from shark_client import SharkClient
from strategy.donchian_breakout import DonchianBreakoutStrategy, TrailingState

log = logging.getLogger("tenant_worker")


@dataclass
class OpenPosition:
    side: str  # "LONG" | "SHORT"
    symbol: str
    qty: float
    entry: float
    sl: float  # current (potentially ratcheted) SL
    trail_state: TrailingState
    order_id: str = ""
    scaled_out: bool = False
    open_time: str = ""

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "symbol": self.symbol,
            "qty": self.qty,
            "entry": self.entry,
            "sl": self.sl,
            "trail_sl": self.trail_state.trail_sl,
            "best_price": self.trail_state.best_price,
            "atr_mult": self.trail_state.atr_mult,
            "order_id": self.order_id,
            "scaled_out": self.scaled_out,
            "open_time": self.open_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OpenPosition:
        trail_state = TrailingState(
            side=data.get("side", "LONG"),
            entry=float(data.get("entry", 0.0)),
            best_price=float(data.get("best_price", data.get("entry", 0.0))),
            trail_sl=float(data.get("trail_sl", data.get("sl", 0.0))),
            atr_mult=float(data.get("atr_mult", 3.0)),
        )
        return cls(
            side=data.get("side", "LONG"),
            symbol=data.get("symbol", "BTCUSDT"),
            qty=float(data.get("qty", 0.001)),
            entry=float(data.get("entry", 0.0)),
            sl=float(data.get("sl", 0.0)),
            trail_state=trail_state,
            order_id=str(data.get("order_id", "")),
            scaled_out=bool(data.get("scaled_out", False)),
            open_time=str(data.get("open_time", "")),
        )


class TenantWorker:
    """
    Isolated execution pod for a single registered tenant.
    Never poll exchange data; responds strictly to dispatched events and ticks.
    """

    def __init__(
        self,
        tenant_id: str,
        tenant_data: Optional[dict] = None,
        db_path: Optional[str] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.db_path = db_path

        # If tenant_data not supplied, load from database
        data = tenant_data or tenant_db.get_tenant_by_id(tenant_id, db_path=self.db_path)
        if not data:
            raise ValueError(f"Tenant '{tenant_id}' not found in database.")

        self.email = str(data.get("email", ""))
        self.role = str(data.get("role", "CLIENT"))
        self.mode = str(data.get("mode", "PAPER")).upper()
        self.is_active = bool(data.get("is_active", 1))

        # Risk configuration per tenant
        capital_base = float(data.get("capital_base", 100.0))
        risk_pct = float(data.get("risk_per_trade_pct", 1.0))
        daily_loss_limit = float(data.get("daily_loss_limit_pct", 3.0))
        max_losses = int(data.get("max_consecutive_losses", 3))
        sizing_mode = str(data.get("sizing_mode", "AUTO")).upper()
        manual_lot = float(data.get("manual_lot_size", 0.001))
        leverage = int(data.get("leverage", 10))

        cfg = RiskConfig(
            capital_base=capital_base,
            risk_per_trade_pct=risk_pct,
            daily_loss_cap_pct=daily_loss_limit,
            max_consecutive_losses=max_losses,
            sizing_mode=sizing_mode,
            manual_lot_size=manual_lot,
            leverage=leverage,
        )
        self.rm = RiskManager(config=cfg)

        self.paper_wallet = capital_base
        self.position: Optional[OpenPosition] = None
        self.trade_history: list[dict] = []
        self.recent_logs: list[str] = []
        self._stats_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._stats = {"trades": 0, "wins": 0, "daily_pnl": 0.0}

        # Restore runtime state & ledger from DB
        self._restore_state()

    def _restore_state(self) -> None:
        """Restore runtime state, circuit breakers, open positions, and trades from DB."""
        state = tenant_db.get_tenant_state(self.tenant_id, db_path=self.db_path)
        if state:
            self.paper_wallet = float(state.get("paper_wallet", self.rm.cfg.capital_base))
            self.rm.state.day_start_equity = float(state.get("day_start_equity", self.paper_wallet))
            self.rm.state.daily_pnl = float(state.get("daily_pnl", 0.0))
            self.rm.state.consecutive_losses = int(state.get("consecutive_losses", 0))
            self.rm.state.cooldown_until_ts = float(state.get("cooldown_until", 0.0))
            self.rm.state.halted = bool(state.get("halted", 0))

            pos_data = state.get("active_position")
            if pos_data and isinstance(pos_data, dict):
                try:
                    self.position = OpenPosition.from_dict(pos_data)
                    self.rm.position_opened()
                except Exception as err:
                    log.warning("Failed to restore position for tenant %s: %s", self.tenant_id, err)

        # Restore recent trade ledger
        trades = tenant_db.get_tenant_trades(self.tenant_id, limit=50, db_path=self.db_path)
        self.trade_history = trades

    def _save_state(self) -> None:
        """Persist current runtime state to tenant_state table."""
        pos_dict = self.position.to_dict() if self.position else None
        state_dict = {
            "paper_wallet": round(self.paper_wallet, 2),
            "day_start_equity": round(self.rm.state.day_start_equity, 2),
            "daily_pnl": round(self.rm.state.daily_pnl, 2),
            "consecutive_losses": self.rm.state.consecutive_losses,
            "cooldown_until": self.rm.state.cooldown_until_ts,
            "halted": 1 if self.rm.state.halted else 0,
            "active_position": pos_dict,
        }
        tenant_db.set_tenant_state(self.tenant_id, state_dict, db_path=self.db_path)

    def _log_event(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.recent_logs.insert(0, f"[{ts}] {msg}")
        if len(self.recent_logs) > 50:
            self.recent_logs.pop()

    def get_equity(self) -> float:
        """Fetch current equity. Uses paper_wallet in PAPER mode or live exchange balance in LIVE mode."""
        if self.mode == "PAPER":
            return round(self.paper_wallet, 2)

        # LIVE Mode: Decrypt exchange API keys Just-In-Time (JIT)
        try:
            api_key, api_secret = tenant_db.get_tenant_keys(self.tenant_id, db_path=self.db_path)
            if not api_key or not api_secret:
                return round(self.rm.cfg.capital_base, 2)

            client = SharkClient(api_key=api_key, api_secret=api_secret, live=True, dry_run=False)
            bal = client.get_balances()
            if isinstance(bal, list):
                for b in bal:
                    if b.get("asset", "").upper() in ("USDT", "USD"):
                        return float(b.get("balance", b.get("availableBalance", self.rm.cfg.capital_base)))
            if isinstance(bal, dict):
                data = bal.get("data", bal)
                if isinstance(data, list):
                    for b in data:
                        if b.get("asset", "").upper() in ("USDT", "USD"):
                            return float(b.get("balance", b.get("availableBalance", self.rm.cfg.capital_base)))
            return round(self.rm.cfg.capital_base, 2)
        except Exception as err:
            log.warning("Tenant %s live balance check failed: %s", self.tenant_id, err)
            return round(self.rm.cfg.capital_base, 2)

    def _ensure_day_reset(self, equity: float) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._stats_date != today:
            self._stats_date = today
            self._stats["daily_pnl"] = 0.0
            self._stats["trades"] = 0
            self._stats["wins"] = 0
        self.rm._ensure_day_reset(equity)

    # ── Signal Execution (Fan-Out from Master) ──────────────────────────────────

    def execute_signal(self, signal: SignalEvent) -> dict[str, Any]:
        """
        Process a central trading signal for this specific tenant pod.
        Evaluates tenant's isolated risk budget, calculates proportional lot size,
        and executes via paper wallet or JIT-decrypted exchange client.
        """
        if not self.is_active:
            return {"status": "INACTIVE", "tenant_id": self.tenant_id, "reason": "Tenant is paused"}

        if self.position is not None:
            return {"status": "POSITION_OPEN", "tenant_id": self.tenant_id, "reason": "Position already active"}

        equity = self.get_equity()
        self._ensure_day_reset(equity)

        allowed, reason = self.rm.can_trade(equity)
        if not allowed:
            self._log_event(f"Signal {signal.action} rejected by risk sandbox: {reason}")
            return {"status": "BLOCKED_BY_RISK", "tenant_id": self.tenant_id, "reason": reason}

        # Size lot size according to tenant profile (AUTO compounding or MANUAL fixed lots)
        qty = self.rm.position_size(equity, signal.entry, signal.sl)
        if qty <= 0:
            self._log_event(f"Signal {signal.action} skipped: calculated lot size is 0 (Equity=${equity:.2f})")
            return {"status": "ZERO_QTY", "tenant_id": self.tenant_id, "reason": "Calculated lot size is 0"}

        order_id = ""
        if self.mode == "LIVE":
            api_key, api_secret = tenant_db.get_tenant_keys(self.tenant_id, db_path=self.db_path)
            if not api_key or not api_secret:
                self._log_event(f"LIVE trade blocked: No valid API keys found in vault")
                return {"status": "NO_KEYS", "tenant_id": self.tenant_id, "reason": "Missing exchange API keys in vault"}

            try:
                client = SharkClient(api_key=api_key, api_secret=api_secret, live=True, dry_run=False)
                resp = client.place_order(signal.symbol, signal.action, "MARKET", qty)
                order_id = str(resp.get("orderId", f"LIVE-{secrets.token_hex(4)}"))
            except Exception as err:
                log.error("Tenant %s live order placement error: %s", self.tenant_id, err)
                self._log_event(f"Order error: {err}")
                return {"status": "EXECUTION_ERROR", "tenant_id": self.tenant_id, "reason": str(err)}
        else:
            order_id = f"PAPER-{secrets.token_hex(4)}"

        # Instantiate TrailingState
        trail_state = TrailingState(
            side=signal.action,
            entry=signal.entry,
            best_price=signal.entry,
            trail_sl=signal.trail_sl,
        )

        now_utc = datetime.now(timezone.utc)
        self.position = OpenPosition(
            side=signal.action,
            symbol=signal.symbol,
            qty=qty,
            entry=signal.entry,
            sl=signal.sl,
            trail_state=trail_state,
            order_id=order_id,
            open_time=now_utc.strftime("%H:%M:%S"),
        )

        self.rm.position_opened()
        self._log_event(f"Opened {signal.action} {qty} {signal.symbol} @ ${signal.entry:.2f} (SL: ${signal.sl:.2f})")
        self._save_state()

        return {
            "status": "FILLED",
            "tenant_id": self.tenant_id,
            "symbol": signal.symbol,
            "action": signal.action,
            "qty": qty,
            "entry": signal.entry,
            "sl": signal.sl,
            "trail_sl": signal.trail_sl,
            "order_id": order_id,
            "mode": self.mode,
        }

    # ── Trailing Stop & Exit Evaluation ─────────────────────────────────────────

    def update_position(
        self,
        mark_price: float,
        atr: float,
        strategy: DonchianBreakoutStrategy,
    ) -> Optional[dict[str, Any]]:
        """
        Evaluate trailing stop ratchet or exit hit against mark price and ATR.
        Returns closed trade dictionary if exited, or None if position remains active.
        """
        if self.position is None:
            return None

        pos = self.position

        # Ratchet trailing stop in favorable direction
        updated_state = strategy.update_trailing_stop(pos.trail_state, mark_price, atr)
        pos.trail_state = updated_state
        pos.sl = updated_state.trail_sl

        # Check exit triggers
        exit_reason = None
        if pos.side == "LONG" and mark_price <= pos.sl:
            exit_reason = f"Trailing stop hit ({mark_price:.2f} <= {pos.sl:.2f})"
        elif pos.side == "SHORT" and mark_price >= pos.sl:
            exit_reason = f"Trailing stop hit ({mark_price:.2f} >= {pos.sl:.2f})"

        if exit_reason:
            return self._close_position(pos, mark_price, exit_reason)

        # Position still open; persist updated trailing stop level
        self._save_state()
        return None

    def close_position(self, reason: str = "Manual Close", mark_price: float = 0.0) -> dict[str, Any]:
        """Manually or emergently close this tenant's open position."""
        if self.position is None:
            return {"ok": True, "message": "No open position for tenant", "tenant_id": self.tenant_id}

        exit_price = mark_price if mark_price > 0 else self.position.entry
        return self._close_position(self.position, exit_price, reason)

    def _close_position(self, pos: OpenPosition, exit_price: float, reason: str) -> dict[str, Any]:
        """Execute position exit, compute P&L, update risk state, and record in tenant ledger."""
        if pos.side == "LONG":
            pnl = (exit_price - pos.entry) * pos.qty
            raw_ret = (exit_price - pos.entry) / pos.entry
        else:
            pnl = (pos.entry - exit_price) * pos.qty
            raw_ret = (pos.entry - exit_price) / pos.entry

        pnl_pct = raw_ret * 100 * self.rm.cfg.leverage

        if self.mode == "LIVE":
            try:
                api_key, api_secret = tenant_db.get_tenant_keys(self.tenant_id, db_path=self.db_path)
                if api_key and api_secret:
                    client = SharkClient(api_key=api_key, api_secret=api_secret, live=True, dry_run=False)
                    close_side = "SELL" if pos.side == "LONG" else "BUY"
                    client.place_order(pos.symbol, close_side, "MARKET", pos.qty, reduce_only=True)
            except Exception as err:
                log.error("Tenant %s live exit order error: %s", self.tenant_id, err)
        else:
            self.paper_wallet = max(1.0, round(self.paper_wallet + pnl, 2))

        # Update Risk Sandbox
        self.rm.record_trade(pnl)
        self.rm.position_closed()

        now_utc = datetime.now(timezone.utc)
        today = now_utc.strftime("%Y-%m-%d")
        self._ensure_day_reset(self.get_equity())
        self._stats["trades"] += 1
        if pnl > 0:
            self._stats["wins"] += 1
        self._stats["daily_pnl"] += pnl

        trade_record = {
            "id": f"TR-{int(time.time()*1000)}-{secrets.token_hex(2)}",
            "time": now_utc.strftime("%H:%M:%S"),
            "date": today,
            "side": pos.side,
            "symbol": pos.symbol,
            "qty": pos.qty,
            "entry": pos.entry,
            "exit": exit_price,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "reason": reason,
            "mode": self.mode,
            "order_id": pos.order_id,
        }

        self.trade_history.insert(0, trade_record)
        if len(self.trade_history) > 50:
            self.trade_history.pop()

        self._log_event(f"Closed {pos.side} {pos.qty} @ ${exit_price:.2f} | P&L: ${pnl:+.2f} ({reason})")

        # Record in partitioned SQLite ledger
        tenant_db.record_tenant_trade(self.tenant_id, trade_record, mode=self.mode, db_path=self.db_path)

        self.position = None
        self._save_state()

        return {
            "ok": True,
            "tenant_id": self.tenant_id,
            "trade": trade_record,
        }

    # ── Status Query ────────────────────────────────────────────────────────────

    def get_status(self, mark_price: float = 0.0) -> dict[str, Any]:
        """Return tenant status payload for dashboard & API."""
        equity = self.get_equity()
        self._ensure_day_reset(equity)

        unrealized_pnl = 0.0
        pnl_pct = 0.0
        liq_price = 0.0

        if self.position and mark_price > 0:
            pos = self.position
            if pos.side == "LONG":
                unrealized_pnl = (mark_price - pos.entry) * pos.qty
                pnl_pct = ((mark_price - pos.entry) / pos.entry) * 100 * self.rm.cfg.leverage
                liq_price = max(0.0, pos.entry * 0.90)
            else:
                unrealized_pnl = (pos.entry - mark_price) * pos.qty
                pnl_pct = ((pos.entry - mark_price) / pos.entry) * 100 * self.rm.cfg.leverage
                liq_price = pos.entry * 1.10

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_trades = [t for t in self.trade_history if t.get("date") == today_str]
        daily_realized_pnl = sum(t.get("pnl", 0.0) for t in today_trades) if today_trades else float(self._stats.get("daily_pnl", 0.0))
        total_daily_pnl = round(daily_realized_pnl + unrealized_pnl, 2)

        trades_count = len(self.trade_history)
        wins_count = sum(1 for t in self.trade_history if t.get("pnl", 0.0) > 0)
        win_rate = (wins_count / trades_count * 100) if trades_count > 0 else 0.0

        gross_profit = sum(t.get("pnl", 0.0) for t in self.trade_history if t.get("pnl", 0.0) > 0)
        gross_loss = abs(sum(t.get("pnl", 0.0) for t in self.trade_history if t.get("pnl", 0.0) < 0))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)

        return {
            "tenant_id": self.tenant_id,
            "email": self.email,
            "role": self.role,
            "mode": self.mode,
            "is_active": self.is_active,
            "equity": equity,
            "wallet": {
                "balance": equity,
                "currency": "USDT",
                "mode": self.mode,
                "capital_base": self.rm.cfg.capital_base,
                "paper_wallet": round(self.paper_wallet, 2),
            },
            "position": {
                "side": self.position.side,
                "symbol": self.position.symbol,
                "qty": self.position.qty,
                "entry": self.position.entry,
                "mark_price": mark_price,
                "liquidation": round(liq_price, 2),
                "sl": self.position.sl,
                "trail_sl": self.position.trail_state.trail_sl,
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "open_time": self.position.open_time,
            } if self.position else None,
            "stats": {
                "trades": trades_count,
                "wins": wins_count,
                "win_rate": round(win_rate, 1),
                "profit_factor": profit_factor,
                "daily_pnl": round(daily_realized_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "total_daily_pnl": total_daily_pnl,
            },
            "risk": {
                "consecutive_losses": self.rm.state.consecutive_losses,
                "daily_pnl": round(self.rm.state.daily_pnl, 2),
                "daily_limit_pct": self.rm.cfg.daily_loss_cap_pct,
                "halted": self.rm.state.halted,
                "cooldown_until": self.rm.state.cooldown_until_ts,
            },
            "sizing": {
                "sizing_mode": self.rm.cfg.sizing_mode,
                "manual_lot_size": self.rm.cfg.manual_lot_size,
                "risk_per_trade_pct": self.rm.cfg.risk_per_trade_pct,
                "capital_base": self.rm.cfg.capital_base,
                "leverage": self.rm.cfg.leverage,
            },
            "trade_history": self.trade_history,
            "logs": self.recent_logs,
        }
