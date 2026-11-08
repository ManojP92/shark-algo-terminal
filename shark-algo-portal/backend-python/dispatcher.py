"""
dispatcher.py
──────────────────────────────────────────────────────────────────────────────
TenantDispatcher — Master Orchestrator and Signal Broadcaster.

Responsibilities:
  1. Manages pool of active TenantWorkers mapped to database tenants.
  2. Dispatches central SignalEvents concurrently across all tenant sandboxes.
  3. Propagates real-time market ticks & ATR updates to active tenant positions
     for independent trailing stop ratchet and exit evaluation.
  4. Provides granular tenant control (manual close, pause, config update).
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from typing import Any, Optional

import tenant_db
from events import SignalEvent
from strategy.donchian_breakout import DonchianBreakoutStrategy
from worker import TenantWorker

log = logging.getLogger("tenant_dispatcher")


class TenantDispatcher:
    """
    Central dispatcher coordinating between the Master Signal Engine and
    individual Tenant Worker execution pods.
    """

    def __init__(self, db_path: Optional[str] = None, max_workers: int = 16) -> None:
        self.db_path = db_path
        self.max_workers = max_workers
        self._workers: dict[str, TenantWorker] = {}
        self._lock = threading.Lock()

        # Initial tenant pool synchronization
        self.sync_tenants()

    def sync_tenants(self) -> list[str]:
        """
        Synchronize in-memory worker pool with active tenants in SQLite/Postgres.
        Adds new active tenants, updates existing ones, and removes deactivated ones.
        """
        active_tenants = tenant_db.list_active_tenants(db_path=self.db_path)
        active_ids = {t["id"] for t in active_tenants}

        with self._lock:
            # 1. Add new workers or update configs
            for t_data in active_tenants:
                t_id = t_data["id"]
                if t_id not in self._workers:
                    try:
                        worker = TenantWorker(t_id, tenant_data=t_data, db_path=self.db_path)
                        self._workers[t_id] = worker
                        log.info("Registered tenant worker %s (%s, Mode=%s)", t_id, t_data.get("email"), worker.mode)
                    except Exception as err:
                        log.error("Failed to initialize worker for tenant %s: %s", t_id, err)
                else:
                    # Refresh configuration attributes
                    w = self._workers[t_id]
                    w.mode = str(t_data.get("mode", "PAPER")).upper()
                    w.is_active = bool(t_data.get("is_active", 1))
                    w.rm.cfg.capital_base = float(t_data.get("capital_base", 100.0))
                    w.rm.cfg.risk_per_trade_pct = float(t_data.get("risk_per_trade_pct", 1.0))
                    w.rm.cfg.daily_loss_cap_pct = float(t_data.get("daily_loss_limit_pct", 3.0))
                    w.rm.cfg.max_consecutive_losses = int(t_data.get("max_consecutive_losses", 3))
                    w.rm.cfg.sizing_mode = str(t_data.get("sizing_mode", "AUTO")).upper()
                    w.rm.cfg.manual_lot_size = float(t_data.get("manual_lot_size", 0.001))
                    w.rm.cfg.leverage = int(t_data.get("leverage", 10))

            # 2. Evict inactive / deleted workers
            to_remove = [tid for tid in self._workers if tid not in active_ids]
            for tid in to_remove:
                log.info("De-registering inactive tenant worker %s", tid)
                del self._workers[tid]

            return list(self._workers.keys())

    def get_worker(self, tenant_id: str) -> Optional[TenantWorker]:
        """Fetch worker instance by tenant ID."""
        with self._lock:
            return self._workers.get(tenant_id)

    # ── Signal Fan-Out ──────────────────────────────────────────────────────────

    def dispatch_signal(self, signal: SignalEvent) -> dict[str, dict[str, Any]]:
        """
        Concurrently broadcast a SignalEvent across all active tenant workers.
        Each tenant checks its own risk, computes its own lot size, and places its own order.
        """
        self.sync_tenants()

        with self._lock:
            active_workers = list(self._workers.values())

        if not active_workers:
            log.warning("No active tenant workers available to receive signal %s", signal.action)
            return {}

        results: dict[str, dict[str, Any]] = {}

        def _execute(w: TenantWorker) -> tuple[str, dict[str, Any]]:
            try:
                res = w.execute_signal(signal)
                return w.tenant_id, res
            except Exception as err:
                log.error("Unhandled error dispatching signal to tenant %s: %s", w.tenant_id, err, exc_info=True)
                return w.tenant_id, {"status": "ERROR", "reason": str(err)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(active_workers))) as pool:
            futures = [pool.submit(_execute, w) for w in active_workers]
            for fut in concurrent.futures.as_completed(futures):
                tid, res = fut.result()
                results[tid] = res

        log.info("Dispatched signal %s to %d tenants: %s", signal.action, len(results),
                 {tid: res.get("status") for tid, res in results.items()})
        return results

    # ── Market Tick & Trailing Stop Updates ──────────────────────────────────────

    def dispatch_market_update(
        self,
        mark_price: float,
        atr: float,
        strategy: DonchianBreakoutStrategy,
    ) -> list[dict[str, Any]]:
        """
        Evaluate trailing stops and exits across all workers with open positions.
        Returns list of closed trade dictionaries.
        """
        with self._lock:
            workers_with_pos = [w for w in self._workers.values() if w.position is not None]

        if not workers_with_pos:
            return []

        closed_trades: list[dict[str, Any]] = []

        def _update(w: TenantWorker) -> Optional[dict[str, Any]]:
            try:
                return w.update_position(mark_price, atr, strategy)
            except Exception as err:
                log.error("Error updating position for tenant %s: %s", w.tenant_id, err)
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(workers_with_pos))) as pool:
            futures = [pool.submit(_update, w) for w in workers_with_pos]
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                if res and res.get("ok"):
                    closed_trades.append(res)

        return closed_trades

    # ── Granular Tenant Actions ────────────────────────────────────────────────

    def close_tenant_position(
        self,
        tenant_id: str,
        reason: str = "Manual Close",
        mark_price: float = 0.0,
    ) -> dict[str, Any]:
        """Manually close position for a specific tenant."""
        worker = self.get_worker(tenant_id)
        if not worker:
            return {"ok": False, "error": f"Tenant '{tenant_id}' not found or inactive."}
        return worker.close_position(reason=reason, mark_price=mark_price)

    def close_all_positions(
        self,
        reason: str = "Emergency Flatten All",
        mark_price: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Emergency flatten across all tenants simultaneously."""
        with self._lock:
            workers_with_pos = [w for w in self._workers.values() if w.position is not None]

        flattened: list[dict[str, Any]] = []
        for w in workers_with_pos:
            res = w.close_position(reason=reason, mark_price=mark_price)
            flattened.append(res)
        return flattened

    def get_tenant_status(self, tenant_id: str, mark_price: float = 0.0) -> Optional[dict[str, Any]]:
        """Get status for a specific tenant."""
        worker = self.get_worker(tenant_id)
        if not worker:
            return None
        return worker.get_status(mark_price=mark_price)

    def get_all_statuses(self, mark_price: float = 0.0) -> dict[str, dict[str, Any]]:
        """Get statuses for all active tenants."""
        with self._lock:
            workers = list(self._workers.values())
        return {w.tenant_id: w.get_status(mark_price=mark_price) for w in workers}
