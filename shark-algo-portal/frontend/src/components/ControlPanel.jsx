import React, { useState, useEffect } from 'react';
import { Sliders, Calculator, Zap, Shield, ChevronRight, Plus, Minus, ArrowUpRight, RotateCcw } from 'lucide-react';

export default function ControlPanel({ status, currentSymbol = 'BTCUSDT', onSymbolChange, onModeChange, onPause, onResume, onFlatten }) {
  const isRunning = status?.running && !status?.paused;
  const currentMode = status?.mode || 'PAPER';
  const hasPosition = Boolean(status?.position);

  const defaultInstruments = {
    BTCUSDT: { name: 'Bitcoin', symbol: 'BTCUSDT', min_qty: 0.001, step_size: 0.001, min_notional: 115.0, min_capital: 50.0, base_asset: 'BTC', default_lots: 0.001 },
    ETHUSDT: { name: 'Ethereum', symbol: 'ETHUSDT', min_qty: 0.001, step_size: 0.001, min_notional: 23.0, min_capital: 25.0, base_asset: 'ETH', default_lots: 0.010 },
    SOLUSDT: { name: 'Solana', symbol: 'SOLUSDT', min_qty: 0.01, step_size: 0.01, min_notional: 5.75, min_capital: 10.0, base_asset: 'SOL', default_lots: 0.05 },
  };

  const instruments = status?.instruments || defaultInstruments;
  const activeSymbol = status?.symbol || currentSymbol || 'BTCUSDT';
  const currentInst = instruments[activeSymbol] || defaultInstruments.BTCUSDT;
  const baseAsset = currentInst.base_asset || 'BTC';
  const minQty = currentInst.min_qty || 0.001;
  const stepSize = currentInst.step_size || 0.001;
  const decimals = stepSize < 0.01 ? 3 : 2;

  const markPrice = status?.market?.mark_price || (activeSymbol === 'BTCUSDT' ? 83000 : activeSymbol === 'ETHUSDT' ? 2400 : 150);
  const atr = status?.market?.atr || (activeSymbol === 'BTCUSDT' ? 40 : activeSymbol === 'ETHUSDT' ? 5 : 0.8);

  // Sizing & Compounding State
  const [strategy, setStrategy] = useState('DONCHIAN');
  const [sizingMode, setSizingMode] = useState(status?.sizing?.sizing_mode || 'AUTO');
  const [manualLots, setManualLots] = useState(status?.sizing?.manual_lot_size || currentInst.default_lots || 0.001);
  const [capitalBase, setCapitalBase] = useState(status?.sizing?.capital_base || 100.0);
  const [riskPct, setRiskPct] = useState(status?.sizing?.risk_per_trade_pct || 1.0);
  const [leverage, setLeverage] = useState(status?.sizing?.leverage || 10);
  const [dailyCap, setDailyCap] = useState(status?.risk?.daily_limit_pct || 2.5);

  // Sync state if backend updates
  useEffect(() => {
    if (status?.strategy) setStrategy(status.strategy);
    if (status?.sizing) {
      if (status.sizing.sizing_mode) setSizingMode(status.sizing.sizing_mode);
      if (status.sizing.manual_lot_size) setManualLots(status.sizing.manual_lot_size);
      if (status.sizing.capital_base) setCapitalBase(status.sizing.capital_base);
      if (status.sizing.risk_per_trade_pct) setRiskPct(status.sizing.risk_per_trade_pct);
      if (status.sizing.leverage) setLeverage(status.sizing.leverage);
    }
  }, [status?.sizing, status?.strategy]);

  const handleStrategyChange = async (newStrat) => {
    setStrategy(newStrat);
    try {
      await fetch('/api/control/strategy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: newStrat }),
      });
    } catch (e) {
      console.error('Failed to update strategy:', e);
    }
  };

  // Push updates to backend
  const pushSizingUpdate = async (overrides = {}) => {
    const payload = {
      sizing_mode: overrides.sizing_mode || sizingMode,
      manual_lot_size: overrides.manual_lot_size !== undefined ? overrides.manual_lot_size : manualLots,
      risk_per_trade_pct: overrides.risk_per_trade_pct !== undefined ? overrides.risk_per_trade_pct : riskPct,
      capital_base: overrides.capital_base !== undefined ? overrides.capital_base : capitalBase,
      leverage: overrides.leverage !== undefined ? overrides.leverage : leverage,
    };
    try {
      await fetch('/api/control/sizing', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      console.error('Failed to sync sizing:', e);
    }
  };

  const handleResetWallet = async () => {
    if (window.confirm(`Reset paper wallet balance to $${capitalBase.toFixed(2)}?`)) {
      try {
        await fetch('/api/control/wallet/reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ balance: capitalBase }),
        });
      } catch (e) {
        console.error('Failed to reset wallet:', e);
      }
    }
  };

  // Calculations for display
  const effectiveLots = sizingMode === 'MANUAL' 
    ? manualLots 
    : Math.max(minQty, Number(((capitalBase * (riskPct / 100)) / (Math.max(0.1, 1.5 * atr))).toFixed(decimals)));

  const notionalValue = effectiveLots * markPrice;
  const marginRequired = notionalValue / leverage;
  const freeMarginBuffer = Math.max(0, capitalBase - marginRequired);
  const slDollarRisk = effectiveLots * (1.5 * atr);
  const slRiskPctOfCapital = capitalBase > 0 ? (slDollarRisk / capitalBase) * 100 : 0;

  const handleToggleMode = () => {
    if (currentMode === 'PAPER') {
      if (window.confirm("⚠️ SWITCH TO LIVE TRADING: Are you sure? Live funds will be subjected to trade execution.")) {
        onModeChange('LIVE');
      }
    } else {
      onModeChange('PAPER');
    }
  };

  const adjustLotSize = (delta) => {
    const newLot = Math.max(minQty, Number((manualLots + delta).toFixed(decimals)));
    setManualLots(newLot);
    pushSizingUpdate({ manual_lot_size: newLot });
  };

  const presetsBySymbol = {
    BTCUSDT: [0.001, 0.002, 0.005, 0.010],
    ETHUSDT: [0.005, 0.010, 0.020, 0.050],
    SOLUSDT: [0.05, 0.10, 0.20, 0.50],
  };
  const currentPresets = presetsBySymbol[activeSymbol] || [0.001, 0.002, 0.005, 0.010];

  return (
    <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-5 shadow-xl h-full flex flex-col justify-between">
      <div>
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#1b2336] pb-3 mb-4">
          <div className="flex items-center space-x-2">
            <Sliders className="w-4 h-4 text-[#00e5ff]" />
            <h3 className="font-bold text-sm text-slate-200 uppercase tracking-wider">Trading Engine &amp; Sizing</h3>
          </div>
          <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
            isRunning ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'
          }`}>
            {isRunning ? 'RUNNING' : 'PAUSED'}
          </span>
        </div>

        {/* Live / Paper Toggle */}
        <div className="bg-[#090d16] p-3 rounded-xl border border-[#1b253b] mb-4 flex items-center justify-between">
          <div>
            <span className="text-xs font-bold text-white block">Execution Mode</span>
            <span className="text-[11px] text-slate-400 font-mono">
              {currentMode === 'LIVE' ? 'Real API order execution' : 'Simulated execution ($100 sandbox)'}
            </span>
          </div>

          <button
            onClick={handleToggleMode}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-bold flex items-center space-x-2 transition cursor-pointer ${
              currentMode === 'LIVE'
                ? 'bg-rose-600 text-white hover:bg-rose-500 shadow-md shadow-rose-900/40'
                : 'bg-[#ffd600]/20 text-[#ffd600] border border-[#ffd600]/40 hover:bg-[#ffd600]/30'
            }`}
          >
            <span>{currentMode}</span>
          </button>
        </div>

        {/* Active Strategy Engine Selector */}
        <div className="bg-[#090d16] p-2.5 rounded-xl border border-[#1b253b] mb-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-bold text-white flex items-center space-x-1.5">
              <span>Active Strategy Engine</span>
            </span>
            <span className="text-[10px] font-mono text-[#00e5ff] bg-[#00e5ff]/10 px-1.5 py-0.5 rounded border border-[#00e5ff]/20">
              {strategy}
            </span>
          </div>
          <select
            value={strategy}
            onChange={(e) => handleStrategyChange(e.target.value)}
            className="w-full bg-[#101726] border border-[#1c2a44] rounded-lg p-2 text-xs font-mono font-bold text-white focus:outline-none cursor-pointer"
          >
            <option value="DONCHIAN">🦈 Donchian Breakout (Trend Following)</option>
            <option value="BOLLINGER_RSI">📊 Bollinger + RSI (Mean Reversion)</option>
            <option value="SUPERTREND">⚡ Supertrend Momentum (Trend Rider)</option>
            <option value="REGIME_ADAPTIVE">🧠 Regime-Adaptive Hybrid (Multi-Regime)</option>
          </select>
        </div>

        {/* Quick Pair Selector */}
        <div className="bg-[#090d16] p-2.5 rounded-xl border border-[#1b253b] mb-3 flex items-center justify-between">
          <div className="flex items-center space-x-1.5">
            <span className="text-[11px] font-bold text-slate-300">Trading Pair:</span>
            <span className="text-xs font-mono font-bold text-[#00e5ff]">{activeSymbol}</span>
          </div>
          <div className="flex space-x-1">
            {[
              { sym: 'BTCUSDT', label: 'BTC', min: '$50+' },
              { sym: 'ETHUSDT', label: 'ETH', min: '$25+' },
              { sym: 'SOLUSDT', label: 'SOL', min: '$10+' },
            ].map((p) => {
              const isSel = activeSymbol === p.sym;
              return (
                <button
                  key={p.sym}
                  onClick={() => {
                    if (hasPosition && !isSel) {
                      alert(`Cannot switch instrument while an active position is open in ${activeSymbol}! Close position first.`);
                      return;
                    }
                    if (onSymbolChange && !isSel) {
                      onSymbolChange(p.sym);
                    }
                  }}
                  className={`px-2 py-0.5 rounded text-xs font-mono font-bold transition flex items-center space-x-1 cursor-pointer ${
                    isSel
                      ? 'bg-[#00e5ff]/20 text-[#00e5ff] border border-[#00e5ff]/50 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200 border border-[#182338] hover:bg-[#141d2f]'
                  }`}
                  title={`${p.sym} - Recommended capital ${p.min}`}
                >
                  <span>{p.label}</span>
                  <span className="text-[9px] text-slate-500 font-normal">({p.min})</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Low Capital Advisory Banner */}
        {capitalBase < currentInst.min_capital && (
          <div className="p-2.5 mb-3 bg-amber-500/15 border border-amber-500/30 rounded-lg text-[11px] font-mono text-amber-300">
            ⚠️ <strong>Low Capital Alert:</strong> Min recommended capital for {activeSymbol} is ${currentInst.min_capital} (Min notional: ${currentInst.min_notional}). 
            {activeSymbol !== 'SOLUSDT' && ' Switch to SOL/USDT to trade with $10+ safely!'}
          </div>
        )}
        {activeSymbol === 'SOLUSDT' && capitalBase <= 25 && (
          <div className="p-2.5 mb-3 bg-emerald-500/15 border border-emerald-500/30 rounded-lg text-[11px] font-mono text-emerald-300">
            ✨ <strong>$10 Capital Ready:</strong> SOL/USDT min order is ${currentInst.min_notional} (0.01 SOL). At {leverage}x leverage, requires only ~${(currentInst.min_notional / leverage).toFixed(2)} margin!
          </div>
        )}

        {/* Capital Compounding & Sizing Station */}
        <div className="bg-[#121826] border border-[#1e273d] rounded-xl p-3.5 mb-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center space-x-1.5 text-xs font-bold text-slate-200">
              <Calculator className="w-3.5 h-3.5 text-[#00e5ff]" />
              <span>Capital Compounding &amp; Lot Sizing</span>
            </div>

            {/* Mode Switcher: AUTO vs MANUAL */}
            <div className="flex bg-[#090d16] p-0.5 rounded-lg border border-[#1b253b]">
              <button
                onClick={() => {
                  setSizingMode('AUTO');
                  pushSizingUpdate({ sizing_mode: 'AUTO' });
                }}
                className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold transition ${
                  sizingMode === 'AUTO' ? 'bg-[#1b253b] text-[#00e5ff] shadow' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                AUTO (Risk %)
              </button>
              <button
                onClick={() => {
                  setSizingMode('MANUAL');
                  pushSizingUpdate({ sizing_mode: 'MANUAL' });
                }}
                className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold transition ${
                  sizingMode === 'MANUAL' ? 'bg-[#1b253b] text-[#00e5ff] shadow' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                MANUAL LOTS
              </button>
            </div>
          </div>

          {/* Sizing Controls Grid */}
          <div className="grid grid-cols-2 gap-2.5 mb-3 text-xs font-mono">
            {/* Capital Base Input */}
            <div className="bg-[#090d16] p-2 rounded-lg border border-[#182236]">
              <div className="flex items-center justify-between mb-1">
                <span className="text-slate-400 text-[10px]">Trading Capital ($)</span>
                {currentMode === 'PAPER' && (
                  <button
                    onClick={handleResetWallet}
                    className="text-[9px] text-[#00e5ff] hover:text-[#4df0ff] flex items-center space-x-1 font-mono transition cursor-pointer"
                    title="Reset paper wallet to this amount"
                  >
                    <RotateCcw className="w-2.5 h-2.5" />
                    <span>Reset</span>
                  </button>
                )}
              </div>
              <div className="flex items-center space-x-1">
                <span className="text-slate-400">$</span>
                <input
                  type="number"
                  step="5"
                  min="5"
                  max="100000"
                  value={capitalBase}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value) || 10;
                    setCapitalBase(val);
                    pushSizingUpdate({ capital_base: val });
                  }}
                  className="w-full bg-transparent text-white font-bold text-sm focus:outline-none"
                />
              </div>
            </div>

            {/* Lot Size Control / Override */}
            <div className="bg-[#090d16] p-2 rounded-lg border border-[#182236]">
              <div className="flex items-center justify-between mb-1">
                <span className="text-slate-400 text-[10px]">Lot Size ({baseAsset})</span>
                {sizingMode === 'MANUAL' && (
                  <div className="flex items-center space-x-1">
                    <button
                      onClick={() => adjustLotSize(-stepSize)}
                      className="p-0.5 bg-[#172136] hover:bg-[#22314e] text-slate-300 rounded cursor-pointer"
                      title={`Decrease ${stepSize}`}
                    >
                      <Minus className="w-2.5 h-2.5" />
                    </button>
                    <button
                      onClick={() => adjustLotSize(stepSize)}
                      className="p-0.5 bg-[#172136] hover:bg-[#22314e] text-slate-300 rounded cursor-pointer"
                      title={`Increase ${stepSize}`}
                    >
                      <Plus className="w-2.5 h-2.5" />
                    </button>
                  </div>
                )}
              </div>
              <div className="flex items-center space-x-1">
                <input
                  type="number"
                  step={stepSize}
                  min={minQty}
                  max="100.0"
                  disabled={sizingMode === 'AUTO'}
                  value={effectiveLots}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value) || minQty;
                    setManualLots(val);
                    pushSizingUpdate({ manual_lot_size: val });
                  }}
                  className={`w-full bg-transparent font-bold text-sm focus:outline-none ${
                    sizingMode === 'AUTO' ? 'text-[#00e5ff]' : 'text-amber-400'
                  }`}
                />
                <span className="text-[10px] text-slate-400">{baseAsset}</span>
              </div>
            </div>
          </div>

          {/* Quick Preset Buttons for Manual Lot Scaling */}
          {sizingMode === 'MANUAL' && (
            <div className="flex items-center space-x-1.5 mb-3">
              {currentPresets.map((preset) => (
                <button
                  key={preset}
                  onClick={() => {
                    setManualLots(preset);
                    pushSizingUpdate({ manual_lot_size: preset });
                  }}
                  className={`flex-1 py-1 rounded text-[10px] font-mono font-bold transition border cursor-pointer ${
                    manualLots === preset
                      ? 'bg-[#00e5ff]/20 text-[#00e5ff] border-[#00e5ff]/40'
                      : 'bg-[#090d16] text-slate-400 border-[#182236] hover:text-white'
                  }`}
                >
                  {preset} {baseAsset}
                </button>
              ))}
            </div>
          )}

          {/* Real-time Order Math Card */}
          <div className="bg-[#090d16] p-2.5 rounded-lg border border-[#182236] text-[11px] font-mono space-y-1.5">
            <div className="flex justify-between text-slate-400">
              <span>Order Notional Value:</span>
              <span className="font-bold text-white">${notionalValue.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Margin Required ({leverage}x):</span>
              <span className="font-bold text-emerald-400">${marginRequired.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Free Account Buffer:</span>
              <span className="font-bold text-sky-400">${freeMarginBuffer.toFixed(2)}</span>
            </div>
            <div className="flex justify-between border-t border-[#162033] pt-1 text-slate-400">
              <span>Max Loss at SL (1.5x ATR):</span>
              <span className="font-bold text-amber-400">${slDollarRisk.toFixed(2)} ({slRiskPctOfCapital.toFixed(2)}%)</span>
            </div>
          </div>
        </div>

        {/* Risk & Leverage Inputs */}
        <div className="grid grid-cols-3 gap-2.5 mb-4 text-xs font-mono">
          <div className="bg-[#121826] p-2 rounded-lg border border-[#1e273d]">
            <span className="text-slate-400 text-[10px] block mb-1">Risk / Trade</span>
            <div className="flex items-center space-x-1">
              <input
                type="number"
                step="0.5"
                min="0.5"
                max="5.0"
                value={riskPct}
                onChange={(e) => {
                  const val = parseFloat(e.target.value) || 1.0;
                  setRiskPct(val);
                  pushSizingUpdate({ risk_per_trade_pct: val });
                }}
                className="w-10 bg-transparent text-white font-bold focus:outline-none"
              />
              <span className="text-slate-400">%</span>
            </div>
          </div>

          <div className="bg-[#121826] p-2 rounded-lg border border-[#1e273d]">
            <span className="text-slate-400 text-[10px] block mb-1">Leverage</span>
            <div className="flex items-center space-x-1">
              <input
                type="number"
                step="1"
                min="1"
                max="50"
                value={leverage}
                onChange={(e) => {
                  const val = parseInt(e.target.value) || 10;
                  setLeverage(val);
                  pushSizingUpdate({ leverage: val });
                }}
                className="w-10 bg-transparent text-white font-bold focus:outline-none"
              />
              <span className="text-slate-400">x</span>
            </div>
          </div>

          <div className="bg-[#121826] p-2 rounded-lg border border-[#1e273d]">
            <span className="text-slate-400 text-[10px] block mb-1">Daily Cap</span>
            <div className="flex items-center space-x-1">
              <input
                type="number"
                step="0.5"
                min="1"
                max="10"
                value={dailyCap}
                onChange={(e) => setDailyCap(parseFloat(e.target.value) || 2.5)}
                className="w-10 bg-transparent text-white font-bold focus:outline-none"
              />
              <span className="text-slate-400">%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Control Buttons */}
      <div className="pt-3 border-t border-[#1b2336] flex items-center space-x-2">
        {isRunning ? (
          <button
            onClick={onPause}
            className="flex-1 py-2 bg-[#172136] hover:bg-[#202c46] text-amber-400 font-medium rounded-lg text-xs transition border border-[#233150] cursor-pointer"
          >
            Pause Trading
          </button>
        ) : (
          <button
            onClick={onResume}
            className="flex-1 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg text-xs transition cursor-pointer"
          >
            Start Engine
          </button>
        )}

        <button
          onClick={onFlatten}
          className="px-4 py-2 bg-rose-600/80 hover:bg-rose-600 text-white font-medium rounded-lg text-xs transition border border-rose-500/40 cursor-pointer"
          title="Emergency Flatten"
        >
          Flatten
        </button>
      </div>
    </div>
  );
}
