"""
strategy/supertrend.py
──────────────────────────────────────────────────────────────────────────────
Supertrend + EMA Macro Momentum Strategy (Institutional Crypto Trend Rider)

One of the most reliable strategies in crypto for riding explosive multi-week trends.
Eliminates subjective exit decisions by using a dynamic ATR-based trailing envelope.

Signal Logic:
  1. Supertrend Indicator (ATR Period 10, Multiplier 3.0)
  2. EMA Macro Filter (EMA 200 on current timeframe or 50 on faster)
  3. ADX(14) >= 20.0 to verify directional velocity.

Trade Entry:
  • LONG  : Supertrend turns GREEN (Bullish) AND close > EMA(200) AND ADX >= 20.0
  • SHORT : Supertrend turns RED (Bearish) AND close < EMA(200) AND ADX >= 20.0

Exits:
  • Supertrend Flip: Exit position when Supertrend changes color.
  • Stop Loss: Initial stop set at Supertrend line or 1.5x ATR.
  • Trailing Stop: Continuously tracks the Supertrend line as dynamic support/resistance.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional, Tuple

import numpy as np
import pandas as pd

from strategy.donchian_breakout import (
    Signal,
    TradeSignal,
    TrailingState,
    compute_atr,
    compute_adx,
)

DEFAULT_ST_PERIOD = 10
DEFAULT_ST_MULTIPLIER = 3.0
DEFAULT_EMA_PERIOD = 100  # 100 on 15m gives ~25 hours trend baseline
DEFAULT_ADX_MIN = 20.0


def compute_supertrend(
    df: pd.DataFrame,
    period: int = DEFAULT_ST_PERIOD,
    multiplier: float = DEFAULT_ST_MULTIPLIER,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Computes Supertrend line and direction (Pine Script standard).
    Returns (supertrend, direction, upper_band, lower_band).
    direction: +1 for Bullish (Green), -1 for Bearish (Red).
    """
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)

    atr = compute_atr(df, period)
    hl2 = (h + l) / 2.0

    basic_upper = hl2 + (multiplier * atr)
    basic_lower = hl2 - (multiplier * atr)

    upper_band = np.copy(basic_upper)
    lower_band = np.copy(basic_lower)
    st = np.zeros(n)
    direction = np.ones(n, dtype=int)

    start = period + 2
    if start < n:
        direction[start] = 1 if c[start] > hl2[start] else -1

    for i in range(start + 1, n):
        if math.isnan(atr[i]):
            continue

        # Lower band ratchet
        if c[i - 1] > lower_band[i - 1]:
            lower_band[i] = max(basic_lower[i], lower_band[i - 1])
        else:
            lower_band[i] = basic_lower[i]

        # Upper band ratchet
        if c[i - 1] < upper_band[i - 1]:
            upper_band[i] = min(basic_upper[i], upper_band[i - 1])
        else:
            upper_band[i] = basic_upper[i]

        # Direction flip
        if direction[i - 1] == 1 and c[i] < lower_band[i]:
            direction[i] = -1
        elif direction[i - 1] == -1 and c[i] > upper_band[i]:
            direction[i] = 1
        else:
            direction[i] = direction[i - 1]

        st[i] = lower_band[i] if direction[i] == 1 else upper_band[i]

    return st, direction, upper_band, lower_band


def compute_ema(series: pd.Series, period: int) -> np.ndarray:
    return series.ewm(span=period, adjust=False).mean().values


class SupertrendMomentumStrategy:
    """Supertrend + Macro EMA Momentum Strategy."""

    def __init__(
        self,
        st_period: int = DEFAULT_ST_PERIOD,
        st_multiplier: float = DEFAULT_ST_MULTIPLIER,
        ema_period: int = DEFAULT_EMA_PERIOD,
        adx_min: float = DEFAULT_ADX_MIN,
    ):
        self.st_period = st_period
        self.st_multiplier = st_multiplier
        self.ema_period = ema_period
        self.adx_min = adx_min
        self.name = "Supertrend Momentum Trend Rider"

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        st, direction, upper, lower = compute_supertrend(df, self.st_period, self.st_multiplier)
        df["st"] = st
        df["st_dir"] = direction
        df["st_upper"] = upper
        df["st_lower"] = lower
        df["ema_trend"] = compute_ema(df["close"], self.ema_period)
        df["atr"] = compute_atr(df, 14)
        adx, plus_di, minus_di = compute_adx(df, 14)
        df["adx"] = adx
        return df

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = self.compute_indicators(df)
        row = df.iloc[-2]       # Last closed bar
        prev_row = df.iloc[-3]  # Previous closed bar

        close = float(row["close"])
        st = float(row["st"])
        st_dir = int(row["st_dir"])
        prev_st_dir = int(prev_row["st_dir"])
        ema_trend = float(row["ema_trend"])
        atr = float(row["atr"])
        adx = float(row["adx"])
        bar_time = str(row.get("timestamp", ""))

        if any(math.isnan(v) for v in [st, ema_trend, atr, adx]):
            return TradeSignal(
                signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
                atr=0, adx=0, dc_upper=0, dc_lower=0,
                reason="Indicators warming up", bar_time=bar_time,
            )

        if adx < self.adx_min:
            return TradeSignal(
                signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
                atr=atr, adx=adx, dc_upper=st, dc_lower=st,
                reason=f"ADX {adx:.1f} < {self.adx_min} (Insufficient trend velocity)",
                bar_time=bar_time,
            )

        # Bullish Supertrend Flip with EMA Filter confirmation
        if st_dir == 1 and prev_st_dir != 1 and close > ema_trend:
            sl = max(st, close - (1.5 * atr))
            return TradeSignal(
                signal="LONG", entry=close, sl=sl, trail_sl=st,
                atr=atr, adx=adx, dc_upper=st, dc_lower=st,
                reason=f"Bullish Supertrend flip: Close ${close:.2f} > EMA({self.ema_period}) ${ema_trend:.2f} | ST Line ${st:.2f}",
                bar_time=bar_time,
            )

        # Bearish Supertrend Flip with EMA Filter confirmation
        if st_dir == -1 and prev_st_dir != -1 and close < ema_trend:
            sl = min(st, close + (1.5 * atr))
            return TradeSignal(
                signal="SHORT", entry=close, sl=sl, trail_sl=st,
                atr=atr, adx=adx, dc_upper=st, dc_lower=st,
                reason=f"Bearish Supertrend flip: Close ${close:.2f} < EMA({self.ema_period}) ${ema_trend:.2f} | ST Line ${st:.2f}",
                bar_time=bar_time,
            )

        return TradeSignal(
            signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
            atr=atr, adx=adx, dc_upper=st, dc_lower=st,
            reason=f"Holding Supertrend {'BULL' if st_dir == 1 else 'BEAR'} (ST: ${st:.2f})",
            bar_time=bar_time,
        )

    def update_trailing_stop(
        self,
        state: TrailingState,
        current_close: float,
        current_atr: float,
    ) -> TrailingState:
        # Trails dynamically with ratchet
        trail_dist = 2.5 * current_atr
        if state.side == "LONG":
            new_best = max(state.best_price, current_close)
            new_sl = max(state.trail_sl, new_best - trail_dist)
        else:
            new_best = min(state.best_price, current_close)
            new_sl = min(state.trail_sl, new_best + trail_dist)

        return TrailingState(
            side=state.side,
            entry=state.entry,
            best_price=new_best,
            trail_sl=new_sl,
            atr_mult=2.5,
        )
