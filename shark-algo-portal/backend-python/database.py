"""
database.py
──────────────────────────────────────────────────────────────────────────────
Indestructible SQLite persistence layer for Shark Algo Terminal.
Stores:
  1. Complete trade history (PAPER and LIVE executions)
  2. Persistent system state (paper wallet balance, capital base, sizing settings)

Uses SQLite with Write-Ahead Logging (WAL) mode to guarantee durability across
server reboots, service restarts, and power interruptions.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger("database")

_DB_LOCK = threading.Lock()
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trades.db"
)


def get_db_path() -> str:
    path = os.getenv("DB_PATH", _DEFAULT_DB_PATH)
    # Ensure relative paths resolve from portal directory
    if not os.path.isabs(path):
        portal_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.normpath(os.path.join(portal_root, path))
    return path


def init_db(db_path: Optional[str] = None) -> str:
    """Initialize SQLite database schema and WAL mode."""
    target_path = db_path or get_db_path()
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    time TEXT NOT NULL,
                    date TEXT NOT NULL,
                    side TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    qty REAL NOT NULL,
                    entry REAL NOT NULL,
                    exit REAL NOT NULL,
                    pnl REAL NOT NULL,
                    reason TEXT,
                    mode TEXT NOT NULL DEFAULT 'PAPER',
                    created_at TEXT NOT NULL
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            conn.commit()
            log.info("SQLite persistence initialized at %s", target_path)
        finally:
            conn.close()

    return target_path


def record_trade(trade: dict, mode: str = "PAPER", db_path: Optional[str] = None) -> None:
    """Insert closed trade into trades table."""
    target_path = db_path or get_db_path()
    now_iso = datetime.now(timezone.utc).isoformat()

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO trades
                (id, time, date, side, symbol, qty, entry, exit, pnl, reason, mode, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(trade.get("id")),
                    str(trade.get("time")),
                    str(trade.get("date")),
                    str(trade.get("side")),
                    str(trade.get("symbol")),
                    float(trade.get("qty", 0.0)),
                    float(trade.get("entry", 0.0)),
                    float(trade.get("exit", 0.0)),
                    float(trade.get("pnl", 0.0)),
                    str(trade.get("reason", "")),
                    str(mode).upper(),
                    now_iso,
                ),
            )
            conn.commit()
        except Exception as err:
            log.error("Failed to record trade to SQLite: %s", err, exc_info=True)
        finally:
            conn.close()


def get_trade_history(limit: int = 50, symbol: Optional[str] = None, db_path: Optional[str] = None) -> list[dict]:
    """Retrieve recent trades ordered by time descending."""
    target_path = db_path or get_db_path()
    if not os.path.exists(target_path):
        return []

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            if symbol:
                cursor.execute(
                    """
                    SELECT id, time, date, side, symbol, qty, entry, exit, pnl, reason, mode
                    FROM trades
                    WHERE symbol = ?
                    ORDER BY rowid DESC
                    LIMIT ?;
                    """,
                    (symbol.upper(), limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, time, date, side, symbol, qty, entry, exit, pnl, reason, mode
                    FROM trades
                    ORDER BY rowid DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as err:
            log.error("Failed to fetch trade history from SQLite: %s", err)
            return []
        finally:
            conn.close()


def set_state(key: str, val: Any, db_path: Optional[str] = None) -> None:
    """Store key-value state."""
    target_path = db_path or get_db_path()
    now_iso = datetime.now(timezone.utc).isoformat()
    val_json = json.dumps(val)

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO system_state (key, value, updated_at)
                VALUES (?, ?, ?);
                """,
                (key, val_json, now_iso),
            )
            conn.commit()
        except Exception as err:
            log.error("Failed to set state '%s': %s", key, err)
        finally:
            conn.close()


def get_state(key: str, default: Any = None, db_path: Optional[str] = None) -> Any:
    """Retrieve key-value state."""
    target_path = db_path or get_db_path()
    if not os.path.exists(target_path):
        return default

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_state WHERE key = ?;", (key,))
            row = cursor.fetchone()
            if row is not None:
                return json.loads(row[0])
            return default
        except Exception as err:
            log.error("Failed to get state '%s': %s", key, err)
            return default
        finally:
            conn.close()


def get_all_state(db_path: Optional[str] = None) -> dict[str, Any]:
    """Retrieve entire state dictionary."""
    target_path = db_path or get_db_path()
    if not os.path.exists(target_path):
        return {}

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM system_state;")
            rows = cursor.fetchall()
            res = {}
            for k, v in rows:
                try:
                    res[k] = json.loads(v)
                except Exception:
                    res[k] = v
            return res
        except Exception as err:
            log.error("Failed to get all state: %s", err)
            return {}
        finally:
            conn.close()
