"""
strategy/bollinger_rsi.py
──────────────────────────────────────────────────────────────────────────────
Bollinger Bands + RSI Mean Reversion Strategy (Range-Bound Crypto Engine)

Designed for the 65–70% of the time crypto trades in sideways consolidation.
Capitalizes on temporary price exhaustion near volatility extremes and mean-reverts
back to the 20-period baseline.

Signal Logic:
  1. Bollinger Bands (20 periods, 2.0 Std Dev)
  2. Wilder's RSI (14 periods)
  3. ADX Filter: ADX < 25.0 — ensures we only trade mean reversion in RANGING regimes
     (avoids fading explosive runaway trends).

Trade Entry:
  • LONG  : close <= BB_lower AND RSI <= 32.0 AND ADX < 25.0
  • SHORT : close >= BB_upper AND RSI >= 68.0 AND ADX < 25.0

Exits:
  • Take Profit : When price touches BB_middle (SMA 20) — mean reversion target reached.
  • Stop Loss   : entry ± (1.5 × ATR) to cut losses quickly if breakout starts.
  • Trailing SL : Ratchets at 2.0 × ATR.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

from strategy.donchian_breakout import (
    Signal,
    TradeSignal,
    TrailingState,
    _wilder_smooth,
    compute_atr,
    compute_adx,
)

DEFAULT_BB_PERIOD = 20
DEFAULT_BB_STD = 2.0
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_OVERSOLD = 32.0
DEFAULT_RSI_OVERBOUGHT = 68.0
DEFAULT_ADX_MAX = 25.0
DEFAULT_ATR_MULT_SL = 1.5
DEFAULT_ATR_MULT_TRAIL = 2.0


def compute_bollinger_bands(
    df: pd.DataFrame,
    period: int = DEFAULT_BB_PERIOD,
    num_std: float = DEFAULT_BB_STD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate middle (SMA), upper, and lower Bollinger Bands."""
    c = df["close"].values.astype(float)
    mid = pd.Series(c).rolling(window=period).mean().values
    std = pd.Series(c).rolling(window=period).std().values
    upper = mid + (num_std * std)
    lower = mid - (num_std * std)
    return mid, upper, lower


def compute_rsi(df: pd.DataFrame, period: int = DEFAULT_RSI_PERIOD) -> np.ndarray:
    """Calculate Relative Strength Index (RSI) using standard Wilder smoothing."""
    c = pd.Series(df["close"].values.astype(float))
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.values


class BollingerRsiStrategy:
    """Bollinger Bands + RSI Mean Reversion Strategy."""

    def __init__(
        self,
        bb_period: int = DEFAULT_BB_PERIOD,
        bb_std: float = DEFAULT_BB_STD,
        rsi_period: int = DEFAULT_RSI_PERIOD,
        rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
        rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
        adx_max: float = DEFAULT_ADX_MAX,
        atr_mult_sl: float = DEFAULT_ATR_MULT_SL,
        atr_mult_trail: float = DEFAULT_ATR_MULT_TRAIL,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.adx_max = adx_max
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_trail = atr_mult_trail
        self.name = "Bollinger + RSI Mean Reversion"

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        mid, upper, lower = compute_bollinger_bands(df, self.bb_period, self.bb_std)
        df["bb_mid"] = mid
        df["bb_upper"] = upper
        df["bb_lower"] = lower
        df["rsi"] = compute_rsi(df, self.rsi_period)
        df["atr"] = compute_atr(df, 14)
        adx, plus_di, minus_di = compute_adx(df, 14)
        df["adx"] = adx
        return df

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        df = self.compute_indicators(df)
        row = df.iloc[-2]  # Last closed bar

        close = float(row["close"])
        bb_mid = float(row["bb_mid"])
        bb_upper = float(row["bb_upper"])
        bb_lower = float(row["bb_lower"])
        rsi = float(row["rsi"])
        atr = float(row["atr"])
        adx = float(row["adx"])
        bar_time = str(row.get("timestamp", ""))

        if any(math.isnan(v) for v in [bb_mid, bb_upper, bb_lower, rsi, atr, adx]):
            return TradeSignal(
                signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
                atr=0, adx=0, dc_upper=0, dc_lower=0,
                reason="Indicators warming up", bar_time=bar_time,
            )

        # In strong trend (ADX >= adx_max), do NOT fade it
        if adx >= self.adx_max:
            return TradeSignal(
                signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
                atr=atr, adx=adx, dc_upper=bb_upper, dc_lower=bb_lower,
                reason=f"ADX {adx:.1f} >= {self.adx_max} (Trend active — skip mean reversion)",
                bar_time=bar_time,
            )

        sl_dist = self.atr_mult_sl * atr

        # LONG: Oversold bounce off lower band in ranging market
        if close <= bb_lower and rsi <= self.rsi_oversold:
            sl = close - sl_dist
            trail_sl = close - (self.atr_mult_trail * atr)
            return TradeSignal(
                signal="LONG", entry=close, sl=sl, trail_sl=trail_sl,
                atr=atr, adx=adx, dc_upper=bb_upper, dc_lower=bb_lower,
                reason=f"Oversold bounce: Close ${close:.2f} <= BB Low ${bb_lower:.2f} | RSI {rsi:.1f} <= {self.rsi_oversold}",
                bar_time=bar_time,
            )

        # SHORT: Overbought rejection off upper band in ranging market
        if close >= bb_upper and rsi >= self.rsi_overbought:
            sl = close + sl_dist
            trail_sl = close + (self.atr_mult_trail * atr)
            return TradeSignal(
                signal="SHORT", entry=close, sl=sl, trail_sl=trail_sl,
                atr=atr, adx=adx, dc_upper=bb_upper, dc_lower=bb_lower,
                reason=f"Overbought rejection: Close ${close:.2f} >= BB High ${bb_upper:.2f} | RSI {rsi:.1f} >= {self.rsi_overbought}",
                bar_time=bar_time,
            )

        return TradeSignal(
            signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
            atr=atr, adx=adx, dc_upper=bb_upper, dc_lower=bb_lower,
            reason=f"Within Bands [${bb_lower:.2f}, ${bb_upper:.2f}] | RSI {rsi:.1f}",
            bar_time=bar_time,
        )

    def check_take_profit(self, side: Signal, close: float, row: pd.Series) -> bool:
        """Exit when price crosses the middle band (SMA 20) target."""
        bb_mid = float(row.get("bb_mid", 0))
        if bb_mid <= 0:
            return False
        if side == "LONG" and close >= bb_mid:
            return True
        if side == "SHORT" and close <= bb_mid:
            return True
        return False

    def update_trailing_stop(
        self,
        state: TrailingState,
        current_close: float,
        current_atr: float,
    ) -> TrailingState:
        trail_dist = state.atr_mult * current_atr
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
            atr_mult=state.atr_mult,
        )
