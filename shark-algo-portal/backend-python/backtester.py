"""
backtester.py
──────────────────────────────────────────────────────────────────────────────
Institutional Backtesting & Monte Carlo Engine for Donchian Breakout Strategy.

Features:
  1. Bar-by-bar historical event simulation with intra-bar SL execution
  2. Exchange-accurate contract constraints (minQty, stepSize, minNotional)
  3. Dynamic capital compounding & risk-based lot sizing
  4. 1:1 R partial scale-out and ratcheting trailing stop
  5. Realistic exchange fee modeling (e.g. 0.05% taker fee)
  6. Monte Carlo bootstrap simulation (500-1000 iterations)
     - Probability of Profit
     - Value-at-Risk (P5 / P95 confidence intervals)
     - Max Drawdown distribution
     - Multi-path equity cone curves for charting
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

from strategy.donchian_breakout import (
    DonchianBreakoutStrategy,
    TrailingState,
    compute_donchian,
    compute_atr,
    compute_adx,
)


@dataclass
class BacktestTrade:
    id: str
    entry_time: str
    exit_time: str
    side: str
    entry_price: float
    exit_price: float
    qty: float
    gross_pnl: float
    fee: float
    net_pnl: float
    pnl_pct: float
    exit_reason: str
    equity_after: float


def run_backtest(
    df: pd.DataFrame,
    initial_capital: float = 100.0,
    risk_pct: float = 1.0,
    leverage: int = 10,
    min_qty: float = 0.001,
    step_size: float = 0.001,
    min_notional: float = 115.0,
    dc_period: int = 25,
    adx_min: float = 20.0,
    atr_mult_sl: float = 1.5,
    atr_mult_trail: float = 3.0,
    fee_pct: float = 0.05,        # 0.05% taker fee
    enable_scale_out: bool = True,
) -> Dict[str, Any]:
    """
    Run bar-by-bar backtest of Donchian Breakout Strategy.
    """
    if len(df) < dc_period + 14:
        raise ValueError(f"Insufficient candles: {len(df)} bars provided, need at least {dc_period + 14}")

    strat = DonchianBreakoutStrategy(
        dc_period=dc_period,
        adx_min=adx_min,
        atr_mult_sl=atr_mult_sl,
        atr_mult_trail=atr_mult_trail,
    )
    df = strat.compute_indicators(df)

    equity = float(initial_capital)
    peak_equity = equity
    trades: List[Dict[str, Any]] = []
    equity_curve: List[Dict[str, Any]] = []

    # Position state
    in_pos = False
    pos_side = ""
    pos_qty = 0.0
    pos_entry = 0.0
    pos_sl = 0.0
    pos_trail_state: Optional[TrailingState] = None
    pos_scaled_out = False
    pos_entry_time = ""
    trade_id_counter = 1

    # Record starting point
    first_time = str(df.iloc[0].get("timestamp", ""))
    equity_curve.append({
        "time": first_time,
        "equity": round(equity, 2),
        "drawdown_pct": 0.0,
    })

    # Warmup loop: start after indicators are valid
    start_idx = max(dc_period, 15)

    for i in range(start_idx, len(df)):
        bar = df.iloc[i]
        prev_bar = df.iloc[i - 1]

        timestamp = str(bar.get("timestamp", ""))
        o = float(bar["open"])
        h = float(bar["high"])
        l = float(bar["low"])
        c = float(bar["close"])

        # Prior bar indicators for clean no-lookahead signal
        prev_dc_up = float(prev_bar["dc_upper"])
        prev_dc_lo = float(prev_bar["dc_lower"])
        prev_atr = float(prev_bar["atr"])
        prev_adx = float(prev_bar["adx"])
        prev_close = float(prev_bar["close"])

        cur_atr = float(bar["atr"]) if not math.isnan(bar["atr"]) else prev_atr

        # ── 1. Check Exit for Open Position ──────────────────────────────────
        if in_pos:
            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            # Intra-bar stop check
            if pos_side == "LONG":
                if l <= pos_sl:
                    exit_triggered = True
                    exit_price = min(o, pos_sl)  # gap protection
                    exit_reason = "Stop Loss Hit"
            elif pos_side == "SHORT":
                if h >= pos_sl:
                    exit_triggered = True
                    exit_price = max(o, pos_sl)
                    exit_reason = "Stop Loss Hit"

            # Optional 50% scale-out at 1:1 R
            if in_pos and not exit_triggered and enable_scale_out and not pos_scaled_out:
                risk_dist = abs(pos_entry - pos_sl)
                scale_hit = (c >= pos_entry + risk_dist) if pos_side == "LONG" else (c <= pos_entry - risk_dist)
                if scale_hit:
                    scale_qty = round(pos_qty * 0.5, 4)
                    if scale_qty >= min_qty:
                        partial_gross = (c - pos_entry) * scale_qty if pos_side == "LONG" else (pos_entry - c) * scale_qty
                        fee = (scale_qty * c) * (fee_pct / 100.0)
                        partial_net = partial_gross - fee
                        equity += partial_net
                        pos_qty -= scale_qty
                        pos_scaled_out = True

            # Trailing stop update on bar close
            if in_pos and not exit_triggered and pos_trail_state:
                pos_trail_state = strat.update_trailing_stop(pos_trail_state, c, cur_atr)
                pos_sl = pos_trail_state.trail_sl

                # Check if bar close violated updated trailing stop
                if pos_side == "LONG" and c <= pos_sl:
                    exit_triggered = True
                    exit_price = c
                    exit_reason = "Trailing Stop Hit"
                elif pos_side == "SHORT" and c >= pos_sl:
                    exit_triggered = True
                    exit_price = c
                    exit_reason = "Trailing Stop Hit"

            # Execute full close
            if exit_triggered:
                gross_pnl = (exit_price - pos_entry) * pos_qty if pos_side == "LONG" else (pos_entry - exit_price) * pos_qty
                exit_notional = pos_qty * exit_price
                entry_notional = pos_qty * pos_entry
                fee = (entry_notional + exit_notional) * (fee_pct / 100.0)
                net_pnl = gross_pnl - fee
                pnl_pct = (net_pnl / (entry_notional / leverage)) * 100 if entry_notional > 0 else 0.0

                equity += net_pnl
                in_pos = False

                trades.append({
                    "id": f"BT-{trade_id_counter:03d}",
                    "entry_time": pos_entry_time,
                    "exit_time": timestamp,
                    "side": pos_side,
                    "entry_price": round(pos_entry, 2),
                    "exit_price": round(exit_price, 2),
                    "qty": round(pos_qty, 4),
                    "gross_pnl": round(gross_pnl, 2),
                    "fee": round(fee, 2),
                    "net_pnl": round(net_pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "exit_reason": exit_reason,
                    "equity_after": round(equity, 2),
                })
                trade_id_counter += 1

        # ── 2. Check Entry if Flat ───────────────────────────────────────────
        if not in_pos and not math.isnan(prev_dc_up) and not math.isnan(prev_atr) and not math.isnan(prev_adx):
            sig_side = ""
            if prev_close > prev_dc_up and prev_adx >= adx_min:
                sig_side = "LONG"
            elif prev_close < prev_dc_lo and prev_adx >= adx_min:
                sig_side = "SHORT"

            if sig_side:
                # Dynamic Position Sizing based on risk
                risk_amount = equity * (risk_pct / 100.0)
                sl_dist = atr_mult_sl * prev_atr

                if sl_dist > 0:
                    raw_qty = risk_amount / sl_dist
                    # Quantize to step size
                    steps = round(raw_qty / step_size)
                    sized_qty = max(min_qty, round(steps * step_size, 4))

                    # Check exchange notional threshold
                    notional = sized_qty * o
                    if notional < min_notional:
                        sized_qty = round(math.ceil(min_notional / o / step_size) * step_size, 4)
                        notional = sized_qty * o

                    # Cap at available margin buffer (max 90% equity used for margin)
                    margin_req = notional / leverage
                    max_allowed_margin = equity * 0.90
                    if margin_req > max_allowed_margin and equity > 2:
                        max_notional = max_allowed_margin * leverage
                        sized_qty = max(min_qty, round(math.floor(max_notional / o / step_size) * step_size, 4))
                        notional = sized_qty * o

                    if equity >= (notional / leverage):
                        in_pos = True
                        pos_side = sig_side
                        pos_entry = o
                        pos_qty = sized_qty
                        pos_entry_time = timestamp
                        pos_scaled_out = False

                        if sig_side == "LONG":
                            pos_sl = o - sl_dist
                            initial_trail = o - (atr_mult_trail * prev_atr)
                        else:
                            pos_sl = o + sl_dist
                            initial_trail = o + (atr_mult_trail * prev_atr)

                        pos_trail_state = TrailingState(
                            side=sig_side,
                            entry=o,
                            best_price=o,
                            trail_sl=initial_trail,
                            atr_mult=atr_mult_trail,
                        )

        # ── 3. Record Equity Curve Point ─────────────────────────────────────
        peak_equity = max(peak_equity, equity)
        dd_pct = ((peak_equity - equity) / peak_equity) * 100 if peak_equity > 0 else 0.0

        # Sample equity curve every 4 bars (to keep payload concise) or at end
        if i % 4 == 0 or i == len(df) - 1:
            equity_curve.append({
                "time": timestamp,
                "equity": round(equity, 2),
                "drawdown_pct": round(dd_pct, 2),
            })

    # Close any open trade at final bar close for clean reconciliation
    if in_pos:
        last_bar = df.iloc[-1]
        exit_price = float(last_bar["close"])
        gross_pnl = (exit_price - pos_entry) * pos_qty if pos_side == "LONG" else (pos_entry - exit_price) * pos_qty
        fee = (pos_qty * exit_price + pos_qty * pos_entry) * (fee_pct / 100.0)
        net_pnl = gross_pnl - fee
        equity += net_pnl

        trades.append({
            "id": f"BT-{trade_id_counter:03d}",
            "entry_time": pos_entry_time,
            "exit_time": str(last_bar.get("timestamp", "")),
            "side": pos_side,
            "entry_price": round(pos_entry, 2),
            "exit_price": round(exit_price, 2),
            "qty": round(pos_qty, 4),
            "gross_pnl": round(gross_pnl, 2),
            "fee": round(fee, 2),
            "net_pnl": round(net_pnl, 2),
            "pnl_pct": round((net_pnl / (pos_qty * pos_entry / leverage)) * 100, 2),
            "exit_reason": "End of Backtest Period",
            "equity_after": round(equity, 2),
        })

    # ── Performance Summary Metrics ──────────────────────────────────────────
    total_trades = len(trades)
    winning_trades = [t for t in trades if t["net_pnl"] > 0]
    losing_trades = [t for t in trades if t["net_pnl"] < 0]

    wins_count = len(winning_trades)
    loss_count = len(losing_trades)
    win_rate = (wins_count / total_trades * 100) if total_trades > 0 else 0.0

    gross_profit = sum(t["net_pnl"] for t in winning_trades)
    gross_loss = abs(sum(t["net_pnl"] for t in losing_trades))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)

    net_pnl = equity - initial_capital
    roi_pct = (net_pnl / initial_capital) * 100

    max_dd_pct = max([p["drawdown_pct"] for p in equity_curve]) if equity_curve else 0.0

    trade_returns = [t["net_pnl"] for t in trades]

    return {
        "summary": {
            "initial_capital": round(initial_capital, 2),
            "final_equity": round(equity, 2),
            "net_pnl": round(net_pnl, 2),
            "roi_pct": round(roi_pct, 2),
            "total_trades": total_trades,
            "winning_trades": wins_count,
            "losing_trades": loss_count,
            "win_rate": round(win_rate, 1),
            "profit_factor": profit_factor,
            "max_drawdown_pct": round(max_dd_pct, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "avg_trade_pnl": round(net_pnl / total_trades, 2) if total_trades > 0 else 0.0,
            "best_trade": round(max(trade_returns), 2) if trade_returns else 0.0,
            "worst_trade": round(min(trade_returns), 2) if trade_returns else 0.0,
        },
        "trades": trades,
        "equity_curve": equity_curve,
    }


def run_monte_carlo(
    trade_returns: List[float],
    initial_capital: float = 100.0,
    num_simulations: int = 500,
    num_trades_projection: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Monte Carlo Bootstrap Resampling:
    Resamples trade outcomes across `num_simulations` iterations to compute
    confidence intervals (5th, 50th, 95th percentiles) and drawdown risk.
    """
    if not trade_returns:
        return {
            "simulations": num_simulations,
            "prob_profit": 50.0,
            "median_equity": initial_capital,
            "p5_equity": initial_capital,
            "p95_equity": initial_capital,
            "median_max_dd": 0.0,
            "p95_max_dd": 0.0,
            "sample_paths": [],
        }

    n_trades = num_trades_projection or len(trade_returns)
    final_equities: List[float] = []
    max_drawdowns: List[float] = []
    simulated_paths: List[List[float]] = []

    for sim_idx in range(num_simulations):
        # Sample trades with replacement
        sampled = random.choices(trade_returns, k=n_trades)
        equity = initial_capital
        peak = equity
        max_dd = 0.0
        path = [round(equity, 2)]

        for pnl in sampled:
            equity = max(0.5, equity + pnl)  # clamp to avoid total 0
            peak = max(peak, equity)
            dd = ((peak - equity) / peak) * 100
            max_dd = max(max_dd, dd)
            path.append(round(equity, 2))

        final_equities.append(equity)
        max_drawdowns.append(max_dd)
        simulated_paths.append(path)

    final_equities.sort()
    max_drawdowns.sort()

    p5_idx = int(0.05 * num_simulations)
    p50_idx = int(0.50 * num_simulations)
    p95_idx = int(0.95 * num_simulations)

    p5_equity = final_equities[p5_idx]
    median_equity = final_equities[p50_idx]
    p95_equity = final_equities[p95_idx]

    median_dd = max_drawdowns[p50_idx]
    p95_dd = max_drawdowns[p95_idx]

    profitable_count = sum(1 for eq in final_equities if eq >= initial_capital)
    prob_profit = (profitable_count / num_simulations) * 100

    # Pick 8 representative paths for rendering in frontend chart:
    # 5th percentile path, Median path, 95th percentile path, and 5 random paths
    # Sort paths by their final equity
    indexed_paths = sorted(enumerate(simulated_paths), key=lambda x: x[1][-1])
    sample_indices = [
        p5_idx,
        int(0.25 * num_simulations),
        p50_idx,
        int(0.75 * num_simulations),
        p95_idx,
    ]
    # Add a few random ones
    for _ in range(3):
        sample_indices.append(random.randint(0, num_simulations - 1))

    sample_paths = [
        {
            "id": f"Path-{idx}",
            "is_median": (idx == p50_idx),
            "is_p5": (idx == p5_idx),
            "is_p95": (idx == p95_idx),
            "data": indexed_paths[min(idx, len(indexed_paths) - 1)][1],
        }
        for idx in set(sample_indices)
    ]

    return {
        "num_simulations": num_simulations,
        "prob_profit": round(prob_profit, 1),
        "median_equity": round(median_equity, 2),
        "p5_equity": round(p5_equity, 2),
        "p95_equity": round(p95_equity, 2),
        "median_max_dd": round(median_dd, 1),
        "p95_max_dd": round(p95_dd, 1),
        "sample_paths": sample_paths,
    }
