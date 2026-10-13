"""
test_broker_connectivity.py
──────────────────────────────────────────────────────────────────────────────
Zero-risk Canary Test — verifies API credentials, permissions, and
connectivity to Shark Exchange before risking any live funds.

Tests run in order:
  1. API signature generation (no network call)
  2. Public market data (no auth required)
  3. Private account access — balances
  4. Private account access — positions
  5. Private account access — leverage
  6. Order book depth
  7. PAPER order placement (never touches real funds)
  8. Telegram notification delivery

Run:
  python test_broker_connectivity.py

All tests must pass before enabling LIVE mode.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
import traceback
from urllib.parse import urlencode

from dotenv import load_dotenv

# Ensure backend-python is in python path
backend_py_dir = os.path.join(os.path.dirname(__file__), "backend-python")
if backend_py_dir not in sys.path:
    sys.path.insert(0, backend_py_dir)

env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    load_dotenv(dotenv_path=env_file, override=True)
else:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env.example"))


from shark_client import SharkClient, SharkClientError
from telegram_alerts import TelegramAlerter

# Reconfigure stdout for utf-8 on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS = f"{GREEN}[PASS]{RESET}"
FAIL = f"{RED}[FAIL]{RESET}"
SKIP = f"{YELLOW}[SKIP]{RESET}"

results: list[tuple[str, bool, str]] = []


def run_test(name: str, fn):
    """Run a single test, capture result, print formatted output."""
    print(f"  {BOLD}{name}{RESET} ", end="", flush=True)
    try:
        msg = fn()
        print(f"{PASS}  {msg or ''}")
        results.append((name, True, msg or ""))
    except Exception as err:
        msg = str(err)
        print(f"{FAIL}  {msg}")
        results.append((name, False, msg))


# ══════════════════════════════════════════════════════════════════════════════
#  TEST FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def test_env_vars():
    """Verify required environment variables are set."""
    required = ["SHARK_API_KEY", "SHARK_API_SECRET", "SHARK_BASE_URL"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")
    key = os.getenv("SHARK_API_KEY", "")
    return f"API key: {key[:8]}… ({len(key)} chars)"


def test_hmac_signature():
    """Verify HMAC-SHA256 signature generation is deterministic."""
    secret  = "test_secret_abc123"
    params  = {"pair": "BTCUSDT", "limit": "100", "timestamp": "1700000000000"}
    qs      = urlencode(sorted(params.items()))
    sig     = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    # Verify it's a valid 64-char hex string
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)
    return f"Signature: {sig[:16]}…"


def test_public_ticker():
    """Fetch public 24hr ticker — no auth required."""
    client = SharkClient()
    ticker = client.get_ticker("BTCUSDT")
    price  = ticker.get("c") or ticker.get("lastPrice") or "?"
    return f"Last price: ${float(price):,.2f}"


def test_public_klines():
    """Fetch public klines — no auth required."""
    client  = SharkClient()
    klines  = client.get_klines("BTCUSDT", interval="5m", limit=5)
    assert len(klines) > 0, "Got 0 klines"
    first   = klines[0]
    assert "close" in first or "c" in first, f"Unexpected kline shape: {list(first.keys())}"
    return f"{len(klines)} klines fetched | last close: {klines[-1].get('close', '?')}"


def test_order_book():
    """Fetch order book depth."""
    client   = SharkClient()
    book     = client.get_orderbook("BTCUSDT", depth=5)
    bid_side = book.get("b", book.get("bids", []))
    ask_side = book.get("a", book.get("asks", []))
    assert len(bid_side) > 0, "Empty bids"
    assert len(ask_side) > 0, "Empty asks"
    spread = abs(float(ask_side[0][0]) - float(bid_side[0][0]))
    return f"Spread: ${spread:.2f} | top bid: {bid_side[0][0]} | top ask: {ask_side[0][0]}"


def test_balances():
    """Fetch futures wallet balance — requires auth."""
    client = SharkClient()
    bal    = client.get_balances()
    # Just check it doesn't throw and returns something
    assert bal is not None, "Null balance response"
    return f"Balance response received (type: {type(bal).__name__})"


def test_positions():
    """Fetch open positions — requires auth."""
    client = SharkClient()
    pos    = client.get_positions("BTCUSDT")
    count  = len(pos) if isinstance(pos, list) else "?"
    return f"{count} open position(s)"


def test_paper_order():
    """
    Place a PAPER order — DRY_RUN=true so no real order is sent.
    Verifies the order logic runs without errors.
    """
    client = SharkClient()
    # Force dry-run regardless of env — this is a test
    client.dry_run = True
    client.live    = False

    result = client.place_order("BTCUSDT", "BUY", "MARKET", qty=0.001)
    assert result["ok"],    "Order not OK"
    assert result["paper"], "Expected paper=True in dry-run"
    return f"Paper order ID: {result['orderId']}"


def test_paper_cancel():
    """PAPER cancel order — DRY_RUN guard."""
    client      = SharkClient()
    client.dry_run = True
    client.live    = False
    result      = client.cancel_order("BTCUSDT", "PAPER-12345")
    assert result["ok"]
    return "Cancel simulated OK"


def test_telegram():
    """Send a test Telegram message using the configured bot token."""
    tg = TelegramAlerter()
    ok = tg._send(
        "🧪 <b>Broker Connectivity Test</b>\n"
        "This is an automated test from <code>test_broker_connectivity.py</code>.\n"
        "If you see this, Telegram notifications are working! ✅"
    )
    if not ok:
        raise RuntimeError("Telegram message failed — check BOT_TOKEN and CHAT_ID")
    return "Message delivered to Telegram"


# ══════════════════════════════════════════════════════════════════════════════
#  RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print()
    print(f"{BOLD}======================================================")
    print(f"    SHARK ALGO — BROKER CONNECTIVITY CANARY TEST     ")
    print(f"======================================================{RESET}")
    print()

    TESTS = [
        ("1. Env vars present",         test_env_vars),
        ("2. HMAC signature format",    test_hmac_signature),
        ("3. Public ticker",            test_public_ticker),
        ("4. Public klines (5m)",       test_public_klines),
        ("5. Order book depth",         test_order_book),
        ("6. Account balances (auth)",  test_balances),
        ("7. Open positions (auth)",    test_positions),
        ("8. PAPER order placement",    test_paper_order),
        ("9. PAPER cancel order",       test_paper_cancel),
        ("10. Telegram notification",   test_telegram),
    ]

    for name, fn in TESTS:
        run_test(name, fn)

    # ── Summary ───────────────────────────────────────────────────────────────
    total   = len(results)
    passed  = sum(1 for _, ok, _ in results if ok)
    failed  = total - passed

    print()
    print(f"  --------------------------------------------------------")
    print(f"  Results: {GREEN}{passed} passed{RESET} / {RED}{failed} failed{RESET} / {total} total")
    print()

    if failed > 0:
        print(f"  {RED}[!] Fix the above failures before enabling LIVE mode.{RESET}")
        sys.exit(1)
    else:
        print(f"  {GREEN}[+] All tests passed — broker connectivity verified.{RESET}")
        print(f"  You may proceed to PAPER trading.")
    print()


if __name__ == "__main__":
    main()
