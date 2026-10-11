import React, { useState } from 'react';
import { History, Terminal, ArrowUpRight, ArrowDownRight } from 'lucide-react';

export default function TradeLedger({ trades, logs }) {
  const [tab, setTab] = useState('trades');

  return (
    <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-4 shadow-xl">
      {/* Header with Tab switcher */}
      <div className="flex items-center justify-between border-b border-[#1b2336] pb-3 mb-3">
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setTab('trades')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition ${
              tab === 'trades'
                ? 'bg-[#172136] text-[#00e5ff] border border-[#22314d]'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <History className="w-3.5 h-3.5" />
            <span>TRADE LEDGER ({trades?.length || 0})</span>
          </button>

          <button
            onClick={() => setTab('logs')}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition ${
              tab === 'logs'
                ? 'bg-[#172136] text-[#00e5ff] border border-[#22314d]'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>ENGINE LOGS ({logs?.length || 0})</span>
          </button>
        </div>

        <span className="text-[11px] text-slate-500 font-mono">Auto-syncing via WebSocket</span>
      </div>

      {/* Tab 1: Trade Ledger */}
      {tab === 'trades' && (
        <div className="overflow-x-auto">
          {(!trades || trades.length === 0) ? (
            <div className="py-10 text-center text-slate-500 font-mono text-xs">
              No historical trades logged yet today. Trades will populate here automatically.
            </div>
          ) : (
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="text-slate-400 border-b border-[#172136] pb-2 text-[11px] uppercase">
                  <th className="py-2 px-3">Time</th>
                  <th className="py-2 px-3">Type</th>
                  <th className="py-2 px-3">Pair</th>
                  <th className="py-2 px-3">Size</th>
                  <th className="py-2 px-3">Entry</th>
                  <th className="py-2 px-3">Exit</th>
                  <th className="py-2 px-3">P&amp;L ($)</th>
                  <th className="py-2 px-3">Exit Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#141b2a]">
                {trades.map((t, idx) => {
                  const isLong = t.side === 'LONG';
                  const isWin = t.pnl >= 0;
                  return (
                    <tr key={t.id || idx} className="hover:bg-[#121826] transition">
                      <td className="py-2.5 px-3 text-slate-400">{t.time}</td>
                      <td className="py-2.5 px-3">
                        <span className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] font-bold ${
                          isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
                        }`}>
                          {isLong ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                          <span>{t.side}</span>
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-slate-200">{t.symbol}</td>
                      <td className="py-2.5 px-3 text-slate-300">{t.qty}</td>
                      <td className="py-2.5 px-3 text-slate-300">${t.entry?.toLocaleString()}</td>
                      <td className="py-2.5 px-3 text-slate-300">${t.exit?.toLocaleString()}</td>
                      <td className={`py-2.5 px-3 font-bold ${isWin ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {isWin ? '+' : ''}${t.pnl?.toFixed(2)}
                      </td>
                      <td className="py-2.5 px-3 text-slate-400 text-[11px] max-w-xs truncate">{t.reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Tab 2: Live Engine Logs */}
      {tab === 'logs' && (
        <div className="bg-[#090d16] border border-[#161f31] rounded-lg p-3 max-h-64 overflow-y-auto font-mono text-[11px] space-y-1">
          {(!logs || logs.length === 0) ? (
            <div className="text-slate-500 py-4 text-center">No telemetry logs recorded yet.</div>
          ) : (
            logs.map((logItem, idx) => (
              <div key={idx} className="text-slate-300 flex items-start space-x-2">
                <span className="text-slate-500 select-none">›</span>
                <span className="break-all">{logItem}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
