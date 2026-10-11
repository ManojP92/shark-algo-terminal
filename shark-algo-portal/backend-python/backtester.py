"""
backtester.py
──────────────────────────────────────────────────────────────────────────────
Institutional Multi-Strategy Backtesting & Monte Carlo Engine.

Supported Strategies:
  1. DONCHIAN (Donchian Channel 20 + ADX 22 Momentum Breakout)
  2. BOLLINGER_RSI (Bollinger Bands 20, 2.0 + RSI 14 Mean Reversion with Midline TP)
  3. SUPERTREND (Supertrend 10, 3.0 + EMA Trend Momentum)
  4. REGIME_ADAPTIVE (Multi-Regime Hybrid: Trend Breakout in Trends, Mean Reversion in Ranges)

Features:
  • Bar-by-bar historical simulation with intra-bar SL & TP execution
  • Exchange-accurate contract constraints (minQty, stepSize, minNotional)
  • Compounding equity calculation & fee modeling (0.05% taker)
  • 500-run Monte Carlo Bootstrap Resampling (P5, P50, P95 cones & VaR)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

from strategy import (
    get_strategy,
    DonchianBreakoutStrategy,
    BollingerRsiStrategy,
    SupertrendMomentumStrategy,
    RegimeAdaptiveStrategy,
    TrailingState,
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
    strategy_name: str = "DONCHIAN",
    initial_capital: float = 100.0,
    risk_pct: float = 1.0,
    leverage: int = 10,
    min_qty: float = 0.001,
    step_size: float = 0.001,
    min_notional: float = 115.0,
    dc_period: int = 20,
    adx_min: float = 22.0,
    atr_mult_sl: float = 1.2,
    atr_mult_trail: float = 3.0,
    fee_pct: float = 0.05,        # 0.05% taker fee
    enable_scale_out: bool = False,
) -> Dict[str, Any]:
    """
    Run bar-by-bar backtest of selected strategy over historical candles.
    """
    strat_key = (strategy_name or "DONCHIAN").strip().upper()
    if len(df) < dc_period + 20:
        raise ValueError(f"Insufficient candles: {len(df)} bars provided, need at least {dc_period + 20}")

    strat = get_strategy(
        strat_key,
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
    pos_tp = 0.0
    pos_strat_type = ""
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

    # Extract price arrays for high-speed indexing
    timestamps = [str(t) for t in df["timestamp"].values]
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    atrs = df["atr"].values if "atr" in df.columns else np.full(len(df), 1.0)
    adxs = df["adx"].values if "adx" in df.columns else np.full(len(df), 25.0)

    # Strategy-specific arrays
    dc_ups = df["dc_upper"].values if "dc_upper" in df.columns else None
    dc_los = df["dc_lower"].values if "dc_lower" in df.columns else None

    bb_mids = df["bb_mid"].values if "bb_mid" in df.columns else None
    bb_ups = df["bb_upper"].values if "bb_upper" in df.columns else None
    bb_los = df["bb_lower"].values if "bb_lower" in df.columns else None
    rsis = df["rsi"].values if "rsi" in df.columns else None

    sts = df["st"].values if "st" in df.columns else None
    st_dirs = df["st_dir"].values if "st_dir" in df.columns else None
    emas = df["ema_trend"].values if "ema_trend" in df.columns else None

    start_idx = max(dc_period, 30)

    for i in range(start_idx, len(df)):
        timestamp = timestamps[i]
        o = float(opens[i])
        h = float(highs[i])
        l = float(lows[i])
        c = float(closes[i])

        prev_atr = float(atrs[i - 1]) if not math.isnan(atrs[i - 1]) else 1.0
        prev_adx = float(adxs[i - 1]) if not math.isnan(adxs[i - 1]) else 20.0
        prev_close = float(closes[i - 1])
        cur_atr = float(atrs[i]) if not math.isnan(atrs[i]) else prev_atr

        # ── 1. Check Exit for Open Position ──────────────────────────────────
        if in_pos:
            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            # Check Intra-bar Stop Loss
            if pos_side == "LONG":
                if l <= pos_sl:
                    exit_triggered = True
                    exit_price = min(o, pos_sl)
                    exit_reason = "Stop Loss Hit"
            elif pos_side == "SHORT":
                if h >= pos_sl:
                    exit_triggered = True
                    exit_price = max(o, pos_sl)
                    exit_reason = "Stop Loss Hit"

            # Check Take Profit for Mean Reversion trades (Bollinger Midline)
            if not exit_triggered and pos_tp > 0:
                if pos_side == "LONG" and h >= pos_tp:
                    exit_triggered = True
                    exit_price = max(o, pos_tp)
                    exit_reason = "Take Profit (BB Midline Reversion)"
                elif pos_side == "SHORT" and l <= pos_tp:
                    exit_triggered = True
                    exit_price = min(o, pos_tp)
                    exit_reason = "Take Profit (BB Midline Reversion)"

            # Check Supertrend reversal
            if not exit_triggered and strat_key in ("SUPERTREND", "SUPERTREND_MOMENTUM") and st_dirs is not None:
                cur_st_dir = int(st_dirs[i - 1])
                if (pos_side == "LONG" and cur_st_dir == -1) or (pos_side == "SHORT" and cur_st_dir == 1):
                    exit_triggered = True
                    exit_price = o
                    exit_reason = "Supertrend Reversal Flip"

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
        if not in_pos and not math.isnan(prev_atr):
            sig_side = ""
            entry_tp = 0.0
            trade_sub_type = strat_key

            # ── A. Donchian Channel Breakout
            if strat_key in ("DONCHIAN", "DONCHIAN_BREAKOUT") and dc_ups is not None and dc_los is not None:
                if prev_close > dc_ups[i - 1] and prev_adx >= adx_min:
                    sig_side = "LONG"
                elif prev_close < dc_los[i - 1] and prev_adx >= adx_min:
                    sig_side = "SHORT"

            # ── B. Bollinger + RSI Mean Reversion
            elif strat_key in ("BOLLINGER_RSI", "BOLLINGER_REVERSION") and bb_ups is not None and rsis is not None:
                if prev_close <= (bb_los[i - 1] * 1.002) and rsis[i - 1] <= 38.0 and prev_adx < 28.0:
                    sig_side = "LONG"
                    entry_tp = float(bb_mids[i - 1])
                elif prev_close >= (bb_ups[i - 1] * 0.998) and rsis[i - 1] >= 62.0 and prev_adx < 28.0:
                    sig_side = "SHORT"
                    entry_tp = float(bb_mids[i - 1])

            # ── C. Supertrend Momentum
            elif strat_key in ("SUPERTREND", "SUPERTREND_MOMENTUM") and st_dirs is not None:
                prev_dir = int(st_dirs[i - 1])
                prev2_dir = int(st_dirs[i - 2])
                if prev_dir == 1 and prev2_dir != 1 and prev_adx >= 18.0:
                    sig_side = "LONG"
                elif prev_dir == -1 and prev2_dir != -1 and prev_adx >= 18.0:
                    sig_side = "SHORT"

            # ── D. Regime-Adaptive Hybrid
            elif strat_key in ("REGIME_ADAPTIVE", "ADAPTIVE_HYBRID"):
                # Regime 1: Trending
                if prev_adx >= 22.0 and dc_ups is not None:
                    if prev_close > dc_ups[i - 1]:
                        sig_side = "LONG"
                        trade_sub_type = "TREND_BREAKOUT"
                    elif prev_close < dc_los[i - 1]:
                        sig_side = "SHORT"
                        trade_sub_type = "TREND_BREAKOUT"
                # Regime 2: Ranging
                elif prev_adx <= 20.0 and bb_ups is not None and rsis is not None:
                    if prev_close <= (bb_los[i - 1] * 1.002) and rsis[i - 1] <= 38.0:
                        sig_side = "LONG"
                        entry_tp = float(bb_mids[i - 1])
                        trade_sub_type = "RANGE_REVERSION"
                    elif prev_close >= (bb_ups[i - 1] * 0.998) and rsis[i - 1] >= 62.0:
                        sig_side = "SHORT"
                        entry_tp = float(bb_mids[i - 1])
                        trade_sub_type = "RANGE_REVERSION"

            # ── Sizing & Execution
            if sig_side:
                risk_amount = equity * (risk_pct / 100.0)
                sl_dist = atr_mult_sl * prev_atr

                if sl_dist > 0:
                    raw_qty = risk_amount / sl_dist
                    steps = round(raw_qty / step_size)
                    sized_qty = max(min_qty, round(steps * step_size, 4))

                    notional = sized_qty * o
                    if notional < min_notional:
                        sized_qty = round(math.ceil(min_notional / o / step_size) * step_size, 4)
                        notional = sized_qty * o

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
                        pos_tp = entry_tp
                        pos_strat_type = trade_sub_type

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
            "strategy": strat_key,
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
    Monte Carlo Bootstrap Resampling Engine.
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
        sampled = random.choices(trade_returns, k=n_trades)
        equity = initial_capital
        peak = equity
        max_dd = 0.0
        path = [round(equity, 2)]

        for pnl in sampled:
            equity = max(0.5, equity + pnl)
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

    indexed_paths = sorted(enumerate(simulated_paths), key=lambda x: x[1][-1])
    sample_indices = [
        p5_idx,
        int(0.25 * num_simulations),
        p50_idx,
        int(0.75 * num_simulations),
        p95_idx,
    ]
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
