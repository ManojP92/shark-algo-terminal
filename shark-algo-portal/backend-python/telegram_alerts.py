"""
telegram_alerts.py
──────────────────────────────────────────────────────────────────────────────
Python Telegram notification module.
Reuses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env — same credentials
as the Node telegram_service.mjs.

Sends rich HTML-formatted alerts for:
  • Trade entry / exit
  • Trailing stop adjustment
  • Circuit breaker triggers (daily cap, cooldown, emergency flatten)
  • Daily P&L summary

Usage:
  from telegram_alerts import TelegramAlerter
  tg = TelegramAlerter()
  tg.trade_opened(side="LONG", symbol="BTCUSDT", qty=0.01,
                  entry=65000, sl=63800, trail_sl=62000, atr=400)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("telegram_alerts")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
API_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


class TelegramAlerter:
    """Sends HTML-formatted Telegram messages to the configured chat."""

    def __init__(
        self,
        token:   str = BOT_TOKEN,
        chat_id: str = CHAT_ID,
        paper:   bool = True,
    ):
        self.token   = token
        self.chat_id = chat_id
        self.paper   = paper
        self._url    = f"https://api.telegram.org/bot{self.token}/sendMessage"

        if not self.token or not self.chat_id:
            log.warning("Telegram credentials not set — notifications disabled")

    def _send(self, html: str) -> bool:
        """Send a raw HTML-formatted message."""
        if not self.token or not self.chat_id:
            return False
        mode = "📋 <b>[PAPER]</b> " if self.paper else "🔴 <b>[LIVE]</b> "
        try:
            resp = requests.post(
                self._url,
                json={
                    "chat_id":                  self.chat_id,
                    "text":                     mode + html,
                    "parse_mode":               "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as err:
            log.error("Telegram send failed: %s", err)
            return False

    # ── Alert templates ──────────────────────────────────────────────────────

    def trade_opened(
        self,
        side:     str,
        symbol:   str,
        qty:      float,
        entry:    float,
        sl:       float,
        trail_sl: float,
        atr:      float,
        adx:      float,
        reason:   str = "",
    ) -> bool:
        emoji = "🟢" if side == "LONG" else "🔴"
        return self._send(
            f"{emoji} <b>TRADE OPENED — {side}</b>\n"
            f"<b>Pair:</b> {symbol}  |  <b>Qty:</b> {qty:.6f}\n"
            f"<b>Entry:</b> ${entry:,.2f}\n"
            f"<b>Initial SL:</b> ${sl:,.2f}\n"
            f"<b>Trail SL:</b>  ${trail_sl:,.2f}\n"
            f"<b>ATR:</b> {atr:.2f}  |  <b>ADX:</b> {adx:.2f}\n"
            f"<i>{reason}</i>"
        )

    def trade_closed(
        self,
        side:   str,
        symbol: str,
        qty:    float,
        entry:  float,
        exit_:  float,
        pnl:    float,
        reason: str,
    ) -> bool:
        emoji = "✅" if pnl >= 0 else "❌"
        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        return self._send(
            f"{emoji} <b>TRADE CLOSED — {side}</b>\n"
            f"<b>Pair:</b> {symbol}  |  <b>Qty:</b> {qty:.6f}\n"
            f"<b>Entry:</b> ${entry:,.2f}  →  <b>Exit:</b> ${exit_:,.2f}\n"
            f"<b>P&amp;L:</b> {pnl_str}\n"
            f"<b>Reason:</b> {reason}"
        )

    def trailing_stop_updated(
        self,
        symbol:   str,
        side:     str,
        new_sl:   float,
        best_px:  float,
    ) -> bool:
        return self._send(
            f"📈 <b>Trailing Stop Updated</b>\n"
            f"<b>{symbol}</b> {side}\n"
            f"<b>Best price:</b> ${best_px:,.2f}\n"
            f"<b>New trail SL:</b> ${new_sl:,.2f}"
        )

    def scale_out(
        self,
        symbol: str,
        side:   str,
        qty:    float,
        price:  float,
    ) -> bool:
        return self._send(
            f"⚡ <b>Scale-Out (50% close)</b>\n"
            f"<b>{symbol}</b> {side} — closed {qty:.6f} @ ${price:,.2f}\n"
            f"Remaining half at Break-Even stop"
        )

    def circuit_breaker(self, reason: str) -> bool:
        return self._send(
            f"🚨 <b>CIRCUIT BREAKER TRIGGERED</b>\n"
            f"{reason}\n"
            f"All new trades blocked."
        )

    def emergency_flatten(self, symbol: str, reason: str) -> bool:
        return self._send(
            f"🆘 <b>EMERGENCY FLATTEN</b>\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Reason:</b> {reason}\n"
            f"All positions closed. Bot halted."
        )

    def daily_summary(
        self,
        date:     str,
        pnl:      float,
        trades:   int,
        wins:     int,
        equity:   float,
    ) -> bool:
        win_rate = (wins / trades * 100) if trades > 0 else 0
        pnl_str  = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        return self._send(
            f"📊 <b>Daily Summary — {date}</b>\n"
            f"<b>P&amp;L:</b> {pnl_str}\n"
            f"<b>Trades:</b> {trades}  |  <b>Wins:</b> {wins}  ({win_rate:.1f}%)\n"
            f"<b>Equity:</b> ${equity:,.2f}"
        )

    def bot_started(self, mode: str, symbol: str) -> bool:
        return self._send(
            f"🚀 <b>Bot Started</b>\n"
            f"<b>Mode:</b> {mode}\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"Donchian Breakout Engine active."
        )

    def bot_stopped(self, reason: str = "Manual stop") -> bool:
        return self._send(
            f"⏹ <b>Bot Stopped</b>\n"
            f"<b>Reason:</b> {reason}"
        )
