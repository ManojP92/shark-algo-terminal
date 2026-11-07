"""
test_funding_rate.py
──────────────────────────────────────────────────────────────────────────────
Unit tests for the 8-hour perpetual funding rate sentiment filter.
Verifies:
  - Normal funding rates allow both Long and Short entries.
  - Overheated positive funding rate (> +0.04%) blocks Longs.
  - Deep negative funding rate (< -0.04%) blocks Shorts.
  - Custom funding thresholds in RiskConfig are respected.
──────────────────────────────────────────────────────────────────────────────
"""

import pytest
from risk_manager import RiskManager, RiskConfig


def test_funding_rate_normal():
    rm = RiskManager(RiskConfig(funding_max_long_pct=0.04, funding_min_short_pct=-0.04))
    
    # 0.01% is normal baseline crypto funding
    ok_long, msg_long = rm.funding_rate_ok("BUY", 0.01)
    assert ok_long is True
    assert msg_long == "FUNDING_OK"

    ok_short, msg_short = rm.funding_rate_ok("SELL", 0.01)
    assert ok_short is True
    assert msg_short == "FUNDING_OK"


def test_funding_rate_overheated_long():
    rm = RiskManager(RiskConfig(funding_max_long_pct=0.04, funding_min_short_pct=-0.04))
    
    # +0.08% funding (extreme bullish crowd -> long squeeze danger)
    ok_long, msg_long = rm.funding_rate_ok("BUY", 0.08)
    assert ok_long is False
    assert "Long entry blocked" in msg_long

    # Short should still be allowed during overheated funding (counter-trend)
    ok_short, msg_short = rm.funding_rate_ok("SELL", 0.08)
    assert ok_short is True
    assert msg_short == "FUNDING_OK"


def test_funding_rate_crowded_short():
    rm = RiskManager(RiskConfig(funding_max_long_pct=0.04, funding_min_short_pct=-0.04))
    
    # -0.06% funding (extreme bearish crowd -> short squeeze danger)
    ok_short, msg_short = rm.funding_rate_ok("SELL", -0.06)
    assert ok_short is False
    assert "Short entry blocked" in msg_short

    # Long should still be allowed during crowded negative funding
    ok_long, msg_long = rm.funding_rate_ok("BUY", -0.06)
    assert ok_long is True
    assert msg_long == "FUNDING_OK"


def test_custom_thresholds():
    # Tight threshold: max +0.02%
    rm = RiskManager(RiskConfig(funding_max_long_pct=0.02, funding_min_short_pct=-0.02))
    
    ok_long, _ = rm.funding_rate_ok("BUY", 0.025)
    assert ok_long is False

    ok_long_safe, _ = rm.funding_rate_ok("BUY", 0.015)
    assert ok_long_safe is True
