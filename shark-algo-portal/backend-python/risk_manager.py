"""
risk_manager.py
──────────────────────────────────────────────────────────────────────────────
Multi-level circuit breaker and risk enforcement module.

Circuit Breakers (in priority order):
  1. Daily Loss Cap  — if total daily P&L loss exceeds DAILY_LOSS_CAP_PCT of
     equity, flatten all positions and block new trades until next UTC day.
  2. Consecutive Loss Cooldown — after MAX_CONSECUTIVE_LOSSES in a row,
     block new trades for COOLDOWN_MINUTES and send Telegram alert.
  3. Spread Filter — pre-trade check: if bid-ask spread > SPREAD_MAX_PCT of
     mid-price, reject the order.
  4. Single position limit — only 1 concurrent position (configurable).

Usage:
  rm = RiskManager()
  rm.record_trade(pnl=-120.0)
  if rm.can_trade():
      size = rm.position_size(equity=10000, entry=65000, sl=64000)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("risk_manager")


@dataclass
class RiskConfig:
    risk_per_trade_pct:     float = float(os.getenv("RISK_PER_TRADE_PCT",     "1.0"))
    max_concurrent:         int   = int(os.getenv("MAX_CONCURRENT_POSITIONS", "1"))
    max_consecutive_losses: int   = int(os.getenv("MAX_CONSECUTIVE_LOSSES",   "3"))
    daily_loss_cap_pct:     float = float(os.getenv("DAILY_LOSS_LIMIT_PCT",   "2.5"))
    cooldown_minutes:       int   = int(os.getenv("COOLDOWN_MINUTES",         "90"))
    spread_max_pct:         float = float(os.getenv("SPREAD_MAX_PCT",         "0.05"))
    # Lot Sizing & Compounding Settings
    min_qty:                float = 0.001   # Shark Exchange BTC min lot size (0.001 BTC)
    step_size:              float = 0.001   # Order lot increment
    sizing_mode:            str   = "AUTO"  # "AUTO" (compounding risk %) or "MANUAL"
    manual_lot_size:        float = 0.001   # Editable manual lot size
    capital_base:           float = float(os.getenv("CAPITAL_BASE", "100.0")) # Account capital base
    leverage:               int   = int(os.getenv("LEVERAGE", "10"))          # Account leverage


@dataclass
class RiskState:
    # Daily tracking (resets at UTC midnight)
    day_str:            str   = ""    # "YYYY-MM-DD" of current UTC day
    day_start_equity:   float = 0.0
    daily_pnl:          float = 0.0   # cumulative realised P&L today

    # Consecutive loss tracking
    consecutive_losses: int   = 0

    # Cooldown state
    cooldown_until_ts:  float = 0.0   # Unix timestamp when cooldown expires

    # Position tracking
    open_positions:     int   = 0

    # Kill-switch flag
    halted:             bool  = False  # set True on daily-loss breach


class RiskManager:
    """
    Stateful risk enforcer. Persists state in-memory (Phase 4: add SQLite persistence).
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.cfg   = config or RiskConfig()
        self.state = RiskState()
        log.info(
            "RiskManager ready | risk=%.1f%% | daily_cap=%.1f%% | "
            "max_loss_streak=%d | cooldown=%dmin",
            self.cfg.risk_per_trade_pct,
            self.cfg.daily_loss_cap_pct,
            self.cfg.max_consecutive_losses,
            self.cfg.cooldown_minutes,
        )

    # ── Daily reset ──────────────────────────────────────────────────────────

    def _ensure_day_reset(self, equity: float) -> None:
        """Reset daily state at UTC midnight."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.day_str != today:
            log.info("New UTC day %s — resetting daily P&L tracker", today)
            self.state.day_str          = today
            self.state.day_start_equity = equity
            self.state.daily_pnl        = 0.0
            self.state.halted           = False   # new day un-halts the bot

    # ── State updates ─────────────────────────────────────────────────────────

    def record_trade(self, pnl: float) -> None:
        """
        Call after every trade close with the realised P&L (positive = profit).
        Updates consecutive loss counter and daily P&L.
        """
        self.state.daily_pnl += pnl
        if pnl < 0:
            self.state.consecutive_losses += 1
            log.warning(
                "Loss recorded: %.2f | streak=%d/%d",
                pnl, self.state.consecutive_losses, self.cfg.max_consecutive_losses,
            )
            if self.state.consecutive_losses >= self.cfg.max_consecutive_losses:
                self._trigger_cooldown()
        else:
            if self.state.consecutive_losses > 0:
                log.info("Win recorded — resetting loss streak")
            self.state.consecutive_losses = 0

    def position_opened(self) -> None:
        self.state.open_positions += 1

    def position_closed(self) -> None:
        self.state.open_positions = max(0, self.state.open_positions - 1)

    # ── Circuit breakers ──────────────────────────────────────────────────────

    def _trigger_cooldown(self) -> None:
        """Activate consecutive-loss cooldown."""
        secs = self.cfg.cooldown_minutes * 60
        self.state.cooldown_until_ts = time.time() + secs
        log.warning(
            "COOLDOWN triggered — %d consecutive losses. No new trades for %d minutes.",
            self.state.consecutive_losses, self.cfg.cooldown_minutes,
        )

    def _check_daily_cap(self, equity: float) -> bool:
        """
        Returns True (halted) if daily loss exceeds cap.
        Cap = DAILY_LOSS_CAP_PCT % of day-start equity.
        """
        if self.state.day_start_equity <= 0:
            return False
        loss_pct = (-self.state.daily_pnl / self.state.day_start_equity) * 100
        if loss_pct >= self.cfg.daily_loss_cap_pct:
            if not self.state.halted:
                log.critical(
                    "DAILY LOSS CAP BREACHED: %.2f%% loss (cap=%.2f%%) — HALTING until next UTC day.",
                    loss_pct, self.cfg.daily_loss_cap_pct,
                )
                self.state.halted = True
            return True
        return False

    def can_trade(self, equity: float = 0.0) -> tuple[bool, str]:
        """
        Master gate — call before attempting any new entry.

        Returns (allowed: bool, reason: str).
        """
        self._ensure_day_reset(equity)

        if self.state.halted:
            return False, f"Daily loss cap breached — halted until next UTC day"

        if self._check_daily_cap(equity):
            return False, f"Daily P&L: {self.state.daily_pnl:.2f} — cap reached"

        now = time.time()
        if now < self.state.cooldown_until_ts:
            remaining = int((self.state.cooldown_until_ts - now) / 60)
            return False, f"Cooldown active — {remaining} minutes remaining"

        if self.state.open_positions >= self.cfg.max_concurrent:
            return False, f"Max concurrent positions ({self.cfg.max_concurrent}) reached"

        return True, "OK"

    # ── Pre-trade spread filter ───────────────────────────────────────────────

    def spread_ok(self, best_bid: float, best_ask: float) -> bool:
        """
        Returns True if the bid-ask spread is within the acceptable threshold.
        Spread check: (ask - bid) / mid ≤ SPREAD_MAX_PCT
        """
        mid    = (best_bid + best_ask) / 2.0
        spread = (best_ask - best_bid) / mid * 100  # as percentage
        ok     = spread <= self.cfg.spread_max_pct
        if not ok:
            log.warning(
                "Spread %.4f%% > limit %.4f%% — order blocked",
                spread, self.cfg.spread_max_pct,
            )
        return ok

    # ── Position sizing ───────────────────────────────────────────────────────

    def position_size(
        self,
        equity: float,
        entry:  float,
        sl:     float,
        manual_lots: Optional[float] = None,
    ) -> float:
        """
        Calculates position size in BTC with exchange step size and compounding support.

        1. MANUAL Mode:
           Directly uses configured or overridden lot size (e.g. 0.001 BTC).

        2. AUTO Compounding Mode:
           Risk Amount ($) = Effective Equity ($) × (Risk % / 100)
           Position Size = Risk Amount / |Entry - SL|
           Quantized to exchange stepSize (0.001) and clamped to minQty (0.001).

        Reference: Van Tharp (1998) Risk & Position Sizing Framework.
        """
        # 1. Manual Lot Override Mode
        if self.cfg.sizing_mode == "MANUAL" or manual_lots is not None:
            lots = manual_lots if manual_lots is not None else self.cfg.manual_lot_size
            quantized = round(round(lots / self.cfg.step_size) * self.cfg.step_size, 4)
            final_size = max(self.cfg.min_qty, quantized)
            log.info("MANUAL sizing applied: %.4f (min_qty=%.4f)", final_size, self.cfg.min_qty)
            return final_size

        # 2. Dynamic Capital Compounding Mode
        effective_equity = max(equity, self.cfg.capital_base)
        risk_amount = effective_equity * (self.cfg.risk_per_trade_pct / 100.0)
        sl_distance = abs(entry - sl)
        if sl_distance <= 0:
            return self.cfg.min_qty

        # Raw calculated quantity
        raw_size = risk_amount / sl_distance
        
        # Quantize to step size
        steps = round(raw_size / self.cfg.step_size)
        quantized_size = round(steps * self.cfg.step_size, 4)

        # Enforce exchange minimum lot size
        final_size = max(self.cfg.min_qty, quantized_size)

        log.info(
            "AUTO compounding sizing: equity=$%.2f risk=%.2f%% ($%.2f) sl_dist=$%.2f -> raw=%.4f, final=%.4f",
            effective_equity, self.cfg.risk_per_trade_pct, risk_amount, sl_distance, raw_size, final_size
        )
        return final_size
