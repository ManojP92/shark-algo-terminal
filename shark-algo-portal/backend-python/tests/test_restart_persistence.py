"""
test_restart_persistence.py
──────────────────────────────────────────────────────────────────────────────
Tests that simulate server restarts to guarantee:
  1. Historical trades are NEVER wiped out.
  2. Capital base and paper wallet are preserved across restarts (no reset to $100).
──────────────────────────────────────────────────────────────────────────────
"""

import os
import tempfile
import pytest
from executor import Executor, OpenPosition
from strategy import TrailingState
import database


@pytest.fixture
def isolated_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("DB_PATH", path)
    database.init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_state_persists_across_restart(isolated_db):
    # 1. First run: Start executor, change capital base to $500, close a trade
    ex1 = Executor()
    ex1.set_mode("PAPER")
    initial_trade_count = len(ex1.trade_history)
    ex1.rm.cfg.capital_base = 500.0
    ex1.paper_wallet = 525.50
    ex1.rm.cfg.manual_lot_size = 0.005

    # Mock an open trade and close it
    trail = TrailingState(side="LONG", entry=75000.0, best_price=75000.0, trail_sl=74000.0)
    ex1.position = OpenPosition(
        side="LONG",
        symbol="BTCUSDT",
        qty=0.002,
        entry=75000.0,
        sl=74000.0,
        trail_state=trail,
        order_id="TEST-PERSIST-1",
        open_time="12:00:00",
    )
    ex1.latest_market["mark_price"] = 76000.0

    # Close position (+$2.00 profit)
    ex1.close_position(reason="Target Profit Reached")
    assert ex1.paper_wallet == 527.50
    assert len(ex1.trade_history) == initial_trade_count + 1
    assert ex1.trade_history[0]["pnl"] == 2.0
    assert ex1.trade_history[0]["reason"] == "Target Profit Reached"

    # Explicit save
    ex1._save_paper_state()

    # 2. Simulate complete server shutdown & reboot
    del ex1

    # 3. Second run (brand new Executor instance, simulating uvicorn reboot)
    ex2 = Executor()

    # Verify everything was preserved across restart!
    assert ex2.paper_wallet == 527.50, f"Expected 527.50 but got {ex2.paper_wallet} (reset to 100 bug!)"
    assert ex2.rm.cfg.capital_base == 500.0, f"Expected capital_base 500.0 but got {ex2.rm.cfg.capital_base}"
    assert ex2.rm.cfg.manual_lot_size == 0.005
    assert len(ex2.trade_history) >= initial_trade_count + 1
    assert ex2.trade_history[0]["pnl"] == 2.0
    assert ex2.trade_history[0]["reason"] == "Target Profit Reached"
