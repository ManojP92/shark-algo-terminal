"""
regime_detector.py
──────────────────────────────────────────────────────────────────────────────
Phase 2 — Market Regime Classifier

Fetches 15m BTCUSDT klines from the Node server, computes three indicators,
and classifies the current market regime:

  TRENDING  : ADX(14) > 25  AND  Choppiness(14) < 38
  RANGING   : ADX(14) < 20  AND  Choppiness(14) > 61
  VOLATILE  : ATR_ratio > 1.5  (overrides ADX/Choppiness)
  UNCLEAR   : everything else  → no trading

Indicator References:
  ATR  — Wilder, J.W. (1978). New Concepts in Technical Trading Systems. p. 21-23.
  ADX  — Wilder, J.W. (1978). New Concepts in Technical Trading Systems. p. 47-53.
  Choppiness — Dreiss, E.W. (1993). Choppiness Index. ATAA Journal.

Usage:
  python regime_detector.py                     # live regime on latest bar
  python regime_detector.py --url http://localhost:3001
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests

# ── Shared constants (mirrors shared/constants.json) ──────────────────────────
NODE_URL        = "http://localhost:3001"
PAIR            = "BTCUSDT"
ADX_PERIOD      = 14
ATR_PERIOD      = 14
CHOP_PERIOD     = 14
ATR_AVG_PERIOD  = 20   # denominator for ATR ratio

# Thresholds (match shared/constants.json)
ADX_TREND_MIN      = 25.0
ADX_RANGE_MAX      = 20.0
CHOP_TREND_MAX     = 38.0
CHOP_RANGE_MIN     = 61.0
ATR_RATIO_VOLATILE = 1.5

REGIME_TRENDING = "TRENDING"
REGIME_RANGING  = "RANGING"
REGIME_VOLATILE = "VOLATILE"
REGIME_UNCLEAR  = "UNCLEAR"

# Minimum bars needed before any indicator is valid
MIN_BARS = max(ADX_PERIOD, CHOP_PERIOD) * 2 + ATR_AVG_PERIOD   # ~48 bars


# ══════════════════════════════════════════════════════════════════════════════
#  DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def fetch_klines(
    interval: str = "15m",
    limit: int = 300,
    node_url: str = NODE_URL,
) -> pd.DataFrame:
    """
    Fetch klines from the Node server's /api/klines/<interval> endpoint.

    Returns a DataFrame with columns:
        timestamp (UTC datetime), open, high, low, close, volume
    Sorted oldest → newest, numeric types enforced.
    """
    url = f"{node_url}/api/klines/{interval}?limit={limit}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    body = resp.json()

    if not body.get("ok"):
        raise RuntimeError(f"Node server error: {body.get('error')}")

    return _parse_klines(body["data"])


def fetch_klines_history(
    interval: str = "15m",
    days: int = 30,
    node_url: str = NODE_URL,
) -> pd.DataFrame:
    """
    Fetch historical klines from /api/klines/history (paginated).
    Returns same format as fetch_klines().
    """
    url = f"{node_url}/api/klines/history?interval={interval}&days={days}"
    print(f"  Fetching {days}d of {interval} klines from {url} …", end=" ", flush=True)
    resp = requests.get(url, timeout=120)   # pagination may take a few seconds
    resp.raise_for_status()
    body = resp.json()

    if not body.get("ok"):
        raise RuntimeError(f"Node server error: {body.get('error')}")

    df = _parse_klines(body["data"])
    print(f"got {len(df)} candles ({df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()})")
    return df


def _parse_klines(raw: list[dict]) -> pd.DataFrame:
    """Normalise raw SDK kline list into a typed DataFrame."""
    df = pd.DataFrame(raw)
    # Rename SDK field names → canonical names
    df.rename(columns={"startTime": "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype(np.int64), unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


# ══════════════════════════════════════════════════════════════════════════════
#  INDICATOR COMPUTATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _wilder_smooth(series: np.ndarray, period: int) -> np.ndarray:
    """
    Wilder's Smoothing (RMA): alpha = 1/period.
    Seeds with simple average of first `period` values.

    Reference: Wilder (1978), New Concepts in Technical Trading Systems, p. 23.

    Parameters
    ----------
    series : 1-D float array (NaN allowed only at head)
    period : smoothing period

    Returns
    -------
    1-D float array, same length as input; NaN before seed index.
    """
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result

    alpha = 1.0 / period
    seed_idx = period - 1
    result[seed_idx] = np.mean(series[:period])

    for i in range(seed_idx + 1, len(series)):
        result[i] = alpha * series[i] + (1.0 - alpha) * result[i - 1]

    return result


def compute_true_range(df: pd.DataFrame) -> np.ndarray:
    """
    True Range: max(H-L, |H-prevC|, |L-prevC|)
    Index 0 is NaN (no previous close).

    Reference: Wilder (1978), p. 21.
    """
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values

    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    tr[0] = np.nan
    return tr


def compute_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> np.ndarray:
    """
    Average True Range using Wilder's smoothing.

    Reference: Wilder (1978), p. 23.
    """
    tr = compute_true_range(df)
    # Drop the leading NaN for Wilder seed (use bars 1..period as seed)
    tr_valid = tr[1:]
    atr_valid = _wilder_smooth(tr_valid, period)
    return np.concatenate([[np.nan], atr_valid])


def compute_adx(
    df: pd.DataFrame,
    period: int = ADX_PERIOD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Average Directional Index (ADX) with +DI and -DI.

    Reference: Wilder (1978), New Concepts in Technical Trading Systems, p. 47-53.

    Returns
    -------
    adx     : 1-D array
    plus_di : 1-D array  (+DI14)
    minus_di: 1-D array  (-DI14)
    """
    n     = len(df)
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values

    # Directional movement (bars 1..n-1, length = n-1)
    up_move   = high[1:]   - high[:-1]
    down_move = low[:-1]   - low[1:]

    # +DM: up_move wins AND is positive
    plus_dm  = np.where((up_move > down_move) & (up_move > 0),  up_move,   0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # True Range for bars 1..n-1
    prev_close = close[:-1]
    tr_vals    = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
    )

    # Wilder-smooth TR, +DM, -DM
    atr_s      = _wilder_smooth(tr_vals, period)
    plus_dm_s  = _wilder_smooth(plus_dm,  period)
    minus_dm_s = _wilder_smooth(minus_dm, period)

    # +DI and -DI (guard against zero ATR)
    with np.errstate(invalid="ignore", divide="ignore"):
        plus_di_s  = np.where(atr_s > 0, 100.0 * plus_dm_s  / atr_s, 0.0)
        minus_di_s = np.where(atr_s > 0, 100.0 * minus_dm_s / atr_s, 0.0)
        dx = np.where(
            (plus_di_s + minus_di_s) > 0,
            100.0 * np.abs(plus_di_s - minus_di_s) / (plus_di_s + minus_di_s),
            0.0,
        )

    adx_s = _wilder_smooth(dx, period)

    # Pad with one leading NaN (we dropped bar 0 for DM computation)
    pad = np.array([np.nan])
    adx      = np.concatenate([pad, adx_s])
    plus_di  = np.concatenate([pad, plus_di_s])
    minus_di = np.concatenate([pad, minus_di_s])
    return adx, plus_di, minus_di


def compute_choppiness(df: pd.DataFrame, period: int = CHOP_PERIOD) -> np.ndarray:
    """
    Choppiness Index.

    CI(n) = 100 × log10( Σ TR(1,i) over n bars  /  (HH(n) − LL(n)) ) / log10(n)

    Range: ~(0, 100)
      > 61.8 → choppy / ranging
      < 38.2 → trending (directional)

    Reference: Dreiss, E.W. (1993). Choppiness Index. ATAA Journal.
    """
    tr   = compute_true_range(df)
    high = df["high"].values
    low  = df["low"].values
    n    = len(df)

    ci = np.full(n, np.nan)
    log10_period = math.log10(period)

    for i in range(period, n):
        # Sum of individual TRs over the last `period` bars (bars i-period+1 … i)
        tr_slice  = tr[i - period + 1 : i + 1]
        tr_sum    = np.nansum(tr_slice)

        # Highest High and Lowest Low over same window
        hh        = np.max(high[i - period + 1 : i + 1])
        ll        = np.min(low[i  - period + 1 : i + 1])
        hl_range  = hh - ll

        if hl_range > 0 and tr_sum > 0:
            ci[i] = 100.0 * math.log10(tr_sum / hl_range) / log10_period

    return ci


def compute_atr_ratio(
    atr: np.ndarray,
    avg_period: int = ATR_AVG_PERIOD,
) -> np.ndarray:
    """
    ATR ratio = current ATR / rolling mean of ATR over `avg_period` bars.
    Ratio > 1.5 → abnormally high volatility (VOLATILE regime).
    """
    atr_series = pd.Series(atr)
    atr_ma     = atr_series.rolling(avg_period).mean().values
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(atr_ma > 0, atr / atr_ma, np.nan)
    return ratio


# ══════════════════════════════════════════════════════════════════════════════
#  REGIME CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def classify_regime(
    adx:       float,
    choppiness: float,
    atr_ratio: float,
) -> str:
    """
    Classify market regime from scalar indicator values.

    Priority order:
      1. VOLATILE  — ATR ratio > 1.5 (overrides everything)
      2. TRENDING  — ADX > 25 AND Choppiness < 38
      3. RANGING   — ADX < 20 AND Choppiness > 61
      4. UNCLEAR   — anything else (do NOT trade)

    Reference: Project spec §2 Market Regime Classifier.
    """
    # Guard: NaN indicators → UNCLEAR
    if any(math.isnan(v) for v in [adx, choppiness, atr_ratio]):
        return REGIME_UNCLEAR

    # Priority 1: volatile regardless of trend/range
    if atr_ratio > ATR_RATIO_VOLATILE:
        return REGIME_VOLATILE

    # Priority 2: trending
    if adx > ADX_TREND_MIN and choppiness < CHOP_TREND_MAX:
        return REGIME_TRENDING

    # Priority 3: ranging
    if adx < ADX_RANGE_MAX and choppiness > CHOP_RANGE_MIN:
        return REGIME_RANGING

    return REGIME_UNCLEAR


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DETECTION FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add ADX, +DI, -DI, Choppiness, ATR, ATR_ratio, and Regime columns to df.
    Modifies df in-place and returns it.
    """
    atr               = compute_atr(df)
    adx, plus_di, minus_di = compute_adx(df)
    chop              = compute_choppiness(df)
    atr_ratio         = compute_atr_ratio(atr)

    df["atr"]       = atr
    df["adx"]       = adx
    df["plus_di"]   = plus_di
    df["minus_di"]  = minus_di
    df["chop"]      = chop
    df["atr_ratio"] = atr_ratio

    df["regime"] = df.apply(
        lambda row: classify_regime(
            float(row["adx"])       if not pd.isna(row["adx"])       else float("nan"),
            float(row["chop"])      if not pd.isna(row["chop"])      else float("nan"),
            float(row["atr_ratio"]) if not pd.isna(row["atr_ratio"]) else float("nan"),
        ),
        axis=1,
    )

    return df


def detect_current_regime(
    node_url: str = NODE_URL,
    limit: int = 300,
) -> dict:
    """
    Fetch 15m klines and return the latest bar's regime and indicator values.

    Returns
    -------
    dict with keys:
        timestamp, close, atr, adx, plus_di, minus_di, chop, atr_ratio, regime
    """
    df = fetch_klines("15m", limit=limit, node_url=node_url)
    df = compute_all_indicators(df)

    # Use the last CLOSED bar (second-to-last row, since the last may be forming)
    row = df.iloc[-2]

    return {
        "timestamp":  row["timestamp"].isoformat(),
        "close":      round(float(row["close"]), 2),
        "atr":        round(float(row["atr"]),       4),
        "adx":        round(float(row["adx"]),       2),
        "plus_di":    round(float(row["plus_di"]),   2),
        "minus_di":   round(float(row["minus_di"]),  2),
        "chop":       round(float(row["chop"]),      2),
        "atr_ratio":  round(float(row["atr_ratio"]), 3),
        "regime":     row["regime"],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _fmt(value: float | None, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:.{decimals}f}"


REGIME_COLOURS = {
    REGIME_TRENDING:  "\033[32m",   # green
    REGIME_RANGING:   "\033[34m",   # blue
    REGIME_VOLATILE:  "\033[31m",   # red
    REGIME_UNCLEAR:   "\033[33m",   # yellow
}
RESET = "\033[0m"


def print_regime_report(result: dict) -> None:
    regime  = result["regime"]
    colour  = REGIME_COLOURS.get(regime, "")
    ts      = result["timestamp"]

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         SHARK ALGO — REGIME DETECTOR (15m)               ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(f"  Bar time   : {ts}")
    print(f"  Close      : ${_fmt(result['close'])}")
    print()
    print(f"  ATR(14)    : {_fmt(result['atr'], 2)}")
    print(f"  ADX(14)    : {_fmt(result['adx'])}   [> {ADX_TREND_MIN} = trending, < {ADX_RANGE_MAX} = ranging]")
    print(f"  +DI(14)    : {_fmt(result['plus_di'])}")
    print(f"  -DI(14)    : {_fmt(result['minus_di'])}")
    print(f"  Chop(14)   : {_fmt(result['chop'])}   [< {CHOP_TREND_MAX} = trending, > {CHOP_RANGE_MIN} = ranging]")
    print(f"  ATR Ratio  : {_fmt(result['atr_ratio'], 3)}   [> {ATR_RATIO_VOLATILE} = volatile]")
    print()
    print(f"  ▶ REGIME   : {colour}{regime}{RESET}")
    print()

    strategy_map = {
        REGIME_TRENDING:  "FVG Strategy  OR  Breakout Strategy",
        REGIME_RANGING:   "Reversal Strategy",
        REGIME_VOLATILE:  "⛔ NO TRADING  — alert only",
        REGIME_UNCLEAR:   "⛔ NO TRADING  — wait for clearer regime",
    }
    print(f"  Strategy   : {strategy_map.get(regime, '—')}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Shark Algo — Market Regime Detector")
    parser.add_argument("--url",   default=NODE_URL, help="Node server base URL")
    parser.add_argument("--limit", type=int, default=300, help="Number of 15m candles to fetch")
    parser.add_argument("--json",  action="store_true", help="Output raw JSON instead of formatted")
    args = parser.parse_args()

    try:
        result = detect_current_regime(node_url=args.url, limit=args.limit)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_regime_report(result)
    except requests.ConnectionError:
        print(f"\n❌  Cannot connect to Node server at {args.url}")
        print("   Start the server first:  node server.mjs\n")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌  Error: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
