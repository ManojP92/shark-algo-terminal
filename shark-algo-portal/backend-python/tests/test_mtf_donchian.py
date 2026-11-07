"""
test_mtf_donchian.py
──────────────────────────────────────────────────────────────────────────────
Unit tests for Multi-Timeframe (MTF) Donchian Breakout Strategy:
- Macro level: 15m Donchian Channel + 15m ADX momentum gate
- Micro trigger: 5m candle close + 5m ATR sizing/trailing stop
──────────────────────────────────────────────────────────────────────────────
"""

import numpy as np
import pandas as pd
import pytest
from strategy.donchian_breakout import DonchianBreakoutStrategy, TradeSignal


def _generate_synthetic_candles(n: int, base: float, trend: float, vol: float, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = [base]
    for _ in range(1, n):
        step = trend + rng.normal(0, vol)
        closes.append(closes[-1] + step)
    closes = np.array(closes)
    highs = closes + np.abs(rng.normal(0, vol * 0.8, n))
    lows = closes - np.abs(rng.normal(0, vol * 0.8, n))
    opens = np.concatenate([[base], closes[:-1]])
    volume = rng.uniform(10, 100, n)
    timestamps = pd.date_range("2026-11-01", periods=n, freq="5min")

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volume,
    })


def test_mtf_long_signal():
    """5m close breaks above 15m DC upper with 15m ADX >= 22.0 -> LONG."""
    strat = DonchianBreakoutStrategy(dc_period=10, adx_min=20.0)

    # 15m candles: strong uptrend
    df_15m = _generate_synthetic_candles(60, base=65000, trend=50.0, vol=15.0, seed=1)
    # 5m candles: matching uptrend, last closed bar high
    df_5m = _generate_synthetic_candles(120, base=65000, trend=25.0, vol=10.0, seed=2)

    # Force 5m close to decisively exceed 15m upper
    upper_15m = df_15m["high"].iloc[-15:-1].max()
    df_5m.loc[df_5m.index[-2], "close"] = upper_15m + 50.0

    sig = strat.generate_mtf_signal(df_15m, df_5m)

    assert sig.signal == "LONG"
    assert sig.entry == pytest.approx(upper_15m + 50.0)
    assert sig.sl < sig.entry
    assert sig.trail_sl < sig.entry
    assert sig.atr > 0
    assert sig.adx >= 20.0
    assert "5m Close" in sig.reason
    assert "15m DC Upper" in sig.reason


def test_mtf_short_signal():
    """5m close breaks below 15m DC lower with 15m ADX >= 22.0 -> SHORT."""
    strat = DonchianBreakoutStrategy(dc_period=10, adx_min=20.0)

    # 15m candles: downtrend
    df_15m = _generate_synthetic_candles(60, base=65000, trend=-50.0, vol=15.0, seed=3)
    # 5m candles: downtrend
    df_5m = _generate_synthetic_candles(120, base=65000, trend=-25.0, vol=10.0, seed=4)

    # Force 5m close below 15m lower
    lower_15m = df_15m["low"].iloc[-15:-1].min()
    df_5m.loc[df_5m.index[-2], "close"] = lower_15m - 50.0

    sig = strat.generate_mtf_signal(df_15m, df_5m)

    assert sig.signal == "SHORT"
    assert sig.entry == pytest.approx(lower_15m - 50.0)
    assert sig.sl > sig.entry
    assert sig.trail_sl > sig.entry
    assert sig.atr > 0
    assert sig.adx >= 20.0
    assert "5m Close" in sig.reason
    assert "15m DC Lower" in sig.reason


def test_mtf_adx_filter_blocks():
    """If 15m ADX < adx_min (sideways market), no trade even if 5m close breaks DC."""
    strat = DonchianBreakoutStrategy(dc_period=10, adx_min=45.0)  # Very high ADX requirement

    df_15m = _generate_synthetic_candles(60, base=65000, trend=0.0, vol=10.0, seed=5)
    df_5m = _generate_synthetic_candles(120, base=65000, trend=0.0, vol=8.0, seed=6)

    # Even if 5m close shoots above 15m upper:
    upper_15m = df_15m["high"].iloc[-15:-1].max()
    df_5m.loc[df_5m.index[-2], "close"] = upper_15m + 100.0

    sig = strat.generate_mtf_signal(df_15m, df_5m)

    assert sig.signal == "NO_TRADE"
    assert "sideways market" in sig.reason


def test_mtf_inside_channel_no_trade():
    """5m close inside 15m DC channel -> NO_TRADE."""
    strat = DonchianBreakoutStrategy(dc_period=10, adx_min=10.0)

    df_15m = _generate_synthetic_candles(60, base=65000, trend=10.0, vol=20.0, seed=7)
    df_5m = _generate_synthetic_candles(120, base=65000, trend=5.0, vol=10.0, seed=8)

    # Force 5m close right at midpoint of 15m DC
    df_15m_ind = strat.compute_indicators(df_15m)
    dc_mid = (df_15m_ind.iloc[-2]["dc_upper"] + df_15m_ind.iloc[-2]["dc_lower"]) / 2.0
    df_5m.loc[df_5m.index[-2], "close"] = dc_mid

    sig = strat.generate_mtf_signal(df_15m, df_5m)

    assert sig.signal == "NO_TRADE"
    assert "inside 15m DC" in sig.reason


def test_mtf_warmup_guard():
    """If either dataframe has insufficient bars for indicator warmup, gracefully return NO_TRADE."""
    strat = DonchianBreakoutStrategy(dc_period=20, adx_period=14, atr_period=14)

    df_short = _generate_synthetic_candles(5, base=65000, trend=0.0, vol=10.0)
    df_valid = _generate_synthetic_candles(60, base=65000, trend=10.0, vol=10.0)

    sig1 = strat.generate_mtf_signal(df_short, df_valid)
    assert sig1.signal == "NO_TRADE"
    assert "warmup" in sig1.reason

    sig2 = strat.generate_mtf_signal(df_valid, df_short)
    assert sig2.signal == "NO_TRADE"
    assert "warmup" in sig2.reason
