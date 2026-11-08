"""
master_engine.py
──────────────────────────────────────────────────────────────────────────────
MasterEngine — Central Market Ingestion, Indicator Math & Signal Engine.

Architecture:
  • Single market data poller: Fetches 15m & 5m klines once per interval from
    Node.js data bridge (O(1) CPU/Network).
  • Proprietary Indicator Sandbox:
      1. 15m Donchian Channel (20 periods)
      2. 15m ADX Momentum Gate (>= 22.0)
      3. 5m Breakout Candle Close
      4. 5m ATR Sizing & Dynamic Ratchet (14 periods)
      5. Institutional Session Filter (07:00–20:00 UTC)
      6. Orderbook Spread & Liquidation Expansion Guard
      7. 8-Hour Funding Rate Sentiment Filter
  • Central Signal Broadcaster: Emits SignalEvents to TenantDispatcher.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

from dispatcher import TenantDispatcher
from events import SignalEvent
from risk_manager import RiskManager
from shark_client import SharkClient
from strategy import get_strategy
from strategy.donchian_breakout import DonchianBreakoutStrategy

log = logging.getLogger("master_engine")

SYMBOL = os.getenv("TRADING_PAIR", "BTCUSDT")
MACRO_INTERVAL = os.getenv("MACRO_INTERVAL", "15m")
MICRO_INTERVAL = os.getenv("MICRO_INTERVAL", "5m")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
KLINES_LIMIT = 300
NODE_URL = os.getenv("NODE_URL", "http://localhost:3001")


def _handle_sigint(sig, frame):
    log.info("SIGINT received — halting Master Engine")
    sys.exit(0)


class MasterEngine:
    """
    Central master signal calculation engine.
    Ingests market data once and broadcasts signals to all tenant workers.
    """

    def __init__(
        self,
        symbol: str = SYMBOL,
        dispatcher: Optional[TenantDispatcher] = None,
        db_path: Optional[str] = None,
        strategy_name: str = "DONCHIAN",
    ) -> None:
        self.symbol = symbol.upper()
        self.db_path = db_path
        self.dispatcher = dispatcher or TenantDispatcher(db_path=self.db_path)
        self.strategy_name = strategy_name.upper()
        self.strategy = get_strategy(self.strategy_name)

        # Market data & client for spread / funding rate queries
        self.client = SharkClient(live=False, dry_run=True)
        self.rm_filter = RiskManager()  # used solely for session & spread checking

        self._running = True
        self.recent_logs: list[str] = []
        self.latest_market: dict[str, Any] = {
            "mark_price": 0.0,
            "atr": 0.0,
            "adx": 0.0,
            "dc_upper": 0.0,
            "dc_lower": 0.0,
            "regime": "UNCLEAR",
            "timeframe": f"{MACRO_INTERVAL}/{MICRO_INTERVAL} MTF",
            "timestamp": "",
        }

        log.info(
            "MasterEngine initialized for %s | Strategy=%s | Timeframe=%s/%s",
            self.symbol,
            self.strategy_name,
            MACRO_INTERVAL,
            MICRO_INTERVAL,
        )

    def _log_event(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.recent_logs.insert(0, f"[{ts}] {msg}")
        if len(self.recent_logs) > 60:
            self.recent_logs.pop()

    def fetch_klines(self, interval: str) -> pd.DataFrame:
        """Fetch klines from Node data bridge for active symbol."""
        url = f"{NODE_URL}/api/klines/{interval}?pair={self.symbol}&limit={KLINES_LIMIT}"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok"):
            raise RuntimeError(f"Node klines error: {body.get('error')}")

        raw = body["data"]
        df = pd.DataFrame(raw)
        df.rename(columns={"startTime": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def step(
        self,
        df_15m: Optional[pd.DataFrame] = None,
        df_5m: Optional[pd.DataFrame] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Execute one calculation iteration.
        Optionally accepts pre-fetched DataFrames for deterministic unit testing.
        """
        try:
            # 1. Ingest market data centrally
            df_macro = df_15m if df_15m is not None else self.fetch_klines(MACRO_INTERVAL)
            df_micro = df_5m if df_5m is not None else self.fetch_klines(MICRO_INTERVAL)

            # Compute indicators centrally
            df_15m_ind = self.strategy.compute_indicators(df_macro)
            df_5m_ind = self.strategy.compute_indicators(df_micro)

            last_15m = df_15m_ind.iloc[-2]
            last_5m = df_5m_ind.iloc[-2]

            atr_val = float(last_5m["atr"]) if not pd.isna(last_5m["atr"]) else 0.0
            adx_val = float(last_15m["adx"]) if not pd.isna(last_15m["adx"]) else 0.0
            dc_up = float(last_15m["dc_upper"]) if not pd.isna(last_15m["dc_upper"]) else 0.0
            dc_lo = float(last_15m["dc_lower"]) if not pd.isna(last_15m["dc_lower"]) else 0.0
            mark_price = float(df_micro.iloc[-1]["close"])

            regime = "UNCLEAR"
            if adx_val >= 25.0:
                regime = "TRENDING"
            elif adx_val < 20.0:
                regime = "RANGING"

            self.latest_market = {
                "mark_price": mark_price,
                "atr": round(atr_val, 2),
                "adx": round(adx_val, 2),
                "dc_upper": round(dc_up, 2),
                "dc_lower": round(dc_lo, 2),
                "regime": regime,
                "timeframe": f"{MACRO_INTERVAL}/{MICRO_INTERVAL} MTF",
                "timestamp": str(last_5m.get("timestamp", "")),
            }

            # 2. Propagate market price & ATR to active tenant positions for trailing ratchets & exits
            closed_trades = self.dispatcher.dispatch_market_update(mark_price, atr_val, self.strategy)
            for ct in closed_trades:
                trade = ct.get("trade", {})
                self._log_event(
                    f"Closed {trade.get('side')} for {ct.get('tenant_id')} @ ${trade.get('exit', 0):.2f} "
                    f"| P&L: ${trade.get('pnl', 0):+.2f} ({trade.get('reason')})"
                )

            # 3. Institutional Session Filter (07:00–20:00 UTC)
            session_ok, session_msg = self.rm_filter.session_ok()
            if not session_ok:
                return {"status": "BLOCKED_BY_SESSION", "reason": session_msg}

            # 4. Strategy Signal Generation
            sig = self.strategy.generate_mtf_signal(df_macro, df_micro)
            if sig.signal == "NO_TRADE":
                return {"status": "NO_TRADE", "reason": sig.reason}

            # 5. Liquidation Cascade / Spread Expansion Guard
            try:
                book = self.client.get_orderbook(self.symbol, depth=5)
                bids = book.get("b", book.get("bids", []))
                asks = book.get("a", book.get("asks", []))
                if bids and asks:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    if not self.rm_filter.spread_ok(best_bid, best_ask):
                        self._log_event("Spread expansion guard: spread > 0.05% — entry delayed")
                        return {"status": "BLOCKED_BY_SPREAD", "reason": "Spread expansion guard"}
            except Exception as spread_err:
                log.warning("Liquidation guard spread check failed: %s", spread_err)

            # 6. 8-Hour Funding Rate Sentiment Filter
            try:
                funding_pct = self.client.get_funding_rate(self.symbol)
                fund_ok, fund_reason = self.rm_filter.funding_rate_ok(sig.signal, funding_pct)
                if not fund_ok:
                    self._log_event(f"Blocked by Funding Rate Gate: {fund_reason}")
                    return {"status": "BLOCKED_BY_FUNDING", "reason": fund_reason}
            except Exception as fund_err:
                log.warning("Funding rate query error: %s", fund_err)

            # 7. Construct Decoupled SignalEvent & Broadcast to Tenant Dispatcher
            event = SignalEvent(
                symbol=self.symbol,
                action=sig.signal,
                entry=sig.entry,
                sl=sig.sl,
                trail_sl=sig.trail_sl,
                atr=sig.atr,
                adx=sig.adx,
                reason=sig.reason,
                dc_upper=sig.dc_upper,
                dc_lower=sig.dc_lower,
            )

            self._log_event(f"Central Signal Generated: {event.action} @ ${event.entry:.2f} (SL: ${event.sl:.2f})")
            dispatch_results = self.dispatcher.dispatch_signal(event)

            return {
                "status": "SIGNAL_BROADCAST",
                "event": event.to_dict(),
                "dispatch_results": dispatch_results,
            }

        except KeyboardInterrupt:
            raise
        except Exception as err:
            log.error("MasterEngine step error: %s", err, exc_info=True)
            return {"status": "ERROR", "reason": str(err)}

    def run(self) -> None:
        """Continuous polling loop."""
        log.info("MasterEngine loop started — polling every %ds", POLL_SECONDS)
        import threading
        if threading.current_thread() is threading.main_thread():
            try:
                signal.signal(signal.SIGINT, _handle_sigint)
            except (ValueError, AttributeError):
                pass

        while self._running:
            self.step()
            time.sleep(POLL_SECONDS)

        log.info("MasterEngine stopped")
