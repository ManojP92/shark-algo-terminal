"""
test_session_filter.py
──────────────────────────────────────────────────────────────────────────────
Unit tests for Institutional Session Time-of-Day Filter (London & NY Window).
07:00 to 20:00 UTC (12:30 PM to 01:30 AM IST).
Off-hours (Asian chop: 21:00 to 06:00 UTC) blocked from opening new positions.
──────────────────────────────────────────────────────────────────────────────
"""

import pytest
from risk_manager import RiskManager, RiskConfig


def test_session_filter_allowed_hours():
    """Verify that trades are permitted during active London/NY hours (07:00 - 20:00 UTC)."""
    cfg = RiskConfig(
        session_filter_enabled=True,
        allowed_hours_utc={7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20},
    )
    rm = RiskManager(cfg)

    # Allowed hours
    for h in [7, 8, 11, 14, 16, 18, 20]:
        ok, reason = rm.session_ok(utc_hour=h)
        assert ok is True
        assert reason == "SESSION_OK"

        trade_ok, trade_reason = rm.can_trade(equity=100.0, utc_hour=h)
        assert trade_ok is True
        assert trade_reason == "OK"


def test_session_filter_blocked_hours():
    """Verify that trades are blocked during off-peak/Asian chop hours (21:00 - 06:00 UTC)."""
    cfg = RiskConfig(
        session_filter_enabled=True,
        allowed_hours_utc={7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20},
    )
    rm = RiskManager(cfg)

    # Blocked off-hours
    for h in [0, 1, 2, 3, 4, 5, 6, 21, 22, 23]:
        ok, reason = rm.session_ok(utc_hour=h)
        assert ok is False
        assert "outside allowed trend window" in reason

        trade_ok, trade_reason = rm.can_trade(equity=100.0, utc_hour=h)
        assert trade_ok is False
        assert "Session Filter" in trade_reason


def test_session_filter_disabled():
    """Verify that when disabled, all hours are permitted."""
    cfg = RiskConfig(session_filter_enabled=False)
    rm = RiskManager(cfg)

    for h in range(24):
        ok, reason = rm.session_ok(utc_hour=h)
        assert ok is True
        assert reason == "SESSION_FILTER_DISABLED"

        trade_ok, trade_reason = rm.can_trade(equity=100.0, utc_hour=h)
        assert trade_ok is True
        assert trade_reason == "OK"


def test_session_filter_custom_hours():
    """Verify that custom allowed hours can be configured."""
    cfg = RiskConfig(session_filter_enabled=True, allowed_hours_utc={12, 13, 14})
    rm = RiskManager(cfg)

    assert rm.session_ok(utc_hour=13)[0] is True
    assert rm.session_ok(utc_hour=15)[0] is False
