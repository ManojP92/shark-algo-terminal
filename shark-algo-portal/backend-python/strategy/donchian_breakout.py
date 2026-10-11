"""
strategy/donchian_breakout.py
──────────────────────────────────────────────────────────────────────────────
Institutional Trend-Following Expansion Engine

Signal Logic:
  1. Donchian Channel (25-period) — detect price breakout above/below channel
  2. ADX(14) ≥ 20 — momentum filter, blocks sideways-market trades
  3. ATR(14) — dynamic sizing, initial SL, and trailing stop

Trade Entry:
  • LONG  : close > DC_upper (prev bar) AND ADX ≥ 20
  • SHORT : close < DC_lower (prev bar) AND ADX ≥ 20

Stop Loss: entry ± (ATR_MULT_SL × ATR)     default: 1.5×ATR
Trailing : ratchets to entry ± (ATR_MULT_TRAIL × ATR)  default: 3.0×ATR

References:
  Donchian, R.D. (1960). Trend-following methods in commodity price analysis.
  Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
import pandas as pd

# ── Strategy parameters (can be overridden via constructor) ───────────────────
DEFAULT_DC_PERIOD    = 25      # Donchian Channel lookback
DEFAULT_ADX_PERIOD   = 14      # ADX period
DEFAULT_ATR_PERIOD   = 14      # ATR period
DEFAULT_ADX_MIN      = 20.0    # minimum ADX to permit entry
DEFAULT_ATR_MULT_SL  = 1.5     # initial stop distance = 1.5×ATR
DEFAULT_ATR_MULT_TRAIL = 3.0   # trailing stop distance = 3.0×ATR

Signal = Literal["LONG", "SHORT", "NO_TRADE"]


@dataclass
class TradeSignal:
    signal:    Signal
    entry:     float         # suggested entry price (last close)
    sl:        float         # initial stop-loss price
    trail_sl:  float         # initial trailing-stop price (same as sl at entry)
    atr:       float         # ATR value used for sizing
    adx:       float         # ADX at signal bar
    dc_upper:  float         # Donchian upper at signal bar
    dc_lower:  float         # Donchian lower at signal bar
    reason:    str           # human-readable explanation
    bar_time:  Optional[str] = None   # ISO timestamp of signal bar


@dataclass
class TrailingState:
    """Mutable state for an open trade's trailing stop."""
    side:     Signal        # "LONG" or "SHORT"
    entry:    float
    best_price: float       # highest close seen (LONG) or lowest (SHORT)
    trail_sl:   float       # current trailing SL price
    atr_mult:   float = DEFAULT_ATR_MULT_TRAIL


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATOR HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _wilder_smooth(series: np.ndarray, period: int) -> np.ndarray:
    """
    Wilder's Smoothing (alpha = 1/period). Seeds with SMA of first period values.
    Reference: Wilder (1978) p. 23.
    """
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    alpha = 1.0 / period
    result[period - 1] = np.mean(series[:period])
    for i in range(period, len(series)):
        result[i] = alpha * series[i] + (1.0 - alpha) * result[i - 1]
    return result


def compute_atr(df: pd.DataFrame, period: int = DEFAULT_ATR_PERIOD) -> np.ndarray:
    """
    Average True Range via Wilder's smoothing.
    Reference: Wilder (1978) p. 21-23.
    """
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    prev_c = np.concatenate([[np.nan], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    tr[0] = np.nan
    return np.concatenate([[np.nan], _wilder_smooth(tr[1:], period)])


def compute_adx(
    df: pd.DataFrame, period: int = DEFAULT_ADX_PERIOD
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    ADX + ±DI via Wilder's smoothing.
    Reference: Wilder (1978) p. 47-53.
    Returns: (adx, plus_di, minus_di)
    """
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    up   = h[1:] - h[:-1]
    down = l[:-1] - l[1:]
    prev_c  = c[:-1]
    tr_vals = np.maximum(h[1:] - l[1:],
              np.maximum(np.abs(h[1:] - prev_c), np.abs(l[1:] - prev_c)))
    plus_dm  = np.where((up > down) & (up > 0),    up,   0.0)
    minus_dm = np.where((down > up) & (down > 0), down,  0.0)
    atr_s    = _wilder_smooth(tr_vals, period)
    pdm_s    = _wilder_smooth(plus_dm,  period)
    mdm_s    = _wilder_smooth(minus_dm, period)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi  = np.where(atr_s > 0, 100 * pdm_s / atr_s, 0.0)
        mdi  = np.where(atr_s > 0, 100 * mdm_s / atr_s, 0.0)
        dx   = np.where((pdi + mdi) > 0, 100 * np.abs(pdi - mdi) / (pdi + mdi), 0.0)
    adx_s = _wilder_smooth(dx, period)
    pad = np.array([np.nan])
    return (
        np.concatenate([pad, adx_s]),
        np.concatenate([pad, pdi]),
        np.concatenate([pad, mdi]),
    )


def compute_donchian(
    df: pd.DataFrame, period: int = DEFAULT_DC_PERIOD
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Donchian Channel: rolling max high / min low over `period` bars.
    Upper/lower are computed on the previous bar (shifted by 1) so they
    are NEVER look-ahead — we compare current close to prior channel.

    Reference: Donchian (1960). Trend-following in commodity price analysis.

    Returns: (upper, lower, mid)  — all NaN for first period bars.
    """
    upper_raw = df["high"].rolling(period).max().values
    lower_raw = df["low"].rolling(period).min().values
    # Shift by 1: entry signal uses channel from the COMPLETED prior bar
    upper = np.concatenate([[np.nan], upper_raw[:-1]])
    lower = np.concatenate([[np.nan], lower_raw[:-1]])
    mid   = (upper + lower) / 2.0
    return upper, lower, mid


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGY CLASS
# ══════════════════════════════════════════════════════════════════════════════

class DonchianBreakoutStrategy:
    """
    Institutional Donchian Channel Breakout strategy.

    Parameters
    ----------
    dc_period      : Donchian Channel lookback (default 25)
    adx_period     : ADX period (default 14)
    atr_period     : ATR period (default 14)
    adx_min        : Minimum ADX for entry (default 20.0)
    atr_mult_sl    : Initial SL = entry ± (atr_mult_sl × ATR)  (default 1.5)
    atr_mult_trail : Trailing SL distance = (atr_mult_trail × ATR)  (default 3.0)
    """

    def __init__(
        self,
        dc_period:      int   = DEFAULT_DC_PERIOD,
        adx_period:     int   = DEFAULT_ADX_PERIOD,
        atr_period:     int   = DEFAULT_ATR_PERIOD,
        adx_min:        float = DEFAULT_ADX_MIN,
        atr_mult_sl:    float = DEFAULT_ATR_MULT_SL,
        atr_mult_trail: float = DEFAULT_ATR_MULT_TRAIL,
    ):
        self.dc_period      = dc_period
        self.adx_period     = adx_period
        self.atr_period     = atr_period
        self.adx_min        = adx_min
        self.atr_mult_sl    = atr_mult_sl
        self.atr_mult_trail = atr_mult_trail

    # ── Signal generation ────────────────────────────────────────────────────

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add dc_upper, dc_lower, dc_mid, atr, adx, plus_di, minus_di to df."""
        dc_upper, dc_lower, dc_mid = compute_donchian(df, self.dc_period)
        atr                         = compute_atr(df, self.atr_period)
        adx, plus_di, minus_di      = compute_adx(df, self.adx_period)

        df = df.copy()
        df["dc_upper"]  = dc_upper
        df["dc_lower"]  = dc_lower
        df["dc_mid"]    = dc_mid
        df["atr"]       = atr
        df["adx"]       = adx
        df["plus_di"]   = plus_di
        df["minus_di"]  = minus_di
        return df

    def generate_signal(self, df: pd.DataFrame) -> TradeSignal:
        """
        Evaluate the LAST CLOSED bar and return a TradeSignal.

        The signal bar is df.iloc[-2] (the most-recently closed candle).
        df.iloc[-1] is the forming/current bar — never used for decisions.

        Returns TradeSignal with signal == "NO_TRADE" if conditions not met.
        """
        df = self.compute_indicators(df)

        # Use second-to-last bar (last CLOSED bar)
        row = df.iloc[-2]

        close     = float(row["close"])
        dc_upper  = float(row["dc_upper"])
        dc_lower  = float(row["dc_lower"])
        atr       = float(row["atr"])
        adx       = float(row["adx"])
        bar_time  = str(row.get("timestamp", ""))

        # Guard: indicators not ready (NaN)
        if any(math.isnan(v) for v in [dc_upper, dc_lower, atr, adx]):
            return TradeSignal(
                signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
                atr=0, adx=0, dc_upper=0, dc_lower=0,
                reason="Indicators not ready (warmup)", bar_time=bar_time,
            )

        # ADX momentum filter
        if adx < self.adx_min:
            return TradeSignal(
                signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
                atr=atr, adx=adx, dc_upper=dc_upper, dc_lower=dc_lower,
                reason=f"ADX {adx:.2f} < {self.adx_min} — sideways market, skip",
                bar_time=bar_time,
            )

        sl_dist = self.atr_mult_sl * atr

        # LONG breakout: close above DC upper
        if close > dc_upper:
            sl       = close - sl_dist
            trail_sl = close - (self.atr_mult_trail * atr)
            return TradeSignal(
                signal="LONG", entry=close, sl=sl, trail_sl=trail_sl,
                atr=atr, adx=adx, dc_upper=dc_upper, dc_lower=dc_lower,
                reason=f"Close {close} > DC upper {dc_upper:.2f} | ADX {adx:.2f}",
                bar_time=bar_time,
            )

        # SHORT breakout: close below DC lower
        if close < dc_lower:
            sl       = close + sl_dist
            trail_sl = close + (self.atr_mult_trail * atr)
            return TradeSignal(
                signal="SHORT", entry=close, sl=sl, trail_sl=trail_sl,
                atr=atr, adx=adx, dc_upper=dc_upper, dc_lower=dc_lower,
                reason=f"Close {close} < DC lower {dc_lower:.2f} | ADX {adx:.2f}",
                bar_time=bar_time,
            )

        return TradeSignal(
            signal="NO_TRADE", entry=close, sl=0, trail_sl=0,
            atr=atr, adx=adx, dc_upper=dc_upper, dc_lower=dc_lower,
            reason=f"Price {close} inside DC [{dc_lower:.2f}, {dc_upper:.2f}]",
            bar_time=bar_time,
        )

    # ── Trailing stop update ─────────────────────────────────────────────────

    def update_trailing_stop(
        self,
        state:         TrailingState,
        current_close: float,
        current_atr:   float,
    ) -> TrailingState:
        """
        Ratchet the trailing stop behind a winning position.
        The stop only MOVES in the favourable direction — never widens.

        For LONG  : trail_sl = max(prev_trail_sl, best_price − mult×ATR)
        For SHORT : trail_sl = min(prev_trail_sl, best_price + mult×ATR)
        """
        trail_dist = state.atr_mult * current_atr

        if state.side == "LONG":
            new_best = max(state.best_price, current_close)
            new_sl   = new_best - trail_dist
            # Ratchet only: never move SL backwards
            new_sl   = max(state.trail_sl, new_sl)
        else:   # SHORT
            new_best = min(state.best_price, current_close)
            new_sl   = new_best + trail_dist
            new_sl   = min(state.trail_sl, new_sl)

        return TrailingState(
            side=state.side,
            entry=state.entry,
            best_price=new_best,
            trail_sl=new_sl,
            atr_mult=state.atr_mult,
        )

    # ── Partial scale-out ────────────────────────────────────────────────────

    def should_scale_out(
        self,
        side:  Signal,
        entry: float,
        sl:    float,
        close: float,
    ) -> bool:
        """
        Optional 1:1 R scale-out trigger.
        Returns True when price has moved 1× the initial risk in our favour.
        """
        risk = abs(entry - sl)
        if side == "LONG":
            return close >= entry + risk
        if side == "SHORT":
            return close <= entry - risk
        return False
