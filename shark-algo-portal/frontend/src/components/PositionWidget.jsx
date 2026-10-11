import React from 'react';
import { ArrowUpRight, ArrowDownRight, ShieldCheck, Crosshair, AlertTriangle } from 'lucide-react';

export default function PositionWidget({ position, onFlatten }) {
  if (!position) {
    return (
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-5 shadow-xl flex flex-col justify-between h-full">
        <div className="flex items-center justify-between border-b border-[#1b2336] pb-3 mb-4">
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-slate-500"></span>
            <h3 className="font-bold text-sm text-slate-300 uppercase tracking-wider">Active Position</h3>
          </div>
          <span className="text-[11px] font-mono text-slate-500">CONCURRENT: 0 / 1</span>
        </div>

        <div className="py-8 flex flex-col items-center justify-center text-center">
          <div className="w-12 h-12 rounded-full bg-[#121826] border border-[#1e273d] flex items-center justify-center text-slate-500 mb-3">
            <Crosshair className="w-5 h-5 text-slate-400" />
          </div>
          <p className="text-sm font-medium text-slate-300">No Open Position</p>
          <p className="text-xs text-slate-500 mt-1 max-w-xs font-mono">
            Scanning 25-period Donchian Channels with ADX momentum filter (≥20.0).
          </p>
        </div>

        <div className="bg-[#090d16] p-3 rounded-lg border border-[#161e30] flex items-center justify-between text-xs text-slate-400">
          <span>Target Risk: <strong className="text-slate-200">1.0% Equity</strong></span>
          <span>Max Slippage: <strong className="text-slate-200">0.05%</strong></span>
        </div>
      </div>
    );
  }

  const isLong = position.side === 'LONG';
  const isProfitable = position.unrealized_pnl >= 0;

  return (
    <div className={`bg-[#0e131f] border ${isProfitable ? 'border-emerald-500/40' : 'border-rose-500/40'} rounded-xl p-5 shadow-2xl relative overflow-hidden flex flex-col justify-between h-full`}>
      {/* Top Header */}
      <div>
        <div className="flex items-center justify-between border-b border-[#1b2336] pb-3 mb-4">
          <div className="flex items-center space-x-2">
            <span className={`px-2.5 py-0.5 rounded text-xs font-mono font-bold flex items-center space-x-1 ${
              isLong ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
            }`}>
              {isLong ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
              <span>{position.side} {position.symbol}</span>
            </span>
            <span className="text-[11px] font-mono text-slate-400">Qty: {position.qty}</span>
          </div>

          <div className="flex items-center space-x-2">
            {position.scaled_out && (
              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-sky-500/20 text-sky-400 border border-sky-500/30">
                50% SCALED OUT (BE)
              </span>
            )}
            <span className="text-[11px] font-mono text-slate-400">Opened: {position.open_time}</span>
          </div>
        </div>

        {/* Live Unrealized PnL Hero */}
        <div className="bg-[#090d16] p-4 rounded-xl border border-[#172136] mb-4">
          <span className="text-xs font-mono text-slate-400 uppercase tracking-wider block mb-1">Unrealized P&L</span>
          <div className="flex items-baseline space-x-3">
            <span className={`text-2xl sm:text-3xl font-mono font-bold tracking-tight ${
              isProfitable ? 'text-emerald-400' : 'text-rose-400'
            }`}>
              {position.unrealized_pnl >= 0 ? '+' : ''}${position.unrealized_pnl.toFixed(2)}
            </span>
            <span className={`text-sm font-mono font-bold px-2 py-0.5 rounded ${
              isProfitable ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
            }`}>
              {position.pnl_pct >= 0 ? '+' : ''}{position.pnl_pct.toFixed(2)}%
            </span>
          </div>
        </div>

        {/* Key Trade Levels Grid */}
        <div className="grid grid-cols-2 gap-2 text-xs font-mono mb-4">
          <div className="bg-[#121826] p-2.5 rounded-lg border border-[#1b253b]">
            <span className="text-slate-400 text-[10px] uppercase block">Entry Price</span>
            <span className="font-bold text-white text-sm">${position.entry.toLocaleString()}</span>
          </div>
          <div className="bg-[#121826] p-2.5 rounded-lg border border-[#1b253b]">
            <span className="text-slate-400 text-[10px] uppercase block">Mark Price</span>
            <span className="font-bold text-white text-sm">${position.mark_price.toLocaleString()}</span>
          </div>
          <div className="bg-[#121826] p-2.5 rounded-lg border border-[#1b253b]">
            <span className="text-rose-400 text-[10px] uppercase flex items-center space-x-1">
              <ShieldCheck className="w-3 h-3" />
              <span>Trailing SL (3.0x ATR)</span>
            </span>
            <span className="font-bold text-rose-400 text-sm">${(position.trail_sl || position.sl).toLocaleString()}</span>
          </div>
          <div className="bg-[#121826] p-2.5 rounded-lg border border-[#1b253b]">
            <span className="text-amber-400 text-[10px] uppercase block">Est. Liquidation</span>
            <span className="font-bold text-amber-400 text-sm">${position.liquidation.toLocaleString()}</span>
          </div>
        </div>
      </div>

      {/* Close Action */}
      <button
        onClick={onFlatten}
        className="w-full py-2 bg-rose-600/80 hover:bg-rose-600 text-white font-medium rounded-lg text-xs transition border border-rose-500/30 flex items-center justify-center space-x-2 cursor-pointer"
      >
        <span>Market Close Position</span>
      </button>
    </div>
  );
}
