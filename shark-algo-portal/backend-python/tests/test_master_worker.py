"""
test_master_worker.py
──────────────────────────────────────────────────────────────────────────────
Comprehensive Test Suite for Master-Worker Multi-Tenant Architecture.
Tests:
  1. Multi-tenant registration, initialization, and isolated sandboxing.
  2. SignalEvent broadcast fan-out and proportional lot sizing ($100 vs $500 vs $5,000).
  3. Circuit breaker sandbox isolation (Tenant in cooldown skipped; others execute).
  4. Concurrent trailing stop ratchet and exit evaluation across all tenant positions.
  5. Tenant manual close isolation.
  6. Inactive tenant handling.
──────────────────────────────────────────────────────────────────────────────
"""

import os
import shutil
import tempfile
import pytest

import tenant_db
import vault
from dispatcher import TenantDispatcher
from events import SignalEvent
from master_engine import MasterEngine
from strategy.donchian_breakout import DonchianBreakoutStrategy


@pytest.fixture
def temp_workspace():
    """Create isolated temporary database and vault key for testing."""
    temp_dir = tempfile.mkdtemp(prefix="shark_mw_test_")
    db_file = os.path.join(temp_dir, "test_trades.db")
    os.environ["ENCRYPTION_MASTER_KEY"] = vault.generate_master_key()
    tenant_db.init_tenant_db(db_file)
    yield db_file
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_tenant_worker_initialization(temp_workspace):
    """Verify tenant workers initialize with custom capital and risk sandboxes."""
    db = temp_workspace
    t1 = tenant_db.create_tenant(
        email="alice@shark.io",
        password="alice_password",
        capital_base=500.0,
        risk_per_trade_pct=1.5,
        db_path=db,
    )
    t2 = tenant_db.create_tenant(
        email="bob@shark.io",
        password="bob_password",
        capital_base=5000.0,
        risk_per_trade_pct=0.5,
        db_path=db,
    )

    dispatcher = TenantDispatcher(db_path=db)
    active_ids = dispatcher.sync_tenants()

    assert t1["id"] in active_ids
    assert t2["id"] in active_ids

    w1 = dispatcher.get_worker(t1["id"])
    w2 = dispatcher.get_worker(t2["id"])

    assert w1 is not None
    assert w2 is not None
    assert w1.rm.cfg.capital_base == 500.0
    assert w1.rm.cfg.risk_per_trade_pct == 1.5
    assert w2.rm.cfg.capital_base == 5000.0
    assert w2.rm.cfg.risk_per_trade_pct == 0.5


def test_signal_fanout_and_proportional_sizing(temp_workspace):
    """
    Verify that a single SignalEvent broadcast scales position sizing
    proportionally according to each tenant's capital.
    """
    db = temp_workspace
    # Alice: $100 capital, 1.0% risk -> $1 risk budget
    t_alice = tenant_db.create_tenant("alice@test.com", "pass123", capital_base=100.0, risk_per_trade_pct=1.0, db_path=db)
    # Bob: $500 capital, 1.0% risk -> $5 risk budget
    t_bob = tenant_db.create_tenant("bob@test.com", "pass123", capital_base=500.0, risk_per_trade_pct=1.0, db_path=db)
    # Charlie: $5,000 capital, 1.0% risk -> $50 risk budget
    t_charlie = tenant_db.create_tenant("charlie@test.com", "pass123", capital_base=5000.0, risk_per_trade_pct=1.0, db_path=db)

    dispatcher = TenantDispatcher(db_path=db)

    # Signal: Entry @ 60,000, SL @ 59,000 (Risk per BTC = $1,000)
    sig = SignalEvent(
        symbol="BTCUSDT",
        action="LONG",
        entry=60000.0,
        sl=59000.0,
        trail_sl=57000.0,
        atr=800.0,
        adx=30.0,
        reason="15m DC breakout",
    )

    results = dispatcher.dispatch_signal(sig)

    assert results[t_alice["id"]]["status"] == "FILLED"
    assert results[t_bob["id"]]["status"] == "FILLED"
    assert results[t_charlie["id"]]["status"] == "FILLED"

    qty_alice = results[t_alice["id"]]["qty"]
    qty_bob = results[t_bob["id"]]["qty"]
    qty_charlie = results[t_charlie["id"]]["qty"]

    # At $1,000 SL distance:
    # Alice ($1 risk) -> 0.001 BTC
    # Bob ($5 risk) -> 0.005 BTC
    # Charlie ($50 risk) -> 0.050 BTC
    assert qty_alice == 0.001
    assert qty_bob == 0.005
    assert qty_charlie == 0.050

    # Ensure positions are marked open
    w_alice = dispatcher.get_worker(t_alice["id"])
    w_bob = dispatcher.get_worker(t_bob["id"])
    assert w_alice.position is not None
    assert w_bob.position is not None
    assert w_alice.position.qty == 0.001
    assert w_bob.position.qty == 0.005


def test_circuit_breaker_isolation(temp_workspace):
    """
    Verify that if Tenant 1 breaches their risk limit (e.g. cooldown),
    they are blocked with BLOCKED_BY_RISK, while Tenant 2 executes normally.
    """
    db = temp_workspace
    t1 = tenant_db.create_tenant("user1@test.com", "pass", capital_base=500.0, db_path=db)
    t2 = tenant_db.create_tenant("user2@test.com", "pass", capital_base=500.0, db_path=db)

    dispatcher = TenantDispatcher(db_path=db)
    w1 = dispatcher.get_worker(t1["id"])
    w2 = dispatcher.get_worker(t2["id"])

    # Simulate 3 consecutive losses for Tenant 1 -> triggers 30-min cooldown
    w1.rm.record_trade(-10.0)
    w1.rm.record_trade(-10.0)
    w1.rm.record_trade(-10.0)
    assert w1.rm.state.consecutive_losses == 3
    assert w1.rm.state.cooldown_until_ts > 0

    # Tenant 2 has 0 losses
    assert w2.rm.state.consecutive_losses == 0

    sig = SignalEvent(
        symbol="BTCUSDT",
        action="LONG",
        entry=65000.0,
        sl=64000.0,
        trail_sl=62000.0,
        atr=800.0,
        adx=28.0,
        reason="Breakout test",
    )

    results = dispatcher.dispatch_signal(sig)

    # Tenant 1 must be blocked by their own isolated risk sandbox
    assert results[t1["id"]]["status"] == "BLOCKED_BY_RISK"
    assert "cooldown" in results[t1["id"]]["reason"].lower()

    # Tenant 2 must execute successfully
    assert results[t2["id"]]["status"] == "FILLED"
    assert w2.position is not None


def test_concurrent_trailing_stop_and_exit(temp_workspace):
    """
    Verify that dispatch_market_update ratchets trailing stops for all open positions,
    and cleanly exits tenants when price pulls back to the stop level.
    """
    db = temp_workspace
    t_alice = tenant_db.create_tenant("alice_trail@test.com", "pass", capital_base=500.0, db_path=db)
    t_bob = tenant_db.create_tenant("bob_trail@test.com", "pass", capital_base=1000.0, db_path=db)

    dispatcher = TenantDispatcher(db_path=db)
    strategy = DonchianBreakoutStrategy(atr_mult_trail=3.0)

    # Open positions @ 60,000, initial trail SL @ 57,000 (ATR = 1000)
    sig = SignalEvent(
        symbol="BTCUSDT",
        action="LONG",
        entry=60000.0,
        sl=58500.0,
        trail_sl=57000.0,
        atr=1000.0,
        adx=32.0,
        reason="Initial entry",
    )
    dispatcher.dispatch_signal(sig)

    w_alice = dispatcher.get_worker(t_alice["id"])
    w_bob = dispatcher.get_worker(t_bob["id"])
    assert w_alice.position.sl == 58500.0
    assert w_alice.position.trail_state.trail_sl == 57000.0

    # 1. Price advances strongly to 65,000 (favorable move)
    # New trail SL should ratchet to 65000 - (3 * 1000) = 62,000
    closed = dispatcher.dispatch_market_update(mark_price=65000.0, atr=1000.0, strategy=strategy)
    assert len(closed) == 0  # No exits yet
    assert w_alice.position.sl == 62000.0
    assert w_bob.position.sl == 62000.0

    # 2. Price pulls back to 61,500 (breaches ratcheted 62,000 trail SL)
    closed = dispatcher.dispatch_market_update(mark_price=61500.0, atr=1000.0, strategy=strategy)
    exited_ids = {c["tenant_id"] for c in closed}
    assert t_alice["id"] in exited_ids
    assert t_bob["id"] in exited_ids
    assert len(closed) >= 2  # Alice, Bob (and seeded default admin) exited!

    # Positions should now be None
    assert w_alice.position is None
    assert w_bob.position is None

    # Ledgers in SQLite must record the closed trades
    trades_alice = tenant_db.get_tenant_trades(t_alice["id"], db_path=db)
    trades_bob = tenant_db.get_tenant_trades(t_bob["id"], db_path=db)
    assert len(trades_alice) == 1
    assert len(trades_bob) == 1
    assert trades_alice[0]["exit"] == 61500.0
    assert trades_alice[0]["pnl"] > 0  # Profitable trade (entry 60,000, exit 61,500)


def test_tenant_manual_close_isolation(temp_workspace):
    """Verify closing position for Tenant A leaves Tenant B open and untouched."""
    db = temp_workspace
    t1 = tenant_db.create_tenant("t1@test.com", "pass", capital_base=300.0, db_path=db)
    t2 = tenant_db.create_tenant("t2@test.com", "pass", capital_base=300.0, db_path=db)

    dispatcher = TenantDispatcher(db_path=db)
    sig = SignalEvent(
        symbol="BTCUSDT",
        action="LONG",
        entry=50000.0,
        sl=49000.0,
        trail_sl=47000.0,
        atr=500.0,
        adx=25.0,
        reason="Entry",
    )
    dispatcher.dispatch_signal(sig)

    w1 = dispatcher.get_worker(t1["id"])
    w2 = dispatcher.get_worker(t2["id"])
    assert w1.position is not None
    assert w2.position is not None

    # Manually close t1 only
    res = dispatcher.close_tenant_position(t1["id"], reason="Manual close test", mark_price=51000.0)
    assert res["ok"] is True
    assert w1.position is None
    assert w2.position is not None  # Tenant 2 is still open!


def test_inactive_tenant_is_skipped(temp_workspace):
    """Verify deactivated tenants do not receive or execute signals."""
    db = temp_workspace
    t_active = tenant_db.create_tenant("active@test.com", "pass", capital_base=200.0, db_path=db)
    t_inactive = tenant_db.create_tenant("inactive@test.com", "pass", capital_base=200.0, db_path=db)
    tenant_db.update_tenant_config(t_inactive["id"], {"is_active": 0}, db_path=db)

    dispatcher = TenantDispatcher(db_path=db)
    sig = SignalEvent(
        symbol="BTCUSDT",
        action="LONG",
        entry=50000.0,
        sl=49000.0,
        trail_sl=47000.0,
        atr=500.0,
        adx=25.0,
        reason="Entry",
    )
    results = dispatcher.dispatch_signal(sig)

    assert t_active["id"] in results
    assert results[t_active["id"]]["status"] == "FILLED"
    # Inactive tenant should either not be dispatched to or returned as inactive
    assert t_inactive["id"] not in results
