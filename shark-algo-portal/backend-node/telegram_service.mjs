/**
 * telegram_service.mjs
 * ─────────────────────────────────────────────────────────────────────────────
 * Thin wrapper around node-telegram-bot-api for trade alerts.
 * Phase 1 stub — fully wired in Phase 4 (executor).
 *
 * Usage:
 *   import Telegram from './telegram_service.mjs';
 *   await Telegram.send('🚀 Trade opened: BUY 0.001 BTCUSDT @ 65000');
 * ─────────────────────────────────────────────────────────────────────────────
 */

import 'dotenv/config';
import TelegramBot from 'node-telegram-bot-api';

const { TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID } = process.env;

let _bot = null;

function getBot() {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
    console.warn('[Telegram] BOT_TOKEN or CHAT_ID not set — notifications disabled');
    return null;
  }
  if (!_bot) {
    // polling: false — we only send messages, no incoming command handling in Phase 1
    _bot = new TelegramBot(TELEGRAM_BOT_TOKEN, { polling: false });
  }
  return _bot;
}

/**
 * Send a plain-text or HTML-formatted message to the configured chat.
 * @param {string} text      - message text (supports HTML parse mode)
 * @param {boolean} html     - use HTML parse_mode if true
 * @returns {Promise<boolean>} - true if sent, false if skipped/failed
 */
export async function send(text, html = false) {
  const bot = getBot();
  if (!bot) return false;

  try {
    await bot.sendMessage(TELEGRAM_CHAT_ID, text, {
      parse_mode:               html ? 'HTML' : undefined,
      disable_web_page_preview: true,
    });
    return true;
  } catch (err) {
    console.error('[Telegram] Failed to send message:', err.message);
    return false;
  }
}

/**
 * Pre-built alert templates (will be expanded in Phase 4).
 */
export const Alerts = {
  tradeOpened:  ({ side, qty, pair, price, sl, tp }) =>
    send(`🟢 <b>TRADE OPENED</b>\n${side} ${qty} ${pair}\nEntry: ${price}\nSL: ${sl} | TP: ${tp}`, true),

  tradeClosed:  ({ pair, pnl, reason }) =>
    send(`🔴 <b>TRADE CLOSED</b>\n${pair} | P&L: ${pnl}\nReason: ${reason}`, true),

  regimeChange: ({ from, to }) =>
    send(`🔄 Regime: <b>${from}</b> → <b>${to}</b>`, true),

  killSwitch:   ({ reason }) =>
    send(`🚨 <b>KILL SWITCH TRIGGERED</b>\n${reason}`, true),

  error:        ({ context, message }) =>
    send(`⛔ <b>ERROR</b> [${context}]\n${message}`, true),

  dailySummary: ({ date, pnl, trades, winRate }) =>
    send(
      `📊 <b>Daily Summary ${date}</b>\nP&L: ${pnl}\nTrades: ${trades}\nWin Rate: ${winRate}%`,
      true,
    ),
};

export default { send, Alerts };
