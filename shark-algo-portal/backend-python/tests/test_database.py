"""
test_database.py
──────────────────────────────────────────────────────────────────────────────
Tests for SQLite persistence layer: trade recording, state saving/retrieval,
and durability across simulated restarts.
──────────────────────────────────────────────────────────────────────────────
"""

import os
import tempfile
import pytest
from database import init_db, record_trade, get_trade_history, set_state, get_state, get_all_state


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_record_and_get_trades(temp_db):
    trade1 = {
        "id": "TR-1001",
        "time": "14:30:00",
        "date": "2026-11-07",
        "side": "LONG",
        "symbol": "BTCUSDT",
        "qty": 0.005,
        "entry": 75000.0,
        "exit": 76000.0,
        "pnl": 5.0,
        "reason": "15m DC Breakout",
    }
    trade2 = {
        "id": "TR-1002",
        "time": "15:00:00",
        "date": "2026-11-07",
        "side": "SHORT",
        "symbol": "BTCUSDT",
        "qty": 0.005,
        "entry": 76000.0,
        "exit": 75500.0,
        "pnl": 2.5,
        "reason": "Trailing stop hit",
    }

    record_trade(trade1, mode="PAPER", db_path=temp_db)
    record_trade(trade2, mode="PAPER", db_path=temp_db)

    history = get_trade_history(limit=10, db_path=temp_db)
    assert len(history) == 2
    assert history[0]["id"] == "TR-1002"  # Latest first
    assert history[1]["id"] == "TR-1001"
    assert history[0]["pnl"] == 2.5
    assert history[1]["pnl"] == 5.0


def test_save_and_get_state(temp_db):
    set_state("paper_wallet", 1250.75, db_path=temp_db)
    set_state("capital_base", 500.0, db_path=temp_db)
    set_state("sizing_mode", "AUTO", db_path=temp_db)

    wallet = get_state("paper_wallet", default=100.0, db_path=temp_db)
    capital = get_state("capital_base", default=100.0, db_path=temp_db)
    mode = get_state("sizing_mode", default="MANUAL", db_path=temp_db)
    missing = get_state("non_existent", default="default_val", db_path=temp_db)

    assert wallet == 1250.75
    assert capital == 500.0
    assert mode == "AUTO"
    assert missing == "default_val"

    all_s = get_all_state(db_path=temp_db)
    assert all_s["paper_wallet"] == 1250.75
    assert all_s["capital_base"] == 500.0
