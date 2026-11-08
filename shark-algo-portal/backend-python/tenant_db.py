"""
tenant_db.py
──────────────────────────────────────────────────────────────────────────────
Multi-Tenant Database and Storage Engine for Shark Algo Terminal.
Features:
  1. Multi-tenant partitioning (tenant_id foreign key on trades & state)
  2. Integrated AES-256 vault for exchange credentials (tenant_keys)
  3. Thread-safe SQLite with Write-Ahead Logging (WAL)
  4. Auto-seeding of Default Admin with backward-compatibility for legacy trades
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import vault

log = logging.getLogger("tenant_db")

_DB_LOCK = threading.Lock()
_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "trades.db"
)


def get_db_path() -> str:
    path = os.getenv("DB_PATH", _DEFAULT_DB_PATH)
    if not os.path.isabs(path):
        portal_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.normpath(os.path.join(portal_root, path))
    return path


def hash_password(password: str) -> str:
    """Hash password with a unique salt using PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}:{key.hex()}"


def verify_password(stored_hash: str, password_attempt: str) -> bool:
    """Verify password against stored salt:hash."""
    try:
        salt, key_hex = stored_hash.split(":", 1)
        attempt_key = hashlib.pbkdf2_hmac(
            "sha256", password_attempt.encode("utf-8"), salt.encode("utf-8"), 100_000
        )
        return secrets.compare_digest(attempt_key.hex(), key_hex)
    except Exception:
        return False


def init_tenant_db(db_path: Optional[str] = None) -> str:
    """Initialize multi-tenant schema with WAL mode."""
    target_path = db_path or get_db_path()
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")

            # 1. Tenants table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'CLIENT',
                    mode TEXT NOT NULL DEFAULT 'PAPER',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    capital_base REAL NOT NULL DEFAULT 100.0,
                    risk_per_trade_pct REAL NOT NULL DEFAULT 1.0,
                    daily_loss_limit_pct REAL NOT NULL DEFAULT 3.0,
                    max_consecutive_losses INTEGER NOT NULL DEFAULT 3,
                    sizing_mode TEXT NOT NULL DEFAULT 'AUTO',
                    manual_lot_size REAL NOT NULL DEFAULT 0.001,
                    leverage INTEGER NOT NULL DEFAULT 10,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 2. Encrypted exchange keys table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenant_keys (
                    tenant_id TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL DEFAULT 'SHARK',
                    encrypted_api_key TEXT NOT NULL,
                    encrypted_api_secret TEXT NOT NULL,
                    key_nickname TEXT,
                    is_valid INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );
            """)

            # 3. Multi-tenant trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenant_trades (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    entry REAL NOT NULL,
                    exit REAL NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_pct REAL NOT NULL DEFAULT 0.0,
                    reason TEXT,
                    mode TEXT NOT NULL DEFAULT 'PAPER',
                    order_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tenant_trades ON tenant_trades(tenant_id, created_at DESC);")

            # 4. Multi-tenant state table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tenant_state (
                    tenant_id TEXT PRIMARY KEY,
                    paper_wallet REAL NOT NULL DEFAULT 100.0,
                    day_start_equity REAL NOT NULL DEFAULT 100.0,
                    daily_pnl REAL NOT NULL DEFAULT 0.0,
                    consecutive_losses INTEGER NOT NULL DEFAULT 0,
                    cooldown_until REAL NOT NULL DEFAULT 0.0,
                    halted INTEGER NOT NULL DEFAULT 0,
                    active_position_json TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );
            """)

            conn.commit()

            # Seed default admin if table is empty
            cursor.execute("SELECT COUNT(*) FROM tenants;")
            if cursor.fetchone()[0] == 0:
                admin_id = "tenant_default_admin"
                now_iso = datetime.now(timezone.utc).isoformat()
                cursor.execute(
                    """
                    INSERT INTO tenants 
                    (id, email, password_hash, role, mode, is_active, capital_base, risk_per_trade_pct, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        admin_id,
                        "admin@sharkalgo.com",
                        hash_password(os.getenv("ADMIN_PASSWORD", "shark2026")),
                        "SUPERADMIN",
                        "PAPER",
                        1,
                        float(os.getenv("CAPITAL_BASE", "100.0")),
                        1.0,
                        now_iso,
                        now_iso,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO tenant_state
                    (tenant_id, paper_wallet, day_start_equity, updated_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (admin_id, float(os.getenv("CAPITAL_BASE", "100.0")), float(os.getenv("CAPITAL_BASE", "100.0")), now_iso),
                )
                # Seed shark api keys from .env if present
                env_key = os.getenv("SHARK_API_KEY")
                env_secret = os.getenv("SHARK_API_SECRET")
                if env_key and env_secret:
                    enc_key = vault.encrypt_secret(env_key)
                    enc_sec = vault.encrypt_secret(env_secret)
                    cursor.execute(
                        """
                        INSERT INTO tenant_keys
                        (tenant_id, exchange, encrypted_api_key, encrypted_api_secret, key_nickname, updated_at)
                        VALUES (?, 'SHARK', ?, ?, 'Master Admin Credentials', ?);
                        """,
                        (admin_id, enc_key, enc_sec, now_iso),
                    )
                conn.commit()
                log.info("Initialized default superadmin tenant '%s'", admin_id)

        finally:
            conn.close()

    return target_path


# ── Tenant Account Operations ──────────────────────────────────────────────────

def create_tenant(
    email: str,
    password: str,
    role: str = "CLIENT",
    mode: str = "PAPER",
    capital_base: float = 100.0,
    risk_per_trade_pct: float = 1.0,
    db_path: Optional[str] = None,
) -> dict:
    """Create a new tenant with isolated account, risk limits, and state."""
    target_path = db_path or get_db_path()
    tenant_id = f"usr_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    pwd_hash = hash_password(password)

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tenants
                (id, email, password_hash, role, mode, is_active, capital_base, risk_per_trade_pct, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?);
                """,
                (tenant_id, email.lower().strip(), pwd_hash, role.upper(), mode.upper(), capital_base, risk_per_trade_pct, now_iso, now_iso),
            )
            cursor.execute(
                """
                INSERT INTO tenant_state
                (tenant_id, paper_wallet, day_start_equity, updated_at)
                VALUES (?, ?, ?, ?);
                """,
                (tenant_id, capital_base, capital_base, now_iso),
            )
            conn.commit()
            log.info("Created new tenant %s (%s)", tenant_id, email)
            return {
                "id": tenant_id,
                "email": email,
                "role": role.upper(),
                "mode": mode.upper(),
                "capital_base": capital_base,
            }
        finally:
            conn.close()


def get_tenant_by_id(tenant_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    target_path = db_path or get_db_path()
    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tenants WHERE id = ?;", (tenant_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def get_tenant_by_email(email: str, db_path: Optional[str] = None) -> Optional[dict]:
    target_path = db_path or get_db_path()
    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tenants WHERE email = ?;", (email.lower().strip(),))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_active_tenants(db_path: Optional[str] = None) -> list[dict]:
    target_path = db_path or get_db_path()
    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tenants WHERE is_active = 1;")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ── Credential Vault Operations ────────────────────────────────────────────────

def set_tenant_keys(
    tenant_id: str,
    api_key: str,
    api_secret: str,
    exchange: str = "SHARK",
    nickname: str = "Default API Key",
    db_path: Optional[str] = None,
) -> None:
    """Encrypt and store exchange credentials in the vault."""
    target_path = db_path or get_db_path()
    enc_key = vault.encrypt_secret(api_key)
    enc_secret = vault.encrypt_secret(api_secret)
    now_iso = datetime.now(timezone.utc).isoformat()

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO tenant_keys
                (tenant_id, exchange, encrypted_api_key, encrypted_api_secret, key_nickname, is_valid, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?);
                """,
                (tenant_id, exchange.upper(), enc_key, enc_secret, nickname, now_iso),
            )
            conn.commit()
            log.info("Encrypted and stored API keys for tenant %s (%s)", tenant_id, exchange)
        finally:
            conn.close()


def get_tenant_keys(tenant_id: str, db_path: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """Retrieve and decrypt exchange credentials Just-In-Time (JIT) for execution."""
    target_path = db_path or get_db_path()
    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT encrypted_api_key, encrypted_api_secret FROM tenant_keys WHERE tenant_id = ? AND is_valid = 1;",
                (tenant_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None, None
            api_key = vault.decrypt_secret(row[0])
            api_secret = vault.decrypt_secret(row[1])
            return api_key, api_secret
        except Exception as err:
            log.error("Failed to decrypt keys for tenant %s: %s", tenant_id, err)
            return None, None
        finally:
            conn.close()


# ── Partitioned Trade Ledger Operations ────────────────────────────────────────

def record_tenant_trade(tenant_id: str, trade: dict, mode: str = "PAPER", db_path: Optional[str] = None) -> None:
    """Record a trade strictly into the tenant's isolated ledger."""
    target_path = db_path or get_db_path()
    now_iso = datetime.now(timezone.utc).isoformat()

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO tenant_trades
                (id, tenant_id, symbol, side, qty, entry, exit, pnl, pnl_pct, reason, mode, order_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    str(trade.get("id", f"TR-{secrets.token_hex(6)}")),
                    tenant_id,
                    str(trade.get("symbol", "BTCUSDT")).upper(),
                    str(trade.get("side", "LONG")).upper(),
                    float(trade.get("qty", 0.001)),
                    float(trade.get("entry", 0.0)),
                    float(trade.get("exit", 0.0)),
                    float(trade.get("pnl", 0.0)),
                    float(trade.get("pnl_pct", 0.0)),
                    str(trade.get("reason", "")),
                    str(mode).upper(),
                    str(trade.get("order_id", "")),
                    now_iso,
                ),
            )
            conn.commit()
        except Exception as err:
            log.error("Failed to record trade for tenant %s: %s", tenant_id, err)
        finally:
            conn.close()


def get_tenant_trades(tenant_id: str, limit: int = 50, db_path: Optional[str] = None) -> list[dict]:
    """Retrieve recent trades strictly for the specified tenant."""
    target_path = db_path or get_db_path()
    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, symbol, side, qty, entry, exit, pnl, pnl_pct, reason, mode, order_id, created_at
                FROM tenant_trades
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (tenant_id, limit),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ── Tenant State Operations ────────────────────────────────────────────────────

def set_tenant_state(tenant_id: str, state_dict: dict, db_path: Optional[str] = None) -> None:
    """Save tenant runtime state (wallet balance, daily P&L, circuit breakers)."""
    target_path = db_path or get_db_path()
    now_iso = datetime.now(timezone.utc).isoformat()
    pos_json = json.dumps(state_dict.get("active_position")) if state_dict.get("active_position") else None

    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO tenant_state
                (tenant_id, paper_wallet, day_start_equity, daily_pnl, consecutive_losses, cooldown_until, halted, active_position_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    tenant_id,
                    float(state_dict.get("paper_wallet", 100.0)),
                    float(state_dict.get("day_start_equity", 100.0)),
                    float(state_dict.get("daily_pnl", 0.0)),
                    int(state_dict.get("consecutive_losses", 0)),
                    float(state_dict.get("cooldown_until", 0.0)),
                    1 if state_dict.get("halted") else 0,
                    pos_json,
                    now_iso,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_tenant_state(tenant_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    target_path = db_path or get_db_path()
    with _DB_LOCK:
        conn = sqlite3.connect(target_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tenant_state WHERE tenant_id = ?;", (tenant_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("active_position_json"):
                try:
                    res["active_position"] = json.loads(res["active_position_json"])
                except Exception:
                    res["active_position"] = None
            return res
        finally:
            conn.close()
