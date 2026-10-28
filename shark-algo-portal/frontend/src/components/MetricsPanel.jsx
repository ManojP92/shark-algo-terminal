import React from 'react';
import { TrendingUp, Award, AlertTriangle, ShieldCheck, Activity, DollarSign, Wallet } from 'lucide-react';

export default function MetricsPanel({ stats, risk, market, wallet, equity, mode, capitalBase }) {
  const dailyRealized = stats?.daily_pnl || 0;
  const floatingPnl = stats?.unrealized_pnl || 0;
  const totalDailyPnl = stats?.total_daily_pnl !== undefined ? stats.total_daily_pnl : (dailyRealized + floatingPnl);
  const isPnlPositive = totalDailyPnl >= 0;
  const hasFloating = Math.abs(floatingPnl) > 0.001;
  const lossStreak = risk?.consecutive_losses || 0;
  const isCooldown = risk?.cooldown_until && risk.cooldown_until > Date.now() / 1000;
  const isLive = mode === 'LIVE';
  const currentEquity = wallet?.balance ?? equity ?? capitalBase ?? 100.0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
      {/* 0. Wallet Balance / Equity */}
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-3.5 shadow-lg">
        <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
          <span className="font-mono uppercase tracking-wider text-[11px]">Wallet Balance</span>
          <Wallet className="w-3.5 h-3.5 text-[#00e5ff]" />
        </div>
        <div className="text-xl font-bold font-mono text-white">
          ${currentEquity.toFixed(2)}
        </div>
        <span className="text-[10px] text-[#00e5ff] font-mono font-medium">
          {isLive ? 'Live Futures' : 'Paper Wallet'} (USDT)
        </span>
      </div>

      {/* 1. Daily Realized P&L */}
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-3.5 shadow-lg">
        <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
          <span className="font-mono uppercase tracking-wider text-[11px]">Daily P&L</span>
          <DollarSign className={`w-3.5 h-3.5 ${isPnlPositive ? 'text-emerald-400' : 'text-rose-400'}`} />
        </div>
        <div className={`text-xl font-bold font-mono ${isPnlPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
          {isPnlPositive ? '+' : ''}${totalDailyPnl.toFixed(2)}
        </div>
        <span className="text-[10px] text-slate-400 font-mono">
          {hasFloating ? (
            <span>
              Real: <span className={dailyRealized >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{dailyRealized >= 0 ? '+' : ''}${dailyRealized.toFixed(2)}</span>
              {' · '}
              Float: <span className={floatingPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{floatingPnl >= 0 ? '+' : ''}${floatingPnl.toFixed(2)}</span>
            </span>
          ) : (
            'Realized today (UTC)'
          )}
        </span>
      </div>

      {/* 2. Win Rate */}
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-3.5 shadow-lg">
        <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
          <span className="font-mono uppercase tracking-wider text-[11px]">Win Rate</span>
          <Award className="w-3.5 h-3.5 text-[#00e5ff]" />
        </div>
        <div className="text-xl font-bold font-mono text-white">
          {stats?.win_rate || 0}%
        </div>
        <span className="text-[10px] text-slate-500 font-mono">
          {stats?.wins || 0}W / {(stats?.trades || 0) - (stats?.wins || 0)}L ({stats?.trades || 0} trades)
        </span>
      </div>

      {/* 3. Profit Factor */}
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-3.5 shadow-lg">
        <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
          <span className="font-mono uppercase tracking-wider text-[11px]">Profit Factor</span>
          <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
        </div>
        <div className="text-xl font-bold font-mono text-white">
          {stats?.profit_factor || '1.00'}
        </div>
        <span className="text-[10px] text-slate-500 font-mono">Gross W / Gross L</span>
      </div>

      {/* 4. Momentum / ADX */}
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-3.5 shadow-lg">
        <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
          <span className="font-mono uppercase tracking-wider text-[11px]">ADX (14)</span>
          <Activity className="w-3.5 h-3.5 text-sky-400" />
        </div>
        <div className="text-xl font-bold font-mono text-white">
          {market?.adx || '—'}
        </div>
        <span className={`text-[10px] font-mono ${market?.adx >= 20 ? 'text-emerald-400' : 'text-amber-400'}`}>
          {market?.adx >= 20 ? 'Momentum active (≥20)' : 'Chop filter (<20)'}
        </span>
      </div>

      {/* 5. ATR Volatility */}
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-3.5 shadow-lg">
        <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
          <span className="font-mono uppercase tracking-wider text-[11px]">ATR (14)</span>
          <span className="text-[10px] font-mono text-slate-500">Trailing Stop</span>
        </div>
        <div className="text-xl font-bold font-mono text-white">
          ${market?.atr || '—'}
        </div>
        <span className="text-[10px] text-slate-500 font-mono">
          3.0x: ${(market?.atr * 3 || 0).toFixed(1)}
        </span>
      </div>

      {/* 6. Circuit Breaker Sentinel */}
      <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-3.5 shadow-lg">
        <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
          <span className="font-mono uppercase tracking-wider text-[11px]">Circuit Breaker</span>
          <ShieldCheck className={`w-3.5 h-3.5 ${risk?.halted || isCooldown ? 'text-rose-400' : 'text-emerald-400'}`} />
        </div>
        <div className="text-xl font-bold font-mono text-white">
          {lossStreak} / 3 <span className="text-xs text-slate-500 font-normal">Losses</span>
        </div>
        <span className={`text-[10px] font-mono ${risk?.halted || isCooldown ? 'text-rose-400 font-bold' : 'text-emerald-400'}`}>
          {risk?.halted ? 'HALTED (DAILY CAP)' : isCooldown ? 'COOLDOWN ACTIVE' : 'NORMAL OPERATION'}
        </span>
      </div>
    </div>
  );
}
