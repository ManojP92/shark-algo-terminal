"""
tests/test_indicators.py
──────────────────────────────────────────────────────────────────────────────
Unit tests for every indicator in regime_detector.py.

Test philosophy:
  • Each indicator is tested against a known synthetic price series where
    the expected output can be computed by hand or verified against a
    reference implementation.
  • Edge cases: flat series, single-direction trend, NaN propagation.
  • Regime classifier: boundary values and priority order.

Run:
  pytest tests/test_indicators.py -v
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pandas as pd
import pytest

# Allow running from backend-python/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from regime_detector import (
    compute_true_range,
    compute_atr,
    compute_adx,
    compute_choppiness,
    compute_atr_ratio,
    classify_regime,
    compute_all_indicators,
    REGIME_TRENDING,
    REGIME_RANGING,
    REGIME_VOLATILE,
    REGIME_UNCLEAR,
    ATR_PERIOD,
    ADX_PERIOD,
    CHOP_PERIOD,
    ADX_TREND_MIN,
    ADX_RANGE_MAX,
    CHOP_TREND_MAX,
    CHOP_RANGE_MIN,
    ATR_RATIO_VOLATILE,
)

# ──────────────────────────────────────────────────────────────────────────────
#  Shared test fixtures / helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_df(opens, highs, lows, closes, volumes=None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from lists."""
    n = len(closes)
    if volumes is None:
        volumes = [1000.0] * n
    return pd.DataFrame({
        "open":   opens,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": volumes,
    })


def flat_df(price: float = 100.0, n: int = 60) -> pd.DataFrame:
    """Perfectly flat market — all OHLC the same, zero ATR."""
    return make_df(
        opens=[price] * n,
        highs=[price] * n,
        lows=[price] * n,
        closes=[price] * n,
    )


def trending_up_df(start: float = 100.0, step: float = 1.0, n: int = 60) -> pd.DataFrame:
    """
    Strongly trending-up series.
    Each bar: open = prev close, close = open + step.
    High = close + 0.1, low = open - 0.1  (small wicks).
    """
    closes = [start + step * i for i in range(n)]
    opens  = [start + step * i - step for i in range(n)]
    opens[0] = start
    highs  = [c + 0.1 for c in closes]
    lows   = [o - 0.1 for o in opens]
    return make_df(opens, highs, lows, closes)


def ranging_df(mid: float = 100.0, amplitude: float = 2.0, n: int = 60) -> pd.DataFrame:
    """
    Oscillating market: price alternates ±amplitude around mid.
    Creates a choppy / ranging scenario.
    """
    closes = [mid + (amplitude if i % 2 == 0 else -amplitude) for i in range(n)]
    opens  = [mid - (amplitude if i % 2 == 0 else -amplitude) for i in range(n)]
    highs  = [c + 0.5 for c in closes]
    lows   = [o - 0.5 for o in opens]
    return make_df(opens, highs, lows, closes)


# ──────────────────────────────────────────────────────────────────────────────
#  1. True Range
# ──────────────────────────────────────────────────────────────────────────────

class TestTrueRange:
    def test_first_bar_is_nan(self):
        df = make_df([10], [12], [9], [11])
        tr = compute_true_range(df)
        assert np.isnan(tr[0]), "TR[0] must be NaN (no previous close)"

    def test_simple_hl_dominant(self):
        """When H-L > |H-prevC| and |L-prevC|, TR = H-L."""
        df = make_df(
            opens= [100, 100],
            highs= [110, 120],
            lows=  [90,  80],
            closes=[105, 100],
        )
        tr = compute_true_range(df)
        # Bar 1: H=120, L=80, prevC=105
        # H-L = 40, |H-prevC| = 15, |L-prevC| = 25  → TR = 40
        assert pytest.approx(tr[1], rel=1e-6) == 40.0

    def test_gap_up_dominant(self):
        """Gap-up: |H - prevClose| is largest."""
        df = make_df(
            opens= [100, 150],
            highs= [105, 155],
            lows=  [95,  148],
            closes=[100, 152],
        )
        tr = compute_true_range(df)
        # Bar 1: H=155, L=148, prevC=100
        # H-L = 7, |H-prevC| = 55, |L-prevC| = 48 → TR = 55
        assert pytest.approx(tr[1], rel=1e-6) == 55.0

    def test_gap_down_dominant(self):
        """Gap-down: |L - prevClose| is largest."""
        df = make_df(
            opens= [100, 50],
            highs= [105, 55],
            lows=  [95,  48],
            closes=[100, 52],
        )
        tr = compute_true_range(df)
        # Bar 1: H=55, L=48, prevC=100
        # H-L=7, |H-prevC|=45, |L-prevC|=52 → TR = 52
        assert pytest.approx(tr[1], rel=1e-6) == 52.0

    def test_flat_series_zero_tr(self):
        """Flat market → TR = 0 on every bar (after bar 0)."""
        df = flat_df(n=10)
        tr = compute_true_range(df)
        assert np.isnan(tr[0])
        assert np.all(tr[1:] == 0.0)


# ──────────────────────────────────────────────────────────────────────────────
#  2. ATR (Wilder's Smoothing)
# ──────────────────────────────────────────────────────────────────────────────

class TestATR:
    def test_returns_array_same_length(self):
        df = trending_up_df(n=40)
        atr = compute_atr(df, period=14)
        assert len(atr) == 40

    def test_first_period_nan(self):
        """First 14 bars should be NaN (seed not ready)."""
        df = trending_up_df(n=40)
        atr = compute_atr(df, period=14)
        # Bars 0..13 → NaN  (bar 0 is always NaN; seed at bar 14)
        assert np.all(np.isnan(atr[:14]))

    def test_positive_after_warmup(self):
        df = trending_up_df(n=40)
        atr = compute_atr(df, period=14)
        valid = atr[~np.isnan(atr)]
        assert np.all(valid > 0), "ATR must be positive in a trending market"

    def test_flat_market_zero_atr(self):
        """Flat price → ATR converges to 0."""
        df = flat_df(n=50)
        atr = compute_atr(df, period=14)
        valid = atr[~np.isnan(atr)]
        assert np.all(valid == 0.0), "Flat market must produce zero ATR"

    def test_wilder_seed_value(self):
        """
        Verify Wilder seed: ATR[14] = SMA(TR, 14) for bars 1..14.
        For a constant-TR series, ATR should equal TR throughout.
        """
        # Build a series where every TR = 5.0 (open/close gap of 5)
        n = 40
        highs  = [i * 5 + 5 for i in range(n)]
        lows   = [i * 5     for i in range(n)]
        closes = [i * 5 + 2.5 for i in range(n)]
        opens  = closes  # not used in TR
        df     = make_df(opens, highs, lows, closes)
        atr    = compute_atr(df, period=14)
        # In this series: H[i]=5i+5, L[i]=5i, C[i]=5i+2.5, prevC[i-1]=5(i-1)+2.5
        # TR[i] = max(H-L=5, |H-prevC|=|5i+5-(5i-2.5)|=7.5, |L-prevC|=|5i-(5i-2.5)|=2.5) = 7.5
        # So every TR = 7.5, Wilder seed = 7.5, and stays at 7.5 throughout.
        valid  = atr[~np.isnan(atr)]
        assert np.allclose(valid, 7.5, atol=1e-6)


# ──────────────────────────────────────────────────────────────────────────────
#  3. ADX
# ──────────────────────────────────────────────────────────────────────────────

class TestADX:
    def test_returns_three_arrays_correct_length(self):
        df = trending_up_df(n=50)
        adx, plus_di, minus_di = compute_adx(df, period=14)
        assert len(adx)      == 50
        assert len(plus_di)  == 50
        assert len(minus_di) == 50

    def test_warmup_nan(self):
        """Early bars should be NaN."""
        df = trending_up_df(n=60)
        adx, _, _ = compute_adx(df, period=14)
        assert np.isnan(adx[0])

    def test_strong_uptrend_high_adx(self):
        """
        A perfectly trending-up series should produce ADX > 25 after warmup.
        """
        df  = trending_up_df(start=100, step=2.0, n=80)
        adx, plus_di, minus_di = compute_adx(df, period=14)
        valid_adx = adx[~np.isnan(adx)]
        # ADX should eventually exceed 25 in a strong uptrend
        assert np.any(valid_adx > 25), (
            f"Expected ADX > 25 in strong uptrend, got max={valid_adx.max():.2f}"
        )

    def test_uptrend_plus_di_dominates(self):
        """In an uptrend, +DI should exceed -DI."""
        df = trending_up_df(start=100, step=2.0, n=60)
        _, plus_di, minus_di = compute_adx(df, period=14)
        # After warmup, +DI > -DI
        # Exclude seed bars where both DIs are 0.0 (no information yet)
        valid_idx = ~(np.isnan(plus_di) | np.isnan(minus_di)) & (plus_di > 0)
        assert np.all(plus_di[valid_idx] > minus_di[valid_idx]), (
            "+DI should dominate -DI in an uptrend"
        )

    def test_adx_range_0_100(self):
        """ADX must always be in [0, 100]."""
        df  = ranging_df(n=80)
        adx, _, _ = compute_adx(df, period=14)
        valid = adx[~np.isnan(adx)]
        assert np.all(valid >= 0) and np.all(valid <= 100)

    def test_di_non_negative(self):
        """Both +DI and -DI must be non-negative."""
        df = ranging_df(n=80)
        _, plus_di, minus_di = compute_adx(df, period=14)
        valid_plus  = plus_di[~np.isnan(plus_di)]
        valid_minus = minus_di[~np.isnan(minus_di)]
        assert np.all(valid_plus  >= 0)
        assert np.all(valid_minus >= 0)


# ──────────────────────────────────────────────────────────────────────────────
#  4. Choppiness Index
# ──────────────────────────────────────────────────────────────────────────────

class TestChoppiness:
    def test_returns_array_correct_length(self):
        df   = ranging_df(n=50)
        chop = compute_choppiness(df, period=14)
        assert len(chop) == 50

    def test_warmup_nan(self):
        df   = ranging_df(n=50)
        chop = compute_choppiness(df, period=14)
        assert np.all(np.isnan(chop[:14]))

    def test_range_0_100(self):
        """CI must be in (0, 100)."""
        df   = ranging_df(n=60)
        chop = compute_choppiness(df, period=14)
        valid = chop[~np.isnan(chop)]
        assert np.all(valid > 0) and np.all(valid < 100)

    def test_trending_produces_low_chop(self):
        """
        Strong directional movement → CI below 61.8 (ideally below 38.2).
        We test that a trending series produces CI < 61 eventually.
        """
        df   = trending_up_df(start=100, step=3.0, n=80)
        chop = compute_choppiness(df, period=14)
        valid = chop[~np.isnan(chop)]
        assert np.any(valid < 61.0), (
            f"Expected CI < 61 in a trending market, got min={valid.min():.2f}"
        )

    def test_ranging_produces_high_chop(self):
        """
        Oscillating market → CI should be high (> 50).
        """
        df   = ranging_df(mid=100, amplitude=3.0, n=80)
        chop = compute_choppiness(df, period=14)
        valid = chop[~np.isnan(chop)]
        # Ranging market should produce elevated CI
        assert np.any(valid > 50.0), (
            f"Expected CI > 50 in a ranging market, got max={valid.max():.2f}"
        )

    def test_flat_market_max_chop(self):
        """
        Perfectly flat market: ATR(1) = 0 and HL range = 0.
        CI is undefined (0/0) → should be NaN, not raise an error.
        """
        df   = flat_df(n=30)
        chop = compute_choppiness(df, period=14)
        # All valid bars should be NaN (log of 0/0 is undefined)
        valid = chop[14:]
        assert np.all(np.isnan(valid)), "Flat market should produce NaN CI"


# ──────────────────────────────────────────────────────────────────────────────
#  5. ATR Ratio
# ──────────────────────────────────────────────────────────────────────────────

class TestATRRatio:
    def test_constant_atr_ratio_equals_one(self):
        """Constant ATR → ratio = 1.0 throughout."""
        atr   = np.array([5.0] * 50)
        ratio = compute_atr_ratio(atr, avg_period=20)
        valid = ratio[~np.isnan(ratio)]
        assert np.allclose(valid, 1.0, atol=1e-6)

    def test_spiked_atr_ratio_above_threshold(self):
        """Large ATR spike should push ratio > 1.5."""
        atr         = np.array([5.0] * 40 + [20.0] * 5)  # spike at end
        ratio       = compute_atr_ratio(atr, avg_period=20)
        valid       = ratio[~np.isnan(ratio)]
        assert np.any(valid > ATR_RATIO_VOLATILE), (
            f"Expected ratio > {ATR_RATIO_VOLATILE} after ATR spike"
        )

    def test_warmup_nan(self):
        """First avg_period values should be NaN."""
        atr   = np.array([5.0] * 50)
        ratio = compute_atr_ratio(atr, avg_period=20)
        # rolling(20) needs 20 values → ratio[19] is first valid
        assert np.all(np.isnan(ratio[:19]))

    def test_zero_atr_produces_nan(self):
        """Zero ATR → ratio NaN (not division by zero crash)."""
        atr   = np.array([0.0] * 50)
        ratio = compute_atr_ratio(atr, avg_period=20)
        valid = ratio[~np.isnan(ratio)]
        # All valid should be NaN-or-zero (depending on impl)
        assert len(valid) == 0 or np.all(np.isnan(valid))


# ──────────────────────────────────────────────────────────────────────────────
#  6. Regime Classifier
# ──────────────────────────────────────────────────────────────────────────────

class TestRegimeClassifier:
    # ── NaN inputs ────────────────────────────────────────────────────────────
    def test_nan_adx_returns_unclear(self):
        assert classify_regime(float("nan"), 50.0, 1.0) == REGIME_UNCLEAR

    def test_nan_chop_returns_unclear(self):
        assert classify_regime(30.0, float("nan"), 1.0) == REGIME_UNCLEAR

    def test_nan_atr_ratio_returns_unclear(self):
        assert classify_regime(30.0, 35.0, float("nan")) == REGIME_UNCLEAR

    # ── VOLATILE priority (overrides everything) ───────────────────────────────
    def test_volatile_overrides_trending(self):
        """Even if ADX/Chop say TRENDING, high ATR ratio → VOLATILE."""
        result = classify_regime(
            adx=30.0,        # trending
            choppiness=30.0, # trending
            atr_ratio=2.0,   # volatile override
        )
        assert result == REGIME_VOLATILE

    def test_volatile_overrides_ranging(self):
        result = classify_regime(
            adx=15.0,        # ranging
            choppiness=65.0, # ranging
            atr_ratio=1.6,   # volatile override
        )
        assert result == REGIME_VOLATILE

    def test_volatile_exact_threshold(self):
        """ATR ratio exactly at threshold = NOT volatile (> not >=)."""
        result = classify_regime(15.0, 65.0, ATR_RATIO_VOLATILE)
        assert result != REGIME_VOLATILE

    def test_volatile_above_threshold(self):
        result = classify_regime(15.0, 65.0, ATR_RATIO_VOLATILE + 0.001)
        assert result == REGIME_VOLATILE

    # ── TRENDING ─────────────────────────────────────────────────────────────
    def test_trending_both_conditions_met(self):
        result = classify_regime(
            adx=ADX_TREND_MIN + 1,
            choppiness=CHOP_TREND_MAX - 1,
            atr_ratio=1.0,
        )
        assert result == REGIME_TRENDING

    def test_trending_adx_exactly_at_threshold(self):
        """ADX must be STRICTLY greater than threshold."""
        result = classify_regime(ADX_TREND_MIN, CHOP_TREND_MAX - 1, 1.0)
        # ADX == 25, not > 25 → not trending (at boundary)
        assert result != REGIME_TRENDING

    def test_trending_chop_exactly_at_threshold(self):
        """Choppiness must be STRICTLY less than threshold."""
        result = classify_regime(ADX_TREND_MIN + 1, CHOP_TREND_MAX, 1.0)
        assert result != REGIME_TRENDING

    def test_trending_fails_if_only_adx(self):
        """ADX alone without low Choppiness → not trending."""
        result = classify_regime(30.0, 55.0, 1.0)  # Chop too high
        assert result != REGIME_TRENDING

    def test_trending_fails_if_only_chop(self):
        """Low Choppiness alone without ADX → not trending."""
        result = classify_regime(22.0, 30.0, 1.0)  # ADX too low
        assert result != REGIME_TRENDING

    # ── RANGING ──────────────────────────────────────────────────────────────
    def test_ranging_both_conditions_met(self):
        result = classify_regime(
            adx=ADX_RANGE_MAX - 1,
            choppiness=CHOP_RANGE_MIN + 1,
            atr_ratio=1.0,
        )
        assert result == REGIME_RANGING

    def test_ranging_adx_exactly_at_threshold(self):
        """ADX must be STRICTLY less than threshold."""
        result = classify_regime(ADX_RANGE_MAX, CHOP_RANGE_MIN + 1, 1.0)
        assert result != REGIME_RANGING

    def test_ranging_fails_if_only_adx(self):
        result = classify_regime(15.0, 50.0, 1.0)  # Chop too low
        assert result != REGIME_RANGING

    def test_ranging_fails_if_only_chop(self):
        result = classify_regime(22.0, 65.0, 1.0)  # ADX too high
        assert result != REGIME_RANGING

    # ── UNCLEAR ──────────────────────────────────────────────────────────────
    def test_unclear_middle_ground(self):
        """Values between TRENDING and RANGING thresholds → UNCLEAR."""
        result = classify_regime(22.0, 50.0, 1.0)
        assert result == REGIME_UNCLEAR

    def test_unclear_high_adx_high_chop(self):
        """High ADX but also high Choppiness → UNCLEAR."""
        result = classify_regime(30.0, 65.0, 1.0)
        assert result == REGIME_UNCLEAR

    def test_unclear_low_adx_low_chop(self):
        """Low ADX but also low Choppiness → UNCLEAR."""
        result = classify_regime(15.0, 30.0, 1.0)
        assert result == REGIME_UNCLEAR


# ──────────────────────────────────────────────────────────────────────────────
#  7. Integration — compute_all_indicators
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeAllIndicators:
    def test_columns_added(self):
        df = trending_up_df(n=60)
        result = compute_all_indicators(df)
        for col in ["atr", "adx", "plus_di", "minus_di", "chop", "atr_ratio", "regime"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_original_columns_preserved(self):
        df = trending_up_df(n=60)
        result = compute_all_indicators(df)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns

    def test_regime_column_valid_values(self):
        df = ranging_df(n=80)
        result = compute_all_indicators(df)
        valid_regimes = {REGIME_TRENDING, REGIME_RANGING, REGIME_VOLATILE, REGIME_UNCLEAR}
        for r in result["regime"]:
            assert r in valid_regimes, f"Invalid regime: {r}"

    def test_warmup_bars_get_unclear(self):
        """Bars before indicators are ready must be UNCLEAR (NaN indicators)."""
        df     = trending_up_df(n=60)
        result = compute_all_indicators(df)
        # Rows with NaN adx must be classified as UNCLEAR
        nan_adx_rows = result[result["adx"].isna()]
        assert all(r == REGIME_UNCLEAR for r in nan_adx_rows["regime"])

    def test_idempotent(self):
        """Calling compute_all_indicators twice gives same result."""
        import copy
        df1 = trending_up_df(n=60)
        df2 = copy.deepcopy(df1)
        r1 = compute_all_indicators(df1)["regime"].tolist()
        r2 = compute_all_indicators(df2)["regime"].tolist()
        assert r1 == r2
