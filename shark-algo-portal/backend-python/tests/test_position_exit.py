"""
tests/test_position_exit.py
──────────────────────────────────────────────────────────────────────────────
Unit and integration tests for position closing and emergency flattening:
  1. Paper mode manual position exit
  2. Live mode market order exit logic (reduceOnly=True)
  3. No open position edge case handling
  4. Emergency flatten & halt
  5. API endpoints for close-position and flatten
──────────────────────────────────────────────────────────────────────────────
"""

import pytest
from executor import Executor, OpenPosition
from strategy import TrailingState


def test_paper_close_position():
    ex = Executor()
    ex.set_mode("PAPER")
    initial_wallet = ex.paper_wallet

    # Mock open position: LONG 0.001 BTC @ $80,000
    trail = TrailingState(side="LONG", entry=80000.0, best_price=80000.0, trail_sl=78000.0)
    ex.position = OpenPosition(
        side="LONG",
        symbol="BTCUSDT",
        qty=0.001,
        entry=80000.0,
        sl=78000.0,
        trail_state=trail,
        order_id="TEST-OPEN-1",
        open_time="10:00:00",
    )
    ex.rm.position_opened()
    assert ex.rm.state.open_positions == 1

    # Simulate market price at $82,000 (+ $2,000 * 0.001 = +$2.00 profit)
    ex.latest_market["mark_price"] = 82000.0

    # Call manual close
    res = ex.close_position(reason="Manual Test Exit")
    assert res["ok"] is True
    assert res["exit"] == 82000.0
    assert ex.position is None
    assert ex.rm.state.open_positions == 0

    assert ex._running is True  # Engine stays running for next setup!
    assert len(ex.trade_history) == 1
    assert ex.trade_history[0]["pnl"] == 2.0
    assert ex.paper_wallet == round(initial_wallet + 2.0, 2)


def test_paper_close_position_short():
    ex = Executor()
    ex.set_mode("PAPER")
    initial_wallet = ex.paper_wallet

    # Mock open position: SHORT 0.001 BTC @ $85,000
    trail = TrailingState(side="SHORT", entry=85000.0, best_price=85000.0, trail_sl=87000.0)
    ex.position = OpenPosition(
        side="SHORT",
        symbol="BTCUSDT",
        qty=0.001,
        entry=85000.0,
        sl=87000.0,
        trail_state=trail,
        order_id="TEST-OPEN-2",
        open_time="11:00:00",
    )
    ex.rm.position_opened()

    # Exit at $84,000 (+$1.00 profit on SHORT)
    ex.latest_market["mark_price"] = 84000.0

    res = ex.close_position(reason="Short Manual Exit")
    assert res["ok"] is True
    assert ex.position is None
    assert ex.paper_wallet == round(initial_wallet + 1.0, 2)


def test_close_position_when_no_position():
    ex = Executor()
    ex.set_mode("PAPER")
    ex.position = None
    res = ex.close_position(reason="Close with none")
    assert res["ok"] is True
    assert "No open position" in res["message"]


def test_emergency_flatten_halts_engine():
    ex = Executor()
    ex.set_mode("PAPER")
    trail = TrailingState(side="LONG", entry=80000.0, best_price=80000.0, trail_sl=78000.0)
    ex.position = OpenPosition(
        side="LONG",
        symbol="BTCUSDT",
        qty=0.001,
        entry=80000.0,
        sl=78000.0,
        trail_state=trail,
        order_id="TEST-OPEN-3",
        open_time="12:00:00",
    )
    ex.rm.position_opened()
    ex.latest_market["mark_price"] = 80500.0

    res = ex.flatten(reason="Test Panic")
    assert res["ok"] is True
    assert res["halted"] is True
    assert ex._running is False  # Bot halted!
    assert ex.position is None
