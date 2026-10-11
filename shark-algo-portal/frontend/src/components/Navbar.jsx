import React from 'react';
import { Activity, ShieldAlert, Play, Pause, Zap, Wifi, WifiOff, Sparkles, Wallet, Lock } from 'lucide-react';

export default function Navbar({ status, connected, currentSymbol = 'BTCUSDT', onSymbolChange, onModeChange, onOpenBacktest, onPause, onResume, onFlatten, onLogout }) {
  const isRunning = status?.running && !status?.paused;
  const isHalted = status?.risk?.halted;
  const isLive = status?.mode === 'LIVE';
  const hasPosition = Boolean(status?.position);
  const activeSymbol = status?.symbol || currentSymbol || 'BTCUSDT';
  const walletBalance = status?.wallet?.balance ?? status?.equity ?? status?.sizing?.capital_base ?? 100.0;

  const pairs = [
    { symbol: 'BTCUSDT', label: 'BTC/USDT', minCap: '$50+' },
    { symbol: 'ETHUSDT', label: 'ETH/USDT', minCap: '$25+' },
    { symbol: 'SOLUSDT', label: 'SOL/USDT', minCap: '$10+' },
  ];

  return (
    <header className="bg-[#0e131f] border-b border-[#1b2336] px-4 py-3 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
        {/* Left: Branding & Market */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <span className="text-2xl">🦈</span>
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="font-bold text-lg tracking-wider text-white">SHARK<span className="text-[#00e5ff]">QUANT</span></h1>
                <span className="text-xs px-2 py-0.5 rounded font-mono font-bold tracking-widest bg-[#172136] text-slate-300 border border-[#233150]">
                  TERMINAL
                </span>
              </div>
              <p className="text-[11px] text-slate-400 font-mono">{activeSymbol} • Shark Exchange Futures</p>
            </div>
          </div>

          {/* Instrument Switcher Tabs */}
          <div className="hidden sm:flex items-center pl-4 border-l border-[#1b2336] space-x-1.5 bg-[#090d16] p-1 rounded-lg border border-[#182338]">
            {pairs.map((p) => {
              const isActive = activeSymbol === p.symbol;
              return (
                <button
                  key={p.symbol}
                  onClick={() => {
                    if (hasPosition && !isActive) {
                      alert(`Cannot switch instrument while an active position is open in ${activeSymbol}! Close position first.`);
                      return;
                    }
                    if (onSymbolChange && !isActive) {
                      onSymbolChange(p.symbol);
                    }
                  }}
                  className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition flex items-center space-x-1 cursor-pointer ${
                    isActive
                      ? 'bg-[#00e5ff]/20 text-[#00e5ff] border border-[#00e5ff]/50 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200 border border-transparent hover:bg-[#151f33]'
                  }`}
                  title={`${p.label} - Min Capital ${p.minCap}`}
                >
                  <span>{p.label}</span>
                  <span className={`text-[9px] px-1 py-0.2 rounded font-normal ${isActive ? 'bg-[#00e5ff]/30 text-white' : 'text-slate-500'}`}>
                    {p.minCap}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="hidden lg:flex items-center pl-3 space-x-3 text-xs">
            <div className="flex items-center space-x-1.5">
              {connected ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                  <span className="text-slate-300 font-mono text-[11px]">WS ONLINE</span>
                </>
              ) : (
                <>
                  <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                  <span className="text-rose-400 font-mono text-[11px]">RECONNECTING</span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Center: Live Strategy & Regime Badge */}
        <div className="hidden md:flex items-center space-x-3 bg-[#090d16] px-3 py-1.5 rounded-lg border border-[#1b2336]">
          <span className="text-[11px] text-slate-400 uppercase tracking-wider">Regime:</span>
          <span className={`text-xs font-bold font-mono px-2 py-0.5 rounded ${
            status?.market?.regime === 'TRENDING'
              ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
              : status?.market?.regime === 'RANGING'
              ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30'
              : status?.market?.regime === 'VOLATILE'
              ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
              : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
          }`}>
            {status?.market?.regime || 'DETECTION PENDING'}
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-[11px] text-slate-400">Strategy:</span>
          <span className="text-xs text-[#00e5ff] font-mono font-bold">
            {status?.strategy_title || status?.strategy || 'Donchian Breakout'}
          </span>
        </div>

        {/* Right: Mode & Execution Controls */}
        <div className="flex items-center space-x-3">
          {/* Wallet Balance Pill */}
          <div className="flex items-center space-x-1.5 px-3 py-1 bg-[#090d16] border border-[#1d2942] rounded text-xs font-mono shadow-sm">
            <Wallet className="w-3.5 h-3.5 text-[#00e5ff]" />
            <span className="text-slate-400 font-medium">Wallet:</span>
            <span className="font-bold text-white">${walletBalance.toFixed(2)}</span>
            <span className="text-[10px] text-slate-500 font-normal">USDT</span>
          </div>

          {/* Mode Pill Toggle Button */}
          <button
            onClick={() => {
              const target = isLive ? 'PAPER' : 'LIVE';
              if (!isLive) {
                if (window.confirm("⚠️ SWITCH TO LIVE TRADING: Are you sure? Real funds on Shark Exchange will be traded.")) {
                  onModeChange && onModeChange('LIVE');
                }
              } else {
                onModeChange && onModeChange('PAPER');
              }
            }}
            title={`Click to switch to ${isLive ? 'PAPER' : 'LIVE'} mode`}
            className={`px-2.5 py-1 rounded text-xs font-mono font-bold tracking-wide flex items-center space-x-1.5 transition cursor-pointer ${
              isLive 
                ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40 hover:bg-rose-500/30 shadow-lg shadow-rose-950/40' 
                : 'bg-[#ffd600]/15 text-[#ffd600] border border-[#ffd600]/30 hover:bg-[#ffd600]/25'
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isLive ? 'bg-rose-400 animate-ping' : 'bg-[#ffd600]'}`}></span>
            <span>{isLive ? 'LIVE' : 'PAPER'}</span>
          </button>

          {/* Backtest & Monte Carlo Button */}
          <button
            onClick={onOpenBacktest}
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-[#141f33] hover:bg-[#1d2d4a] text-[#00e5ff] border border-[#23385d] rounded text-xs font-bold font-mono transition cursor-pointer shadow-sm"
            title="Open Strategy Backtester & Monte Carlo Simulation"
          >
            <Sparkles className="w-3.5 h-3.5 text-[#00e5ff]" />
            <span>Backtest</span>
          </button>

          {/* Pause / Resume Button */}
          {isRunning ? (
            <button
              onClick={onPause}
              className="flex items-center space-x-1 px-3 py-1.5 bg-[#172136] hover:bg-[#202c46] text-amber-400 border border-[#283858] rounded text-xs font-medium transition cursor-pointer"
            >
              <Pause className="w-3.5 h-3.5" />
              <span>Pause Bot</span>
            </button>
          ) : (
            <button
              onClick={onResume}
              disabled={isHalted}
              className="flex items-center space-x-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-medium transition disabled:opacity-50 cursor-pointer"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Resume Bot</span>
            </button>
          )}

          {/* Emergency Kill-Switch Button */}
          <button
            onClick={() => {
              if (window.confirm("⚠️ EMERGENCY FLATTEN: Instantly close all open BTC positions and halt bot?")) {
                onFlatten();
              }
            }}
            className="flex items-center space-x-1 px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded text-xs font-bold transition shadow-lg shadow-rose-900/30 cursor-pointer"
          >
            <ShieldAlert className="w-3.5 h-3.5" />
            <span>FLATTEN ALL</span>
          </button>

          {/* Lock Terminal / Logout Button */}
          {onLogout && (
            <button
              onClick={onLogout}
              className="flex items-center space-x-1 px-2.5 py-1.5 bg-[#172136] hover:bg-[#202c46] text-slate-300 hover:text-white border border-[#283858] rounded text-xs font-mono transition cursor-pointer"
              title="Lock Terminal & Log Out"
            >
              <Lock className="w-3.5 h-3.5 text-slate-400" />
              <span>Lock</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
