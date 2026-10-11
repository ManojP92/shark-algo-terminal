import React, { useState } from 'react';
import {
  X,
  Play,
  RefreshCw,
  TrendingUp,
  Percent,
  Sliders,
  DollarSign,
  Shield,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Sparkles,
  Layers,
  HelpCircle
} from 'lucide-react';

export default function BacktestModal({ isOpen, onClose, defaultPair = 'BTCUSDT' }) {
  if (!isOpen) return null;

  // Configuration state
  const [pair, setPair] = useState(defaultPair);
  const [interval, setInterval] = useState('15m');
  const [days, setDays] = useState(14);
  const [capital, setCapital] = useState(defaultPair === 'SOLUSDT' ? 10.0 : 100.0);
  const [riskPct, setRiskPct] = useState(1.0);
  const [leverage, setLeverage] = useState(10);
  const [mcRuns, setMcRuns] = useState(500);

  // Results & UI State
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [activeTab, setActiveTab] = useState('equity'); // 'equity', 'monte_carlo', 'trades'

  const pairs = [
    { sym: 'BTCUSDT', label: 'BTC/USDT', defaultCap: 100 },
    { sym: 'ETHUSDT', label: 'ETH/USDT', defaultCap: 50 },
    { sym: 'SOLUSDT', label: 'SOL/USDT', defaultCap: 10 },
  ];

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pair,
          interval,
          days: Number(days),
          capital: Number(capital),
          risk_pct: Number(riskPct),
          leverage: Number(leverage),
          monte_carlo_runs: Number(mcRuns),
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || data.error || 'Backtest failed');
      }
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Helper for rendering SVG charts
  const renderEquityChart = () => {
    if (!result?.equity_curve || result.equity_curve.length < 2) {
      return (
        <div className="h-64 flex items-center justify-center text-slate-500 font-mono text-xs">
          No equity data points to plot.
        </div>
      );
    }

    const points = result.equity_curve;
    const equities = points.map((p) => p.equity);
    const minEq = Math.min(...equities) * 0.99;
    const maxEq = Math.max(...equities) * 1.01;
    const range = maxEq - minEq || 1;

    const width = 800;
    const height = 220;
    const padding = 20;

    const coords = points.map((p, idx) => {
      const x = padding + (idx / (points.length - 1)) * (width - 2 * padding);
      const y = height - padding - ((p.equity - minEq) / range) * (height - 2 * padding);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const pathD = `M ${coords.join(' L ')}`;
    const areaD = `M ${coords[0]} L ${coords.join(' L ')} L ${coords[coords.length - 1].split(',')[0]},${height - padding} L ${coords[0].split(',')[0]},${height - padding} Z`;
    const isProfitable = result.summary.net_pnl >= 0;

    return (
      <div className="relative w-full">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-56 overflow-visible">
          <defs>
            <linearGradient id="eqGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={isProfitable ? '#00e676' : '#ff1744'} stopOpacity="0.3" />
              <stop offset="100%" stopColor={isProfitable ? '#00e676' : '#ff1744'} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          <line x1={padding} y1={padding} x2={width - padding} y2={padding} stroke="#1b253b" strokeDasharray="3 3" />
          <line x1={padding} y1={height / 2} x2={width - padding} y2={height / 2} stroke="#1b253b" strokeDasharray="3 3" />
          <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#1b253b" />

          {/* Gradient fill */}
          <path d={areaD} fill="url(#eqGradient)" />

          {/* Equity Line */}
          <path d={pathD} fill="none" stroke={isProfitable ? '#00e676' : '#ff1744'} strokeWidth="2.5" strokeLinecap="round" />
        </svg>

        <div className="flex justify-between items-center text-[10px] font-mono text-slate-400 mt-1 px-2">
          <span>Start: ${points[0].equity} ({points[0].time?.slice(5, 16)})</span>
          <span>High: ${maxEq.toFixed(2)}</span>
          <span>End: ${points[points.length - 1].equity}</span>
        </div>
      </div>
    );
  };

  const renderMonteCarloChart = () => {
    if (!result?.monte_carlo?.sample_paths || result.monte_carlo.sample_paths.length === 0) {
      return (
        <div className="h-64 flex items-center justify-center text-slate-500 font-mono text-xs">
          No Monte Carlo paths generated.
        </div>
      );
    }

    const paths = result.monte_carlo.sample_paths;
    const allValues = paths.flatMap((p) => p.data);
    const minVal = Math.min(...allValues) * 0.98;
    const maxVal = Math.max(...allValues) * 1.02;
    const range = maxVal - minVal || 1;

    const width = 800;
    const height = 220;
    const padding = 20;

    return (
      <div className="relative w-full">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-56 overflow-visible">
          {/* Grid lines */}
          <line x1={padding} y1={padding} x2={width - padding} y2={padding} stroke="#1b253b" strokeDasharray="3 3" />
          <line x1={padding} y1={height / 2} x2={width - padding} y2={height / 2} stroke="#1b253b" strokeDasharray="3 3" />
          <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#1b253b" />

          {/* Draw all sample paths */}
          {paths.map((p, pIdx) => {
            const coords = p.data.map((val, idx) => {
              const x = padding + (idx / (p.data.length - 1)) * (width - 2 * padding);
              const y = height - padding - ((val - minVal) / range) * (height - 2 * padding);
              return `${x.toFixed(1)},${y.toFixed(1)}`;
            });
            const pathD = `M ${coords.join(' L ')}`;

            let strokeColor = 'rgba(100, 116, 139, 0.4)';
            let strokeWidth = 1;
            if (p.is_median) {
              strokeColor = '#00e5ff';
              strokeWidth = 2.5;
            } else if (p.is_p95) {
              strokeColor = '#00e676';
              strokeWidth = 2;
            } else if (p.is_p5) {
              strokeColor = '#ff1744';
              strokeWidth = 2;
            }

            return <path key={pIdx} d={pathD} fill="none" stroke={strokeColor} strokeWidth={strokeWidth} />;
          })}
        </svg>

        <div className="flex flex-wrap items-center justify-between text-[11px] font-mono text-slate-400 mt-2 px-2 gap-2">
          <div className="flex items-center space-x-4">
            <span className="flex items-center space-x-1 text-[#00e676]">
              <span className="w-2.5 h-0.5 bg-[#00e676]"></span>
              <span>P95 (Optimistic): ${result.monte_carlo.p95_equity}</span>
            </span>
            <span className="flex items-center space-x-1 text-[#00e5ff]">
              <span className="w-2.5 h-0.5 bg-[#00e5ff]"></span>
              <span>Median: ${result.monte_carlo.median_equity}</span>
            </span>
            <span className="flex items-center space-x-1 text-[#ff1744]">
              <span className="w-2.5 h-0.5 bg-[#ff1744]"></span>
              <span>P5 (Conservative): ${result.monte_carlo.p5_equity}</span>
            </span>
          </div>
          <span className="text-slate-500">Based on {result.monte_carlo.num_simulations} randomized bootstrap resamples</span>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-md">
      <div className="bg-[#0b0f19] border border-[#1b253b] rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#1b253b] bg-[#0e1422]">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-[#00e5ff]/10 border border-[#00e5ff]/30 flex items-center justify-center text-[#00e5ff]">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-base font-bold text-white tracking-wide">Strategy Backtester &amp; Monte Carlo</h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#18253d] text-[#00e5ff] border border-[#233555]">
                  INSTITUTIONAL
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono">
                Donchian Channels (25) + ADX (14) Momentum Filter • Shark Exchange Data
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-[#1a2336] transition cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Configuration Bar */}
        <div className="p-4 bg-[#090d16] border-b border-[#1b253b]">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3 text-xs font-mono">
            {/* Pair */}
            <div className="bg-[#101726] p-2 rounded-lg border border-[#1c2942]">
              <span className="text-[10px] text-slate-400 block mb-1">Trading Pair</span>
              <select
                value={pair}
                onChange={(e) => {
                  const newPair = e.target.value;
                  setPair(newPair);
                  if (newPair === 'SOLUSDT' && capital > 50) setCapital(10);
                  if (newPair === 'BTCUSDT' && capital < 50) setCapital(100);
                }}
                className="w-full bg-transparent font-bold text-white focus:outline-none cursor-pointer"
              >
                {pairs.map((p) => (
                  <option key={p.sym} value={p.sym} className="bg-[#0b0f19]">
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Timeframe */}
            <div className="bg-[#101726] p-2 rounded-lg border border-[#1c2942]">
              <span className="text-[10px] text-slate-400 block mb-1">Timeframe</span>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="w-full bg-transparent font-bold text-white focus:outline-none cursor-pointer"
              >
                <option value="5m" className="bg-[#0b0f19]">5m (Fast)</option>
                <option value="15m" className="bg-[#0b0f19]">15m (Primary)</option>
                <option value="1h" className="bg-[#0b0f19]">1h (Swing)</option>
              </select>
            </div>

            {/* Lookback Days */}
            <div className="bg-[#101726] p-2 rounded-lg border border-[#1c2942]">
              <span className="text-[10px] text-slate-400 block mb-1">Lookback History</span>
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="w-full bg-transparent font-bold text-white focus:outline-none cursor-pointer"
              >
                <option value={7} className="bg-[#0b0f19]">7 Days (~672 bars)</option>
                <option value={14} className="bg-[#0b0f19]">14 Days (~1344 bars)</option>
                <option value={30} className="bg-[#0b0f19]">30 Days (~2880 bars)</option>
              </select>
            </div>

            {/* Capital ($) */}
            <div className="bg-[#101726] p-2 rounded-lg border border-[#1c2942]">
              <span className="text-[10px] text-slate-400 block mb-1">Capital ($)</span>
              <div className="flex items-center space-x-1">
                <span className="text-slate-400">$</span>
                <input
                  type="number"
                  min="5"
                  step="5"
                  value={capital}
                  onChange={(e) => setCapital(parseFloat(e.target.value) || 10)}
                  className="w-full bg-transparent text-white font-bold focus:outline-none"
                />
              </div>
            </div>

            {/* Risk % */}
            <div className="bg-[#101726] p-2 rounded-lg border border-[#1c2942]">
              <span className="text-[10px] text-slate-400 block mb-1">Risk / Trade</span>
              <div className="flex items-center space-x-1">
                <input
                  type="number"
                  min="0.5"
                  max="5.0"
                  step="0.5"
                  value={riskPct}
                  onChange={(e) => setRiskPct(parseFloat(e.target.value) || 1)}
                  className="w-full bg-transparent text-white font-bold focus:outline-none"
                />
                <span className="text-slate-400">%</span>
              </div>
            </div>

            {/* Leverage */}
            <div className="bg-[#101726] p-2 rounded-lg border border-[#1c2942]">
              <span className="text-[10px] text-slate-400 block mb-1">Leverage</span>
              <div className="flex items-center space-x-1">
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={leverage}
                  onChange={(e) => setLeverage(parseInt(e.target.value) || 10)}
                  className="w-full bg-transparent text-white font-bold focus:outline-none"
                />
                <span className="text-slate-400">x</span>
              </div>
            </div>

            {/* Run Button */}
            <div className="flex items-end">
              <button
                onClick={handleRun}
                disabled={loading}
                className="w-full py-2.5 px-3 bg-[#00e5ff] hover:bg-[#33ebff] text-slate-950 font-bold rounded-lg transition flex items-center justify-center space-x-1.5 shadow-lg shadow-[#00e5ff]/20 disabled:opacity-50 cursor-pointer"
              >
                {loading ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Testing...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>Run Backtest</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {error && (
            <div className="p-3 bg-rose-500/15 border border-rose-500/30 rounded-xl text-xs font-mono text-rose-300">
              ❌ {error}
            </div>
          )}

          {!result && !loading && (
            <div className="py-16 flex flex-col items-center justify-center text-center">
              <div className="w-14 h-14 rounded-2xl bg-[#121a2c] border border-[#1d2a45] flex items-center justify-center text-[#00e5ff] mb-4 shadow-inner">
                <Activity className="w-7 h-7" />
              </div>
              <h3 className="text-base font-bold text-white mb-1">Ready to Backtest</h3>
              <p className="text-xs text-slate-400 max-w-md font-mono mb-4">
                Configure your capital balance ($10 to $1,000+), choose an instrument, and run historical simulations with real exchange candles.
              </p>
              <button
                onClick={handleRun}
                className="px-5 py-2 bg-[#17243c] hover:bg-[#203254] text-[#00e5ff] border border-[#263c66] rounded-xl text-xs font-bold font-mono transition cursor-pointer"
              >
                Run Default {pair} Backtest
              </button>
            </div>
          )}

          {result && (
            <>
              {/* Metric Highlights Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                {/* Net PnL */}
                <div className="bg-[#0e1422] p-3 rounded-xl border border-[#1b253b]">
                  <span className="text-[10px] font-mono text-slate-400 block mb-1">Net Profit / ROI</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className={`text-lg font-bold font-mono ${result.summary.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {result.summary.net_pnl >= 0 ? '+' : ''}${result.summary.net_pnl.toFixed(2)}
                    </span>
                    <span className={`text-xs font-bold font-mono ${result.summary.roi_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      ({result.summary.roi_pct >= 0 ? '+' : ''}{result.summary.roi_pct.toFixed(1)}%)
                    </span>
                  </div>
                </div>

                {/* Win Rate */}
                <div className="bg-[#0e1422] p-3 rounded-xl border border-[#1b253b]">
                  <span className="text-[10px] font-mono text-slate-400 block mb-1">Win Rate</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-lg font-bold font-mono text-white">
                      {result.summary.win_rate}%
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">
                      ({result.summary.winning_trades}W / {result.summary.losing_trades}L)
                    </span>
                  </div>
                </div>

                {/* Profit Factor */}
                <div className="bg-[#0e1422] p-3 rounded-xl border border-[#1b253b]">
                  <span className="text-[10px] font-mono text-slate-400 block mb-1">Profit Factor</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-lg font-bold font-mono text-[#00e5ff]">
                      {result.summary.profit_factor}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">PF</span>
                  </div>
                </div>

                {/* Max Drawdown */}
                <div className="bg-[#0e1422] p-3 rounded-xl border border-[#1b253b]">
                  <span className="text-[10px] font-mono text-slate-400 block mb-1">Max Drawdown</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-lg font-bold font-mono text-amber-400">
                      {result.summary.max_drawdown_pct}%
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">Peak-to-Trough</span>
                  </div>
                </div>

                {/* Monte Carlo Probability of Profit */}
                <div className="bg-[#0e1422] p-3 rounded-xl border border-[#1b253b] relative overflow-hidden">
                  <span className="text-[10px] font-mono text-slate-400 block mb-1 flex items-center justify-between">
                    <span>Monte Carlo Win Prob</span>
                    <Sparkles className="w-2.5 h-2.5 text-[#00e5ff]" />
                  </span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-lg font-bold font-mono text-emerald-400">
                      {result.monte_carlo.prob_profit}%
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">500 Runs</span>
                  </div>
                </div>

                {/* Monte Carlo 95% Worst DD */}
                <div className="bg-[#0e1422] p-3 rounded-xl border border-[#1b253b]">
                  <span className="text-[10px] font-mono text-slate-400 block mb-1">MC 95% Worst DD</span>
                  <div className="flex items-baseline space-x-1.5">
                    <span className="text-lg font-bold font-mono text-sky-400">
                      {result.monte_carlo.p95_max_dd}%
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">95% Confidence</span>
                  </div>
                </div>
              </div>

              {/* Chart Tabs */}
              <div className="bg-[#0e1422] border border-[#1b253b] rounded-xl p-4">
                <div className="flex items-center justify-between border-b border-[#1b253b] pb-3 mb-3">
                  <div className="flex space-x-2">
                    <button
                      onClick={() => setActiveTab('equity')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition cursor-pointer ${
                        activeTab === 'equity'
                          ? 'bg-[#1b263e] text-[#00e5ff] border border-[#2a3c63]'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      📈 Historical Equity Curve
                    </button>
                    <button
                      onClick={() => setActiveTab('monte_carlo')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition cursor-pointer flex items-center space-x-1.5 ${
                        activeTab === 'monte_carlo'
                          ? 'bg-[#1b263e] text-[#00e5ff] border border-[#2a3c63]'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      <Sparkles className="w-3 h-3 text-[#00e5ff]" />
                      <span>Monte Carlo Resampling Cone</span>
                    </button>
                    <button
                      onClick={() => setActiveTab('trades')}
                      className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition cursor-pointer ${
                        activeTab === 'trades'
                          ? 'bg-[#1b263e] text-[#00e5ff] border border-[#2a3c63]'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      📋 Simulated Trades ({result.trades.length})
                    </button>
                  </div>

                  <span className="text-xs font-mono text-slate-400 hidden sm:inline">
                    Tested {result.candles_count} bars on {result.pair}
                  </span>
                </div>

                {/* Tab Views */}
                {activeTab === 'equity' && renderEquityChart()}
                {activeTab === 'monte_carlo' && renderMonteCarloChart()}
                {activeTab === 'trades' && (
                  <div className="overflow-x-auto max-h-72">
                    <table className="w-full text-left text-xs font-mono">
                      <thead className="bg-[#090d16] text-slate-400 sticky top-0">
                        <tr>
                          <th className="p-2">ID</th>
                          <th className="p-2">Entry</th>
                          <th className="p-2">Exit</th>
                          <th className="p-2">Side</th>
                          <th className="p-2">Entry $</th>
                          <th className="p-2">Exit $</th>
                          <th className="p-2">Net P&L</th>
                          <th className="p-2">Reason</th>
                          <th className="p-2">Balance</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#182338]">
                        {result.trades.map((t) => (
                          <tr key={t.id} className="hover:bg-[#121929]">
                            <td className="p-2 text-slate-400">{t.id}</td>
                            <td className="p-2 text-slate-300">{t.entry_time?.slice(5, 16)}</td>
                            <td className="p-2 text-slate-300">{t.exit_time?.slice(5, 16)}</td>
                            <td className="p-2">
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                t.side === 'LONG' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                              }`}>
                                {t.side}
                              </span>
                            </td>
                            <td className="p-2 text-white">${t.entry_price}</td>
                            <td className="p-2 text-white">${t.exit_price}</td>
                            <td className={`p-2 font-bold ${t.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                              {t.net_pnl >= 0 ? '+' : ''}${t.net_pnl.toFixed(2)} ({t.pnl_pct}%)
                            </td>
                            <td className="p-2 text-slate-400">{t.exit_reason}</td>
                            <td className="p-2 text-sky-400">${t.equity_after}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
