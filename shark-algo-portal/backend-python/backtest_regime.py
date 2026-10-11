"""
backtest_regime.py
──────────────────────────────────────────────────────────────────────────────
Phase 2 — 30-Day Regime Backtest

Fetches 30 days of 15m BTCUSDT klines via the Node server (paginated),
runs the regime classifier on every closed bar, and prints:

  1. Regime distribution (% of bars in each regime)
  2. Average consecutive bar runs per regime
  3. Top-5 longest regime streaks
  4. Per-day breakdown (regime that dominated each day)
  5. Indicator stats (ADX, Choppiness, ATR-ratio averages by regime)

Usage:
  # Start the Node server first:
  #   cd backend-node && node server.mjs

  python backtest_regime.py
  python backtest_regime.py --days 7      # quick 7-day run
  python backtest_regime.py --url http://localhost:3001
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import timezone

import numpy as np
import pandas as pd
import requests

# ── Import from same package ──────────────────────────────────────────────────
try:
    from regime_detector import (
        fetch_klines_history,
        compute_all_indicators,
        REGIME_TRENDING, REGIME_RANGING, REGIME_VOLATILE, REGIME_UNCLEAR,
        NODE_URL,
    )
except ImportError:
    sys.path.insert(0, ".")
    from regime_detector import (
        fetch_klines_history,
        compute_all_indicators,
        REGIME_TRENDING, REGIME_RANGING, REGIME_VOLATILE, REGIME_UNCLEAR,
        NODE_URL,
    )

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[32m"
BLUE   = "\033[34m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

REGIME_COLOUR = {
    REGIME_TRENDING:  GREEN,
    REGIME_RANGING:   BLUE,
    REGIME_VOLATILE:  RED,
    REGIME_UNCLEAR:   YELLOW,
}

ALL_REGIMES = [REGIME_TRENDING, REGIME_RANGING, REGIME_VOLATILE, REGIME_UNCLEAR]


# ──────────────────────────────────────────────────────────────────────────────
#  Streak analysis helpers
# ──────────────────────────────────────────────────────────────────────────────

def compute_streaks(regimes: list[str]) -> list[tuple[str, int]]:
    """Return list of (regime, length) for every consecutive run."""
    if not regimes:
        return []
    streaks, cur_regime, cur_len = [], regimes[0], 1
    for r in regimes[1:]:
        if r == cur_regime:
            cur_len += 1
        else:
            streaks.append((cur_regime, cur_len))
            cur_regime, cur_len = r, 1
    streaks.append((cur_regime, cur_len))
    return streaks


def avg_run_length(streaks: list[tuple[str, int]], regime: str) -> float:
    runs = [l for r, l in streaks if r == regime]
    return sum(runs) / len(runs) if runs else 0.0


# ──────────────────────────────────────────────────────────────────────────────
#  Formatting helpers
# ──────────────────────────────────────────────────────────────────────────────

def bar(pct: float, width: int = 30) -> str:
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def regime_row(regime: str, count: int, total: int, avg_run: float) -> str:
    pct   = 100 * count / total if total else 0
    col   = REGIME_COLOUR.get(regime, "")
    barchart = bar(pct)
    return (
        f"  {col}{regime:<10}{RESET}  {barchart}  {pct:5.1f}%  "
        f"({count:5d} bars)  avg run: {avg_run:.1f} bars ({avg_run * 15 / 60:.1f}h)"
    )


# ──────────────────────────────────────────────────────────────────────────────
#  Main backtest
# ──────────────────────────────────────────────────────────────────────────────

def run_backtest(days: int = 30, node_url: str = NODE_URL) -> None:
    # ── 1. Fetch data ──────────────────────────────────────────────────────────
    print()
    print(f"{BOLD}{CYAN}╔══════════════════════════════════════════════════════════╗")
    print(f"║     SHARK ALGO — REGIME BACKTEST  ({days}d × 15m)              ║")
    print(f"╚══════════════════════════════════════════════════════════╝{RESET}")
    print()

    try:
        df = fetch_klines_history(interval="15m", days=days, node_url=node_url)
    except requests.ConnectionError:
        print(f"{RED}❌  Cannot connect to Node server at {node_url}{RESET}")
        print("   Start it first:  cd backend-node && node server.mjs")
        sys.exit(1)

    # ── 2. Compute indicators on all bars ──────────────────────────────────────
    print("  Computing indicators …", end=" ", flush=True)
    df = compute_all_indicators(df)
    # Drop bars where indicators aren't ready yet (NaN regime)
    valid = df.dropna(subset=["adx", "chop", "atr_ratio"]).copy()
    print(f"done. {len(valid)} valid bars ({len(df) - len(valid)} warmup bars excluded)")
    print()

    if len(valid) == 0:
        print(f"{RED}❌  Not enough data. Fetch more candles (increase --days).{RESET}")
        sys.exit(1)

    regimes       = valid["regime"].tolist()
    total         = len(regimes)
    counts        = Counter(regimes)
    streaks       = compute_streaks(regimes)

    # ── 3. Regime distribution ─────────────────────────────────────────────────
    date_range = (
        f"{valid['timestamp'].iloc[0].strftime('%Y-%m-%d')} → "
        f"{valid['timestamp'].iloc[-1].strftime('%Y-%m-%d')}"
    )
    print(f"{BOLD}  Regime Distribution  |  {date_range}  |  {total} bars{RESET}")
    print(f"  {'─' * 70}")
    for regime in ALL_REGIMES:
        count   = counts.get(regime, 0)
        avg_run = avg_run_length(streaks, regime)
        print(regime_row(regime, count, total, avg_run))
    print()

    # ── 4. Top-5 longest streaks ───────────────────────────────────────────────
    print(f"{BOLD}  Top-5 Longest Regime Streaks{RESET}")
    print(f"  {'─' * 50}")
    top5 = sorted(streaks, key=lambda x: x[1], reverse=True)[:5]
    for rank, (regime, length) in enumerate(top5, 1):
        col = REGIME_COLOUR.get(regime, "")
        hours = length * 15 / 60
        print(f"  #{rank}  {col}{regime:<10}{RESET}  {length:4d} bars  ({hours:.1f}h)")
    print()

    # ── 5. Indicator statistics by regime ──────────────────────────────────────
    print(f"{BOLD}  Indicator Averages by Regime{RESET}")
    print(f"  {'─' * 70}")
    header = f"  {'Regime':<12}  {'ADX':>7}  {'+DI':>7}  {'-DI':>7}  {'Chop':>7}  {'ATR-ratio':>10}  {'ATR($)':>9}"
    print(header)
    print(f"  {'─' * 70}")
    for regime in ALL_REGIMES:
        sub = valid[valid["regime"] == regime]
        if sub.empty:
            print(f"  {regime:<12}  {'—':>7}  {'—':>7}  {'—':>7}  {'—':>7}  {'—':>10}  {'—':>9}")
            continue
        col = REGIME_COLOUR.get(regime, "")
        print(
            f"  {col}{regime:<12}{RESET}"
            f"  {sub['adx'].mean():7.2f}"
            f"  {sub['plus_di'].mean():7.2f}"
            f"  {sub['minus_di'].mean():7.2f}"
            f"  {sub['chop'].mean():7.2f}"
            f"  {sub['atr_ratio'].mean():10.3f}"
            f"  {sub['atr'].mean():9.2f}"
        )
    print()

    # ── 6. Daily dominant regime breakdown ─────────────────────────────────────
    print(f"{BOLD}  Daily Dominant Regime (last 10 days){RESET}")
    print(f"  {'─' * 50}")
    valid["date"] = valid["timestamp"].dt.date
    daily = valid.groupby("date")["regime"].agg(lambda x: x.value_counts().idxmax())
    for date, dominant in list(daily.items())[-10:]:
        col = REGIME_COLOUR.get(dominant, "")
        tradeable = dominant in (REGIME_TRENDING, REGIME_RANGING)
        flag = "✅" if tradeable else "⛔"
        print(f"  {flag}  {date}  →  {col}{dominant}{RESET}")
    print()

    # ── 7. Tradeability summary ────────────────────────────────────────────────
    tradeable_bars   = counts.get(REGIME_TRENDING, 0) + counts.get(REGIME_RANGING, 0)
    untradeable_bars = total - tradeable_bars
    tradeable_pct    = 100 * tradeable_bars / total if total else 0

    print(f"{BOLD}  Tradeability Summary{RESET}")
    print(f"  {'─' * 40}")
    print(f"  Tradeable   (TRENDING + RANGING) : {GREEN}{tradeable_bars:5d} bars  ({tradeable_pct:.1f}%){RESET}")
    print(f"  Untradeable (VOLATILE + UNCLEAR)  : {YELLOW}{untradeable_bars:5d} bars  ({100 - tradeable_pct:.1f}%){RESET}")
    print()

    # ── 8. Regime transition matrix ────────────────────────────────────────────
    print(f"{BOLD}  Regime Transition Matrix (row → col = next bar){RESET}")
    print(f"  {'─' * 60}")
    regime_list = regimes
    from_list, to_list = regime_list[:-1], regime_list[1:]
    transitions: dict[str, Counter] = {r: Counter() for r in ALL_REGIMES}
    for frm, to in zip(from_list, to_list):
        transitions[frm][to] += 1

    col_w = 12
    print(f"  {'FROM \\ TO':<12}" + "".join(f"{r[:10]:>{col_w}}" for r in ALL_REGIMES))
    for frm in ALL_REGIMES:
        row_total = sum(transitions[frm].values()) or 1
        row_str = f"  {REGIME_COLOUR.get(frm,'')}{frm:<12}{RESET}"
        for to in ALL_REGIMES:
            pct = 100 * transitions[frm][to] / row_total
            row_str += f"{pct:>{col_w}.1f}%"
        print(row_str)
    print()
    print(f"  {GREEN}✅ Backtest complete — {total} bars analysed over {days} days{RESET}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Shark Algo — Regime Backtest")
    parser.add_argument("--days", type=int, default=30, help="Days of history to fetch")
    parser.add_argument("--url",  default=NODE_URL,  help="Node server base URL")
    args = parser.parse_args()
    run_backtest(days=args.days, node_url=args.url)


if __name__ == "__main__":
    main()
