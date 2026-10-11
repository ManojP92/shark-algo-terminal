/**
 * constants.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Shared constants used by both Node and Python layers.
 * Python reads the JSON version; Node imports this file.
 * ─────────────────────────────────────────────────────────────────────────────
 */

export const PAIR = 'BTCUSDT';

// Timeframes
export const TF_5M  = '5m';
export const TF_15M = '15m';

// Regime labels
export const REGIME = Object.freeze({
  TRENDING:  'TRENDING',
  RANGING:   'RANGING',
  VOLATILE:  'VOLATILE',
  UNCLEAR:   'UNCLEAR',
});

// Regime thresholds
export const REGIME_THRESHOLDS = Object.freeze({
  ADX_TREND_MIN:       25,   // ADX > 25 → trending
  ADX_RANGE_MAX:       20,   // ADX < 20 → ranging
  CHOP_TREND_MAX:      38,   // Choppiness < 38 → trending
  CHOP_RANGE_MIN:      61,   // Choppiness > 61 → ranging
  ATR_RATIO_VOLATILE:  1.5,  // ATR ratio > 1.5 → volatile
});

// Indicator periods
export const PERIODS = Object.freeze({
  ADX:  14,
  ATR:  14,
  RSI:  14,
  CHOP: 14,
  ATR_AVERAGE: 20,  // period for ATR ratio denominator
});

// Risk defaults (overridden by .env)
export const RISK_DEFAULTS = Object.freeze({
  RISK_PER_TRADE_PCT:       1,
  MAX_CONCURRENT_POSITIONS: 1,
  MAX_CONSECUTIVE_LOSSES:   3,
  DAILY_LOSS_LIMIT_PCT:     3,
  PAUSE_DURATION_MS:        60 * 60 * 1000,  // 1 hour
});

// Strategy IDs
export const STRATEGIES = Object.freeze({
  FVG:      'FVG',
  BREAKOUT: 'BREAKOUT',
  REVERSAL: 'REVERSAL',
  NONE:     'NONE',
});

// Signal types
export const SIGNAL = Object.freeze({
  LONG:    'LONG',
  SHORT:   'SHORT',
  NO_TRADE: 'NO_TRADE',
});
