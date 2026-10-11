/**
 * server.mjs
 * ─────────────────────────────────────────────────────────────────────────────
 * Phase 1/2 — Express + Socket.IO server
 * Exposes REST endpoints for the dashboard and Python bridge.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import 'dotenv/config';
import express from 'express';
import { createServer } from 'http';
import { Server as IOServer } from 'socket.io';
import cors from 'cors';
import { createLogger, format, transports } from 'winston';
import SharkClient, { fetchKlines } from './shark_client.mjs';

const app    = express();
const http   = createServer(app);
const io     = new IOServer(http, { cors: { origin: '*' } });
const PORT   = process.env.PORT ?? 3001;

const logger = createLogger({
  level: 'info',
  format: format.combine(
    format.timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
    format.printf(({ timestamp, level, message }) =>
      `[${timestamp}] [SERVER] [${level.toUpperCase()}] ${message}`),
  ),
  transports: [new transports.Console()],
});

// ── Middleware ─────────────────────────────────────────────────────────────────
app.use(cors());
app.use(express.json());

// ── Health check ───────────────────────────────────────────────────────────────
app.get('/health', (_req, res) => {
  res.json({
    status:    'ok',
    dryRun:    SharkClient.isDryRun,
    live:      SharkClient.isLive,
    pair:      SharkClient.pair,
    timestamp: new Date().toISOString(),
  });
});

// ── Market data endpoints ──────────────────────────────────────────────────────
app.get('/api/klines/:interval', async (req, res) => {
  try {
    const { interval } = req.params;
    const limit = parseInt(req.query.limit ?? '200', 10);
    const data  = await fetchKlines({ interval, limit });
    res.json({ ok: true, data });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// ── Historical klines (paginated) — used by Phase 2 regime detector ───────────
/**
 * GET /api/klines/history?interval=15m&days=30&pair=BTCUSDT
 *
 * Fetches up to `days` days of historical klines using startTime pagination.
 * Each page fetches up to 1000 candles (SDK max). Pages are concatenated,
 * deduplicated by startTime, and returned sorted oldest-first.
 *
 * Response: { ok, count, rangeStart, rangeEnd, data: [...klines] }
 */
app.get('/api/klines/history', async (req, res) => {
  try {
    const interval  = req.query.interval  ?? '15m';
    const days      = parseInt(req.query.days  ?? '30', 10);
    const pair      = req.query.pair      ?? process.env.TRADING_PAIR ?? 'BTCUSDT';
    const PAGE_SIZE = 1000;   // SDK maximum per call

    // Interval → milliseconds lookup
    const intervalMs = {
      '1m': 60_000, '3m': 180_000, '5m': 300_000,
      '15m': 900_000, '30m': 1_800_000,
      '1h': 3_600_000, '4h': 14_400_000, '1d': 86_400_000,
    }[interval] ?? 900_000;   // default 15m

    const targetMs  = days * 24 * 60 * 60 * 1000;
    const endTime   = Date.now();
    const startTime = endTime - targetMs;

    logger.info(`History fetch: ${pair} ${interval} ${days}d (~${Math.ceil(targetMs / intervalMs)} candles)`);

    const allCandles = [];
    let pageStart = startTime;
    let pageCount = 0;
    const MAX_PAGES = 20;   // safety cap

    while (pageStart < endTime && pageCount < MAX_PAGES) {
      const page = await fetchKlines({
        pair,
        interval,
        limit:     PAGE_SIZE,
        startTime: pageStart,
      });

      if (!Array.isArray(page) || page.length === 0) break;

      allCandles.push(...page);

      // Advance to the bar AFTER the last one returned
      const lastTs = parseInt(page[page.length - 1].endTime ?? page[page.length - 1].startTime, 10);
      pageStart = lastTs + 1;
      pageCount++;

      logger.info(`  Page ${pageCount}: +${page.length} candles, next pageStart=${new Date(pageStart).toISOString()}`);

      // If we got fewer than a full page, we've reached present
      if (page.length < PAGE_SIZE) break;
    }

    // Deduplicate by startTime (in case of overlap) and sort oldest → newest
    const seen = new Set();
    const deduped = allCandles
      .filter(c => {
        if (seen.has(c.startTime)) return false;
        seen.add(c.startTime);
        return true;
      })
      .sort((a, b) => parseInt(a.startTime, 10) - parseInt(b.startTime, 10));

    const rangeStart = deduped[0]?.startTime ?? null;
    const rangeEnd   = deduped[deduped.length - 1]?.startTime ?? null;

    logger.info(`History ready: ${deduped.length} candles | ${new Date(+rangeStart).toISOString()} → ${new Date(+rangeEnd).toISOString()}`);

    res.json({
      ok:         true,
      count:      deduped.length,
      rangeStart,
      rangeEnd,
      data:       deduped,
    });
  } catch (err) {
    logger.error('History fetch failed:', err.message);
    res.status(500).json({ ok: false, error: err.message });
  }
});

app.get('/api/balance', async (_req, res) => {
  try {
    const data = await SharkClient.fetchBalance();
    res.json({ ok: true, data });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

// ── Socket.IO ─────────────────────────────────────────────────────────────────
io.on('connection', (socket) => {
  logger.info(`Socket connected: ${socket.id}`);
  socket.emit('status', { dryRun: SharkClient.isDryRun, pair: SharkClient.pair });
  socket.on('disconnect', () => logger.info(`Socket disconnected: ${socket.id}`));
});

// ── Start ─────────────────────────────────────────────────────────────────────
http.listen(PORT, () => {
  logger.info(`Server running on http://localhost:${PORT}`);
  logger.info(`DRY_RUN=${SharkClient.isDryRun} | LIVE=${SharkClient.isLive}`);
});
