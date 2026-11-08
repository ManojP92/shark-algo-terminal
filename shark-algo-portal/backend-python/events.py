"""
events.py
──────────────────────────────────────────────────────────────────────────────
Signal & Event Data Models for Master-Worker Multi-Tenant Architecture.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class SignalEvent:
    """
    Decoupled Signal Event emitted by MasterEngine to TenantDispatcher.
    Calculated ONCE centrally (O(1)) and distributed to all tenant execution pods.
    """
    symbol: str
    action: str          # "LONG" | "SHORT"
    entry: float         # Suggested entry price (breakout candle close)
    sl: float            # Initial stop loss price
    trail_sl: float      # Initial trailing stop price
    atr: float           # ATR used for risk calculations
    adx: float           # Trend strength
    reason: str          # Human-readable justification
    dc_upper: float = 0.0
    dc_lower: float = 0.0
    event_id: str = field(default_factory=lambda: f"SIG-{int(time.time()*1000)}")
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "symbol": self.symbol,
            "action": self.action,
            "entry": self.entry,
            "sl": self.sl,
            "trail_sl": self.trail_sl,
            "atr": self.atr,
            "adx": self.adx,
            "reason": self.reason,
            "dc_upper": self.dc_upper,
            "dc_lower": self.dc_lower,
            "timestamp": self.timestamp,
        }
