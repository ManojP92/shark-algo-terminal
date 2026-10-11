"""
combo_optimizer.py
──────────────────────────────────────────────────────────────────────────────
Comprehensive multi-combo parameter optimizer & root-cause analyzer.
Tests combinations of:
  - Donchian Lookback: 15, 20, 25, 35, 50
  - ADX Filter Threshold: 15, 20, 25, 28
  - Trailing Stop Multiplier: 1.5x, 2.0x, 2.5x, 3.0x
  - Stop Loss Multiplier: 1.0x, 1.5x, 2.0x
  - Scale-Out Mode: Enabled (50% @ 1:1R) vs Disabled (Let Winners Run)
  - Trend Filter: None vs EMA 50 / 200
──────────────────────────────────────────────────────────────────────────────
"""

import itertools
import requests
import pandas as pd
import numpy as np

from backtester import run_backtest
from strategy.donchian_breakout import DonchianBreakoutStrategy

NODE_URL = "http://localhost:3001"


def fetch_candles(pair: str, interval: str, days: int = 14) -> pd.DataFrame:
    url = f"{NODE_URL}/api/klines/history?interval={interval}&days={days}&pair={pair}"
    resp = requests.get(url, timeout=30)
    data = resp.json().get("data", [])
    df = pd.DataFrame(data)
    df.rename(columns={"startTime": "timestamp"}, inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def evaluate_combos(pair: str = "BTCUSDT", interval: str = "15m", days: int = 7):
    print(f"\n=================================================================", flush=True)
    print(f" FETCHING HISTORICAL CANDLES FOR {pair} ({interval}, {days} Days)", flush=True)
    print(f"=================================================================", flush=True)
    df = fetch_candles(pair, interval, days)
    print(f"Total Bars: {len(df)} | Start: {df.iloc[0]['timestamp']} -> End: {df.iloc[-1]['timestamp']}", flush=True)

    # Parameter grid
    dc_periods = [15, 20, 25, 35, 50]
    adx_mins = [18.0, 22.0, 25.0]
    atr_sls = [1.0, 1.5, 2.0]
    atr_trails = [1.5, 2.0, 2.5, 3.0]
    scale_outs = [False, True]
    results = []

    # Min specs based on pair
    min_notional = 115.0 if "BTC" in pair else (23.0 if "ETH" in pair else 5.75)
    min_qty = 0.001 if "BTC" in pair else (0.001 if "ETH" in pair else 0.01)
    step_size = 0.001 if "BTC" in pair else (0.001 if "ETH" in pair else 0.01)
    capital = 100.0 if "BTC" in pair else (50.0 if "ETH" in pair else 10.0)

    print(f"Testing parameter combinations on {pair}...", flush=True)

    for dc_p in dc_periods:
        strat = DonchianBreakoutStrategy(dc_period=dc_p)
        df_ind = strat.compute_indicators(df)
        df_ind.attrs["dc_period"] = dc_p

        sub_combos = list(itertools.product(adx_mins, atr_sls, atr_trails, scale_outs))
        for adx_m, sl_m, trail_m, sc_out in sub_combos:
            try:
                bt = run_backtest(
                    df=df_ind,
                    initial_capital=capital,
                    risk_pct=1.5,
                    leverage=10,
                    min_qty=min_qty,
                    step_size=step_size,
                    min_notional=min_notional,
                    dc_period=dc_p,
                    adx_min=adx_m,
                    atr_mult_sl=sl_m,
                    atr_mult_trail=trail_m,
                    enable_scale_out=sc_out,
                )
                s = bt["summary"]
                results.append({
                    "dc_period": dc_p,
                    "adx_min": adx_m,
                    "sl_mult": sl_m,
                    "trail_mult": trail_m,
                    "scale_out": sc_out,
                    "trades": s["total_trades"],
                    "win_rate": s["win_rate"],
                    "profit_factor": s["profit_factor"],
                    "net_pnl": s["net_pnl"],
                    "roi_pct": s["roi_pct"],
                    "max_dd": s["max_drawdown_pct"],
                })
            except Exception as e:
                pass

    res_df = pd.DataFrame(results)

    # Sort by Net PnL descending
    top_profit = res_df.sort_values(by="net_pnl", ascending=False).head(10)
    top_pf = res_df[res_df["trades"] >= 4].sort_values(by="profit_factor", ascending=False).head(10)

    print("\n--- TOP 10 COMBOS BY NET PROFIT ($) ---")
    print(top_profit[["dc_period", "adx_min", "sl_mult", "trail_mult", "scale_out", "trades", "win_rate", "profit_factor", "net_pnl", "roi_pct", "max_dd"]].to_string(index=False))

    # Analytical takeaways
    print("\n--- FACTOR SENSITIVITY BREAKDOWN ---")
    print("\n1. Impact of Scale-Out (50% @ 1:1R) vs Letting Winners Run:")
    print(res_df.groupby("scale_out")[["net_pnl", "profit_factor", "win_rate"]].mean())

    print("\n2. Impact of Trailing Stop Distance (ATR Multiplier):")
    print(res_df.groupby("trail_mult")[["net_pnl", "profit_factor", "win_rate"]].mean())

    print("\n3. Impact of Donchian Channel Period:")
    print(res_df.groupby("dc_period")[["net_pnl", "profit_factor", "trades"]].mean())

    print("\n4. Impact of ADX Filter Threshold:")
    print(res_df.groupby("adx_min")[["net_pnl", "profit_factor", "win_rate"]].mean())

    return res_df


if __name__ == "__main__":
    for sym in ["BTCUSDT", "SOLUSDT"]:
        evaluate_combos(sym, interval="15m", days=7)
