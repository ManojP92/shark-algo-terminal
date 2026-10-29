"""
telegram_commander.py
──────────────────────────────────────────────────────────────────────────────
Two-Way Interactive Telegram Remote Control for Shark Algo Terminal.
Listens for incoming commands from the authorized user via Telegram getUpdates long-polling.

Commands:
  /status    - Real-time bot status, open position, PnL, regime, wallet
  /balance   - Current wallet balance & equity
  /start     - Resume automated trading engine
  /stop      - Pause trading engine (blocks new entries)
  /live      - Switch execution mode to LIVE trading
  /paper     - Switch execution mode to PAPER trading
  /flatten   - Emergency close all open positions and pause
  /strategy  - Switch strategy (donchian, supertrend, rsi, regime)
  /pair      - Switch trading pair (BTCUSDT, ETHUSDT, SOLUSDT)
  /help      - Display clickable commands menu
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional, Any

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

log = logging.getLogger("tg_commander")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [TG-CMD] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


class TelegramCommander:
    def __init__(self, get_executor: Callable[[], Any], token: str = BOT_TOKEN, chat_id: str = CHAT_ID):
        self.get_executor = get_executor
        self.token = token
        self.chat_id = str(chat_id).strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_update_id = 0

    def start(self):
        if not self.token or not self.chat_id:
            log.warning("Telegram credentials missing — Telegram command listener disabled")
            return
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        log.info("Telegram command listener started for authorized Chat ID: %s", self.chat_id)

    def stop(self):
        self.running = False

    def send_message(self, text: str, reply_to_id: Optional[int] = None) -> bool:
        if not self.token or not self.chat_id:
            return False
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if reply_to_id:
                payload["reply_to_message_id"] = reply_to_id
            resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as err:
            log.error("Failed to send Telegram message: %s", err)
            return False

    def _poll_loop(self):
        # Initial offset fetch to discard stale commands from earlier
        try:
            r = requests.get(f"{self.base_url}/getUpdates?offset=-1", timeout=10).json()
            if r.get("ok") and r.get("result"):
                self.last_update_id = r["result"][-1]["update_id"] + 1
        except Exception:
            pass

        while self.running:
            try:
                url = f"{self.base_url}/getUpdates?offset={self.last_update_id}&timeout=20"
                resp = requests.get(url, timeout=25)
                if resp.status_code != 200:
                    time.sleep(3)
                    continue

                data = resp.json()
                if not data.get("ok"):
                    time.sleep(3)
                    continue

                for update in data.get("result", []):
                    self.last_update_id = update["update_id"] + 1
                    msg = update.get("message") or update.get("edited_message")
                    if not msg:
                        continue

                    sender_id = str(msg.get("from", {}).get("id") or msg.get("chat", {}).get("id"))
                    # SECURITY: Only authorized chat ID can execute commands
                    if sender_id != self.chat_id:
                        log.warning("Unauthorized command attempt from user ID: %s (Ignored)", sender_id)
                        continue

                    text = (msg.get("text") or "").strip()
                    if text.startswith("/"):
                        self._handle_command(text, msg.get("message_id"))

            except requests.RequestException:
                time.sleep(4)
            except Exception as err:
                log.error("Error in Telegram poll loop: %s", err)
                time.sleep(3)

    def _handle_command(self, text: str, msg_id: Optional[int]):
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]  # strip @botname if sent in group
        args = parts[1:] if len(parts) > 1 else []

        executor = self.get_executor()
        if executor is None:
            self.send_message("⚠️ <b>Shark Engine Initializing</b> — please wait 5 seconds and retry.", msg_id)
            return

        if cmd in ("/status", "/stats", "/s"):
            self._cmd_status(executor, msg_id)
        elif cmd in ("/balance", "/bal", "/wallet"):
            self._cmd_balance(executor, msg_id)
        elif cmd in ("/start", "/resume"):
            self._cmd_start(executor, msg_id)
        elif cmd in ("/stop", "/pause"):
            self._cmd_stop(executor, msg_id)
        elif cmd == "/live":
            self._cmd_live(executor, msg_id)
        elif cmd == "/paper":
            self._cmd_paper(executor, msg_id)
        elif cmd in ("/close", "/exit"):
            self._cmd_close(executor, msg_id)
        elif cmd in ("/flatten", "/panic"):
            self._cmd_flatten(executor, msg_id)
        elif cmd in ("/reset", "/reset_wallet"):
            self._cmd_reset(executor, args, msg_id)
        elif cmd in ("/strategy", "/strat"):

            self._cmd_strategy(executor, args, msg_id)
        elif cmd in ("/pair", "/symbol"):
            self._cmd_pair(executor, args, msg_id)
        elif cmd in ("/help", "/commands", "/h"):
            self._cmd_help(msg_id)
        else:
            self.send_message(f"❓ Unknown command <code>{cmd}</code>. Type /help to see all commands.", msg_id)

    # ── Command Handlers ──────────────────────────────────────────────────────

    def _cmd_status(self, executor, msg_id):
        st = executor.get_status()
        mode_badge = "🔴 <b>LIVE</b>" if st.get("mode") == "LIVE" else "📋 <b>PAPER</b>"
        state_badge = "🟢 <b>ACTIVE</b>" if st.get("running") and not getattr(executor, "_paused", False) else "⏸️ <b>PAUSED</b>"
        equity = st.get("equity", 0.0)
        wallet = st.get("wallet", {}).get("balance", equity)
        pos = st.get("position")
        stats = st.get("stats", {})
        market = st.get("market", {})
        pair = st.get("symbol", "BTCUSDT")
        strat = st.get("strategy_title", st.get("strategy", "DONCHIAN"))
        regime = market.get("regime", "UNKNOWN")

        pos_text = "⚪ <i>Flat — No Open Position</i>"
        if pos:
            side_emoji = "🟢" if pos.get("side") == "LONG" else "🔴"
            pnl = pos.get("unrealized_pnl", 0.0)
            pnl_pct = pos.get("pnl_pct", 0.0)
            pnl_str = f"+${pnl:.2f} (+{pnl_pct:.2f}%)" if pnl >= 0 else f"-${abs(pnl):.2f} ({pnl_pct:.2f}%)"
            pos_text = (
                f"{side_emoji} <b>{pos.get('side')} {pos.get('qty')} {pair}</b>\n"
                f"   • Entry: <code>${pos.get('entry'):,.2f}</code>\n"
                f"   • Mark: <code>${pos.get('mark_price'):,.2f}</code>\n"
                f"   • PnL: <b>{pnl_str}</b>\n"
                f"   • Trailing SL: <code>${pos.get('trail_sl'):,.2f}</code>"
            )

        daily_pnl = stats.get("daily_pnl", 0.0)
        daily_pnl_str = f"+${daily_pnl:.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):.2f}"

        msg = (
            "🦈 <b>SHARK ALGO TERMINAL STATUS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ <b>Execution:</b> {mode_badge} | {state_badge}\n"
            f"💱 <b>Instrument:</b> <code>{pair}</code> (15m)\n"
            f"🧠 <b>Strategy:</b> {strat}\n"
            f"🌊 <b>Regime:</b> {regime} (ADX: {market.get('adx', 0):.1f})\n"
            f"💰 <b>Wallet Balance:</b> <b>${wallet:,.2f} USDT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Active Position:</b>\n{pos_text}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Today's Trades:</b> {stats.get('trades', 0)} ({stats.get('wins', 0)} Wins | {stats.get('win_rate', 0):.1f}%)\n"
            f"💵 <b>Daily PnL:</b> <b>{daily_pnl_str}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Commands: /stop | /start | /live | /paper | /flatten</i>"
        )
        self.send_message(msg, msg_id)

    def _cmd_balance(self, executor, msg_id):
        equity = executor.get_equity()
        mode = executor.mode
        msg = (
            "💰 <b>SHARK WALLET DETAILS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Current Balance:</b> <b>${equity:,.2f} USDT</b>\n"
            f"⚙️ <b>Mode:</b> {mode}\n"
            f"🎯 <b>Max Risk / Trade:</b> {executor.rm.cfg.risk_per_trade_pct}%\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        self.send_message(msg, msg_id)

    def _cmd_start(self, executor, msg_id):
        executor._running = True
        executor.rm.state.halted = False
        executor.rm.state.cooldown_until_ts = 0.0
        executor._log_event("Engine RESUMED via Telegram command")
        self.send_message(
            "▶️ <b>TRADING ENGINE RESUMED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Autonomous order evaluation is now <b>ACTIVE</b>.\n"
            "🛡️ Circuit breaker halts cleared.\n"
            f"Mode: <b>{executor.mode}</b> | Pair: <b>{executor.symbol}</b>",
            msg_id,
        )

    def _cmd_reset(self, executor, args, msg_id):
        amount = 100.0
        if args:
            try:
                amount = float(args[0])
            except ValueError:
                pass
        executor.paper_wallet = amount
        executor.rm.cfg.capital_base = amount
        executor.rm.state.day_start_equity = amount
        executor.rm.state.daily_pnl = 0.0
        executor.rm.state.halted = False
        executor.rm.state.consecutive_losses = 0
        executor._stats["daily_pnl"] = 0.0
        executor._save_paper_state()
        executor._log_event(f"Paper wallet balance reset to ${amount:.2f}")
        self.send_message(
            "🔄 <b>PAPER WALLET RESET</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 New Balance: <b>${amount:,.2f} USDT</b>\n"
            "Daily P&L and circuit breaker metrics reset.",
            msg_id,
        )

    def _cmd_stop(self, executor, msg_id):
        executor._running = False
        executor._log_event("Engine PAUSED via Telegram command")
        self.send_message(
            "⏸️ <b>TRADING ENGINE PAUSED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛑 New trade entries are blocked.\n"
            "Existing open positions and trailing stops remain active.\n"
            "Use /start to resume anytime.",
            msg_id,
        )

    def _cmd_live(self, executor, msg_id):
        executor.set_mode("LIVE")
        self.send_message(
            "🔴 <b>SWITCHED TO LIVE TRADING MODE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>CAUTION:</b> Real order execution on Shark Exchange is now <b>ARMED</b>.\n"
            "Real funds will be risked on new signals.\n"
            "Use /paper to return to safety sandbox anytime.",
            msg_id,
        )

    def _cmd_paper(self, executor, msg_id):
        executor.set_mode("PAPER")
        self.send_message(
            "📋 <b>SWITCHED TO PAPER TRADING MODE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ Sandbox simulation active.\n"
            "Zero risk to real wallet funds. Compounding paper wallet active.",
            msg_id,
        )

    def _cmd_close(self, executor, msg_id):
        if not executor.position:
            self.send_message("ℹ️ No active position to close.", msg_id)
            return
        pos = executor.position
        res = executor.close_position(reason="Telegram /close command")
        exit_px = res.get("exit", 0.0)
        self.send_message(
            "✅ <b>POSITION CLOSED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Pair: <b>{pos.symbol}</b> ({pos.side})\n"
            f"Qty: <code>{pos.qty}</code> @ Entry: ${pos.entry:,.2f}\n"
            f"Exit: ${exit_px:,.2f}\n"
            "Status: Market exit executed.\n"
            "Bot remains active for next setup.",
            msg_id,
        )

    def _cmd_flatten(self, executor, msg_id):
        symbol = executor.symbol
        result = executor.flatten(reason="Telegram /flatten command")
        self.send_message(
            "🆘 <b>EMERGENCY FLATTEN COMPLETED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ All positions in <b>{symbol}</b> have been market closed.\n"
            "🛑 Bot execution paused for capital protection.\n"
            "Use /start to resume when ready.",
            msg_id,
        )


    def _cmd_strategy(self, executor, args, msg_id):
        valid = {
            "regime": "REGIME_ADAPTIVE",
            "adaptive": "REGIME_ADAPTIVE",
            "donchian": "DONCHIAN",
            "supertrend": "SUPERTREND",
            "rsi": "BOLLINGER_RSI",
            "bollinger": "BOLLINGER_RSI",
        }
        if not args:
            cur = executor.strategy_name
            self.send_message(
                f"🧠 <b>Current Strategy:</b> <code>{cur}</code>\n\n"
                "To switch strategy, send:\n"
                "• <code>/strategy regime</code> — Regime-Adaptive (Recommended)\n"
                "• <code>/strategy donchian</code> — Donchian Breakout\n"
                "• <code>/strategy supertrend</code> — Supertrend Momentum\n"
                "• <code>/strategy rsi</code> — Bollinger Bands + RSI Reversion",
                msg_id,
            )
            return

        choice = args[0].lower().strip()
        strat_key = valid.get(choice)
        if not strat_key:
            self.send_message("❌ Unknown strategy. Options: <code>regime</code>, <code>donchian</code>, <code>supertrend</code>, <code>rsi</code>", msg_id)
            return

        executor.set_strategy(strat_key)
        self.send_message(
            f"✅ <b>STRATEGY SWITCHED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Active Model: <b>{strat_key}</b>\n"
            f"Title: {getattr(executor.strategy, 'name', strat_key)}",
            msg_id,
        )

    def _cmd_pair(self, executor, args, msg_id):
        if not args:
            self.send_message(
                f"💱 <b>Active Pair:</b> <code>{executor.symbol}</code>\n\n"
                "To switch pair, send:\n"
                "• <code>/pair btc</code> (BTC/USDT)\n"
                "• <code>/pair sol</code> (SOL/USDT)\n"
                "• <code>/pair eth</code> (ETH/USDT)",
                msg_id,
            )
            return

        raw = args[0].upper().strip()
        pair_map = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
        target = pair_map.get(raw, raw if raw.endswith("USDT") else f"{raw}USDT")

        if executor.position is not None:
            self.send_message(f"⚠️ Cannot switch instrument while position is open in {executor.symbol}! Close position first.", msg_id)
            return

        from executor import INSTRUMENT_CONFIGS
        if target not in INSTRUMENT_CONFIGS:
            self.send_message(f"❌ Unsupported instrument {target}. Supported: BTCUSDT, ETHUSDT, SOLUSDT", msg_id)
            return

        executor.set_symbol(target) if hasattr(executor, "set_symbol") else setattr(executor, "symbol", target)
        if hasattr(executor, "_apply_instrument_config"):
            executor._apply_instrument_config(target)

        self.send_message(
            f"✅ <b>INSTRUMENT SWITCHED</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Active Trading Pair: <code>{target}</code>\n"
            f"Min Capital: ${INSTRUMENT_CONFIGS[target]['min_capital']}+",
            msg_id,
        )

    def _cmd_help(self, msg_id):
        menu = (
            "🦈 <b>SHARK QUANT COMMAND MENU</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 /status — View bot state, open position & PnL\n"
            "💰 /balance — Check wallet balance & equity\n"
            "▶️ /start — Resume automated trading engine\n"
            "⏸️ /stop — Pause bot (blocks new entries)\n"
            "🔴 /live — Switch execution mode to LIVE\n"
            "📋 /paper — Switch execution mode to PAPER\n"
            "✅ /close — Market exit active position (keeps bot running)\n"
            "🆘 /flatten — Emergency close all positions & pause bot\n"
            "🧠 /strategy — View or change strategy model\n"

            "💱 /pair — View or change trading instrument\n"
            "❓ /help — Show this command menu\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Commands are protected and only respond to your Telegram account.</i>"
        )
        self.send_message(menu, msg_id)
