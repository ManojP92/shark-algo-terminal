/**
 * shark_client.mjs
 * ─────────────────────────────────────────────────────────────────────────────
 * Wraps the official shark-exchange-sdk with:
 *   • DRY_RUN mode guard (no live orders unless LIVE=true)
 *   • Retry logic (max 3 attempts with exponential back-off)
 *   • Normalised error objects
 *   • Structured logging via Winston
 *
 * All market data methods return raw SDK responses so callers can rely on
 * the official schema.  Order methods return a consistent shape:
 *   { ok: true,  orderId, symbol, side, type, qty, price, dryRun }
 *   { ok: false, error: <string>, raw: <Error> }
 *
 * References:
 *   Shark Exchange SDK docs — https://docs.sharkexchange.com/sdk/node
 * ─────────────────────────────────────────────────────────────────────────────
 */

import 'dotenv/config';
import pRetry from 'p-retry';
import { createLogger, format, transports } from 'winston';

// ── Logger ───────────────────────────────────────────────────────────────────

const logger = createLogger({
  level: 'debug',
  format: format.combine(
    format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
    format.printf(({ timestamp, level, message, ...meta }) => {
      const extras = Object.keys(meta).length ? ' ' + JSON.stringify(meta) : '';
      return `[${timestamp}] [SHARK-CLIENT] [${level.toUpperCase()}] ${message}${extras}`;
    }),
  ),
  transports: [
    new transports.Console(),
    new transports.File({ filename: '../logs/shark_client.log', maxsize: 5_000_000 }),
  ],
});

// ── Environment ───────────────────────────────────────────────────────────────

const {
  SHARK_API_KEY,
  SHARK_API_SECRET,
  SHARK_BASE_URL = 'https://api.sharkexchange.com',
  DRY_RUN = 'true',
  LIVE = 'false',
  TRADING_PAIR = 'BTCUSDT',
} = process.env;

const IS_DRY_RUN = DRY_RUN !== 'false';   // safe default: dry unless explicitly false
const IS_LIVE    = LIVE === 'true';        // must be explicitly opted in

if (!IS_LIVE && !IS_DRY_RUN) {
  // Edge case guard: DRY_RUN=false + LIVE=false → treat as dry
  logger.warn('DRY_RUN=false but LIVE=false — treating as DRY_RUN. Set LIVE=true to trade.');
}

logger.info(`SharkClient initialising | DRY_RUN=${IS_DRY_RUN} | LIVE=${IS_LIVE} | PAIR=${TRADING_PAIR}`);

// ── SDK Bootstrap ─────────────────────────────────────────────────────────────
// We do a DYNAMIC import of the SDK so this module can be loaded (and tested)
// even if the SDK is not yet installed — the error surfaces only when a method
// is actually called.

let _sdk = null;          // lazily initialised
let _sdkReady = false;

async function getSdk() {
  if (_sdkReady) return _sdk;

  try {
    // shark-exchange-sdk exports a class or factory — adapt to its actual API.
    // Check the installed SDK README/types if this import path needs adjustment.
    const { SharkExchange } = await import('shark-exchange-sdk');

    _sdk = new SharkExchange({
      apiKey:    SHARK_API_KEY,
      apiSecret: SHARK_API_SECRET,
      baseURL:   SHARK_BASE_URL,
    });

    _sdkReady = true;
    logger.info('SharkExchange SDK initialised successfully');
  } catch (err) {
    logger.error('Failed to initialise SharkExchange SDK', { error: err.message });
    throw err;
  }

  return _sdk;
}

// ── Retry helper ──────────────────────────────────────────────────────────────
/**
 * Wraps an async fn with up to `maxRetries` attempts (exponential back-off).
 * @param {() => Promise<any>} fn  - async operation to retry
 * @param {string}             tag - label for log messages
 * @param {number}             maxRetries
 */
async function withRetry(fn, tag, maxRetries = 3) {
  return pRetry(fn, {
    retries: maxRetries,
    onFailedAttempt: (err) => {
      logger.warn(`${tag} failed (attempt ${err.attemptNumber}/${maxRetries + 1})`, {
        error: err.message,
      });
    },
    factor: 2,           // exponential back-off multiplier
    minTimeout: 500,     // 500ms → 1s → 2s
  });
}

// ── Normalised error builder ──────────────────────────────────────────────────
function errResult(message, raw) {
  logger.error(message, { error: raw?.message });
  return { ok: false, error: message, raw };
}

// ═════════════════════════════════════════════════════════════════════════════
//  MARKET DATA METHODS
// ═════════════════════════════════════════════════════════════════════════════

/**
 * Fetch OHLCV klines from Shark Exchange.
 *
 * @param {object} opts
 * @param {string} opts.pair       - e.g. "BTCUSDT"
 * @param {string} opts.interval   - e.g. "5m", "15m", "1h"
 * @param {number} opts.limit      - number of candles (default 200, max 1000)
 * @param {number} [opts.startTime] - Unix ms timestamp — fetch from this point forward
 * @param {number} [opts.endTime]   - Unix ms timestamp — fetch up to this point
 * @returns {Promise<Array>}        - array of kline objects from SDK
 *
 * Kline object shape (confirmed via SDK introspection):
 *   { startTime, open, high, low, close, volume, endTime }
 */
export async function fetchKlines({
  pair      = TRADING_PAIR,
  interval,
  limit     = 200,
  startTime,
  endTime,
} = {}) {
  if (!interval) throw new Error('fetchKlines: interval is required (e.g. "5m")');

  const sdk = await getSdk();
  logger.debug('fetchKlines', { pair, interval, limit, startTime, endTime });

  // Build SDK params — only include time params if provided
  const params = { pair, interval, limit };
  if (startTime !== undefined) params.startTime = startTime;
  if (endTime   !== undefined) params.endTime   = endTime;

  return withRetry(
    () => sdk.market.klines(params),
    `fetchKlines(${pair} ${interval})`,
  );
}

/**
 * Fetch current account balances from the futures wallet.
 * Uses sdk.wallet.futures() — the correct Shark SDK method.
 * Returns the full SDK wallet object.
 */
export async function fetchBalance() {
  const sdk = await getSdk();
  logger.debug('fetchBalance called');

  return withRetry(
    () => sdk.wallet.futures(),
    'fetchBalance (wallet.futures)',
  );
}

/**
 * Fetch 24hr ticker for a pair.
 * Uses sdk.market.ticker24Hr({ pair }) — the correct Shark SDK method.
 * @param {string} pair
 */
export async function fetchTicker(pair = TRADING_PAIR) {
  const sdk = await getSdk();
  logger.debug('fetchTicker', { pair });

  return withRetry(
    () => sdk.market.ticker24Hr({ contractPair: pair }),
    `fetchTicker(${pair})`,
  );
}


// ═════════════════════════════════════════════════════════════════════════════
//  ORDER METHODS  (DRY_RUN GUARDED)
// ═════════════════════════════════════════════════════════════════════════════

/**
 * Place a MARKET order (buy or sell).
 *
 * In DRY_RUN mode: logs the intended order and returns a synthetic result.
 * In LIVE mode (LIVE=true + DRY_RUN=false): sends to exchange.
 *
 * @param {object} opts
 * @param {string}  opts.pair   - trading pair, e.g. "BTCUSDT"
 * @param {'BUY'|'SELL'} opts.side
 * @param {number}  opts.qty    - quantity in base currency (BTC)
 * @param {string}  [opts.clientOrderId] - optional idempotency key
 *
 * @returns {Promise<{ok, orderId, symbol, side, type, qty, price, dryRun}>}
 */
export async function placeMarketOrder({ pair = TRADING_PAIR, side, qty, clientOrderId } = {}) {
  if (!side || !qty) throw new Error('placeMarketOrder: side and qty are required');
  if (!['BUY', 'SELL'].includes(side.toUpperCase())) {
    throw new Error(`placeMarketOrder: invalid side "${side}"`);
  }

  const normalSide = side.toUpperCase();

  // ── DRY RUN path ──────────────────────────────────────────────────────────
  if (IS_DRY_RUN || !IS_LIVE) {
    const synthetic = {
      ok:        true,
      orderId:   `DRY-${Date.now()}`,
      symbol:    pair,
      side:      normalSide,
      type:      'MARKET',
      qty,
      price:     null,   // market order — price unknown pre-fill
      dryRun:    true,
      timestamp: new Date().toISOString(),
    };
    logger.info('[DRY-RUN] Market order simulated', synthetic);
    return synthetic;
  }

  // ── LIVE path ─────────────────────────────────────────────────────────────
  logger.warn(`LIVE ORDER — ${normalSide} ${qty} ${pair}`);

  try {
    const sdk = await getSdk();
    const result = await withRetry(
      () => sdk.orders.placeMarket({ pair, side: normalSide, qty, clientOrderId }),
      `placeMarketOrder(${normalSide} ${qty} ${pair})`,
    );

    logger.info('Market order placed', { orderId: result.orderId, pair, side: normalSide, qty });
    return {
      ok:        true,
      orderId:   result.orderId,
      symbol:    pair,
      side:      normalSide,
      type:      'MARKET',
      qty,
      price:     result.price ?? null,
      dryRun:    false,
      timestamp: new Date().toISOString(),
      raw:       result,
    };
  } catch (err) {
    return errResult(`placeMarketOrder failed: ${err.message}`, err);
  }
}

/**
 * Close an open position by placing an opposing market order.
 *
 * @param {object} opts
 * @param {string}  opts.pair       - e.g. "BTCUSDT"
 * @param {'BUY'|'SELL'} opts.currentSide - the side of the open position
 * @param {number}  opts.qty        - quantity to close
 */
export async function closePosition({ pair = TRADING_PAIR, currentSide, qty } = {}) {
  if (!currentSide || !qty) throw new Error('closePosition: currentSide and qty are required');

  const closingSide = currentSide.toUpperCase() === 'BUY' ? 'SELL' : 'BUY';
  logger.info('closePosition', { pair, closingSide, qty });

  return placeMarketOrder({ pair, side: closingSide, qty });
}

/**
 * Place a LIMIT order.
 *
 * @param {object} opts
 * @param {string}  opts.pair
 * @param {'BUY'|'SELL'} opts.side
 * @param {number}  opts.qty
 * @param {number}  opts.price
 */
export async function placeLimitOrder({ pair = TRADING_PAIR, side, qty, price } = {}) {
  if (!side || !qty || !price) {
    throw new Error('placeLimitOrder: side, qty, and price are required');
  }

  const normalSide = side.toUpperCase();

  if (IS_DRY_RUN || !IS_LIVE) {
    const synthetic = {
      ok:        true,
      orderId:   `DRY-LMT-${Date.now()}`,
      symbol:    pair,
      side:      normalSide,
      type:      'LIMIT',
      qty,
      price,
      dryRun:    true,
      timestamp: new Date().toISOString(),
    };
    logger.info('[DRY-RUN] Limit order simulated', synthetic);
    return synthetic;
  }

  try {
    const sdk = await getSdk();
    const result = await withRetry(
      () => sdk.orders.placeLimit({ pair, side: normalSide, qty, price }),
      `placeLimitOrder(${normalSide} ${qty} ${pair} @ ${price})`,
    );

    return {
      ok:      true,
      orderId: result.orderId,
      symbol:  pair,
      side:    normalSide,
      type:    'LIMIT',
      qty,
      price,
      dryRun:  false,
      raw:     result,
    };
  } catch (err) {
    return errResult(`placeLimitOrder failed: ${err.message}`, err);
  }
}

/**
 * Cancel an open order by orderId.
 * @param {object} opts
 * @param {string}  opts.pair
 * @param {string}  opts.orderId
 */
export async function cancelOrder({ pair = TRADING_PAIR, orderId } = {}) {
  if (!orderId) throw new Error('cancelOrder: orderId is required');

  if (IS_DRY_RUN || !IS_LIVE) {
    logger.info('[DRY-RUN] Cancel order simulated', { pair, orderId });
    return { ok: true, orderId, dryRun: true };
  }

  try {
    const sdk = await getSdk();
    const result = await withRetry(
      () => sdk.orders.delete({ pair, orderId }),
      `cancelOrder(${orderId})`,
    );
    logger.info('Order cancelled', { orderId });
    return { ok: true, orderId, dryRun: false, raw: result };
  } catch (err) {
    return errResult(`cancelOrder failed: ${err.message}`, err);
  }
}

// ── Named exports for convenience ─────────────────────────────────────────────
export const SharkClient = {
  fetchKlines,
  fetchBalance,
  fetchTicker,
  placeMarketOrder,
  closePosition,
  placeLimitOrder,
  cancelOrder,
  isDryRun: IS_DRY_RUN,
  isLive:   IS_LIVE,
  pair:     TRADING_PAIR,
};

export default SharkClient;
