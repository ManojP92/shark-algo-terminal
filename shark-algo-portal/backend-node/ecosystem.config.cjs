/**
 * ecosystem.config.cjs
 * ─────────────────────────────────────────────────────────────────────────────
 * PM2 process configuration for the Shark Algo Portal.
 * Uses CommonJS (required by PM2 ecosystem format).
 *
 * Usage:
 *   pm2 start ecosystem.config.cjs          # start all
 *   pm2 stop ecosystem.config.cjs           # stop all
 *   pm2 restart ecosystem.config.cjs        # restart all
 *   pm2 logs                                # tail all logs
 *   pm2 monit                               # live monitor
 *
 * Phase 1: Only the Node backend is configured.
 * Python processes will be added in Phase 4.
 * ─────────────────────────────────────────────────────────────────────────────
 */

module.exports = {
  apps: [
    // ── Node.js Backend ──────────────────────────────────────────────────────
    {
      name:           'shark-backend',
      script:         'server.mjs',
      cwd:            './backend-node',

      // Interpreter flags — PM2 needs to know this is ESM
      interpreter:    'node',
      interpreter_args: '--experimental-vm-modules',

      // Environment variables loaded from .env file
      // PM2 does NOT auto-load .env — use env_file (PM2 v5.3+) or dotenv in code
      env: {
        NODE_ENV:  'development',
        PORT:      3001,
        DRY_RUN:   'true',
        LIVE:      'false',
      },
      env_production: {
        NODE_ENV:  'production',
        PORT:      3001,
        DRY_RUN:   'true',   // keep true until Phase 6 sign-off
        LIVE:      'false',
      },

      // Process management
      watch:          false,        // set true in dev if you want auto-restart on save
      max_memory_restart: '512M',
      restart_delay:  3000,         // 3s delay before auto-restart
      max_restarts:   10,

      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      out_file:       './logs/backend-out.log',
      error_file:     './logs/backend-err.log',
      merge_logs:     true,
    },

    // ── Python Strategy Engine (Phase 4 — placeholder) ────────────────────
    // Uncomment in Phase 4 once live_executor.py is ready.
    // {
    //   name:    'shark-strategy-engine',
    //   script:  'live_executor.py',
    //   cwd:     './backend-python',
    //   interpreter: 'python',
    //   env: {
    //     DRY_RUN:            'true',
    //     PYTHON_BRIDGE_PORT: '5001',
    //   },
    //   out_file:   './logs/strategy-out.log',
    //   error_file: './logs/strategy-err.log',
    // },
  ],
};
