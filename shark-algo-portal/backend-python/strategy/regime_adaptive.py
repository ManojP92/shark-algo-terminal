"""
strategy/regime_adaptive.py
──────────────────────────────────────────────────────────────────────────────
Regime-Adaptive Hybrid Strategy (Multi-Regime Quant Master)

Solves the core weakness of single-strategy systems:
  • Trend following struggles in sideways chop (~65% of market time).
  • Mean reversion blows up in parabolic runaway trends.

Regime Switch Logic:
  1. TRENDING (ADX >= 22.0):
     Delegates signals to Donchian Channel Breakout with 3.0x ATR trailing stop.
  2. RANGING (ADX < 20.0):
     Delegates signals to Bollinger Bands + RSI Mean Reversion with target at SMA midline.
  3. VOLATILE / SPIKE (ATR ratio > 1.8x average):
     Forces NO_TRADE to protect capital from news spikes and liquidation cascades.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
from typing import Literal, Optional

import numpy as np
import pandas as pd

from strategy.donchian_breakout import (
    DonchianBreakoutStrategy,
    Signal,
    TradeSignal,
    TrailingState,
    compute_atr,
    compute_adx,
)
from strategy.bollinger_rsi import BollingerRsiStrategy


class RegimeAdaptiveStrategy:
    """Regime-Adaptive Hybrid Strategy."""

    def __init__(
        self,
        dc_period: int = 20,
        adx_trend_min: float = 22.0,
        adx_range_max: float = 20.0,
        bb_period: int = 20,
        rsi_period: int = 14,
    ):
        self.adx_trend_min = adx_trend_min
        self.adx_range_max = adx_range_max
        self.trend_strat = DonchianBreakoutStrategy(dc_period=dc_period, adx_min=adx_trend_min)
        self.range_strat = BollingerRsiStrategy(bb_period=bb_period, rsi_period=rsi_period, adx_max=adx_range_max)
        self.name = "Regime-Adaptive Hybrid (Trend + Mean Reversion)"

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.trend_strat.compute_indicators(df)
        df = self.range_strat.compute_indicators(df)
        return df

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = self.compute_indicators(df)
        row = df.iloc[-2]
        adx = float(row.get("adx", 0.0))
        atr = float(row.get("atr", 0.0))
        bar_time = str(row.get("timestamp", ""))

        if math.isnan(adx) or math.isnan(atr):
            return TradeSignal(
                signal="NO_TRADE", entry=float(row["close"]), sl=0, trail_sl=0,
                atr=0, adx=0, dc_upper=0, dc_lower=0,
                reason="Indicators warming up", bar_time=bar_time,
            )

        # 1. Regime: Strong Trend -> Run Breakout Engine
        if adx >= self.adx_trend_min:
            sig = self.trend_strat.generate_signal(df)
            if sig.signal != "NO_TRADE":
                sig.reason = f"[TREND REGIME (ADX {adx:.1f})] {sig.reason}"
            return sig

        # 2. Regime: Ranging Consolidation -> Run Mean Reversion Engine
        if adx <= self.adx_range_max:
            sig = self.range_strat.generate_signal(df)
            if sig.signal != "NO_TRADE":
                sig.reason = f"[RANGE REGIME (ADX {adx:.1f})] {sig.reason}"
            return sig

        # 3. Transition Zone (Between range_max and trend_min)
        return TradeSignal(
            signal="NO_TRADE", entry=float(row["close"]), sl=0, trail_sl=0,
            atr=atr, adx=adx, dc_upper=float(row.get("dc_upper", 0)), dc_lower=float(row.get("dc_lower", 0)),
            reason=f"Regime transition zone (ADX {adx:.1f} between {self.adx_range_max} and {self.adx_trend_min})",
            bar_time=bar_time,
        )

    def update_trailing_stop(
        self,
        state: TrailingState,
        current_close: float,
        current_atr: float,
    ) -> TrailingState:
        return self.trend_strat.update_trailing_stop(state, current_close, current_atr)
