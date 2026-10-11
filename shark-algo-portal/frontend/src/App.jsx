import React, { useEffect, useState, useCallback, useRef } from 'react';
import Navbar from './components/Navbar';
import MetricsPanel from './components/MetricsPanel';
import ChartWidget from './components/ChartWidget';
import PositionWidget from './components/PositionWidget';
import ControlPanel from './components/ControlPanel';
import TradeLedger from './components/TradeLedger';

export default function App() {
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  // REST fallback fetch
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (e) {
      console.warn('REST status fetch failed:', e);
    }
  }, []);

  // WebSocket lifecycle
  useEffect(() => {
    fetchStatus();

    let isMounted = true;
    let reconnectTimeout = null;

    const connectWS = () => {
      // Connect to relative /ws (proxied by Vite to ws://localhost:5001/ws) or direct
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMounted) return;
        setConnected(true);
        console.log('[WS] Connected to Shark Trading Engine');
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'status' && payload.data) {
            setStatus(payload.data);
          }
        } catch (err) {
          console.error('[WS] Parse error:', err);
        }
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setConnected(false);
        console.warn('[WS] Disconnected — reconnecting in 3s...');
        reconnectTimeout = setTimeout(connectWS, 3000);
      };

      ws.onerror = (err) => {
        console.error('[WS] Error:', err);
        ws.close();
      };
    };

    connectWS();

    // Fallback polling every 5s if WS drops
    const pollInterval = setInterval(() => {
      if (!connected) {
        fetchStatus();
      }
    }, 5000);

    return () => {
      isMounted = false;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      clearInterval(pollInterval);
      if (wsRef.current) wsRef.current.close();
    };
  }, [fetchStatus, connected]);

  // Actions
  const handlePause = async () => {
    try {
      await fetch('/api/control/pause', { method: 'POST' });
      fetchStatus();
    } catch (e) {
      alert('Error pausing bot: ' + e.message);
    }
  };

  const handleResume = async () => {
    try {
      await fetch('/api/control/resume', { method: 'POST' });
      fetchStatus();
    } catch (e) {
      alert('Error resuming bot: ' + e.message);
    }
  };

  const handleFlatten = async () => {
    try {
      const res = await fetch('/api/control/flatten', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        alert('✅ Emergency Flatten executed successfully');
      }
      fetchStatus();
    } catch (e) {
      alert('Error executing flatten: ' + e.message);
    }
  };

  const [selectedSymbol, setSelectedSymbol] = useState('BTCUSDT');
  const activeSymbol = status?.symbol || selectedSymbol;

  const handleSymbolChange = async (newSymbol) => {
    try {
      const res = await fetch('/api/control/symbol', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: newSymbol }),
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || 'Failed to switch trading pair');
      } else {
        setSelectedSymbol(newSymbol);
        fetchStatus();
      }
    } catch (e) {
      alert('Error switching trading pair: ' + e.message);
    }
  };

  const handleModeChange = async (newMode) => {
    try {
      const res = await fetch('/api/control/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: newMode }),
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || 'Failed to switch mode');
      } else {
        fetchStatus();
      }
    } catch (e) {
      alert('Error switching mode: ' + e.message);
    }
  };

  return (
    <div className="min-h-screen bg-[#080b11] text-slate-100 flex flex-col">
      {/* Top Navigation */}
      <Navbar
        status={status}
        connected={connected}
        currentSymbol={activeSymbol}
        onSymbolChange={handleSymbolChange}
        onPause={handlePause}
        onResume={handleResume}
        onFlatten={handleFlatten}
      />

      {/* Main Terminal Body */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 space-y-4">
        {/* Top Analytics Metrics */}
        <MetricsPanel
          stats={status?.stats}
          risk={status?.risk}
          market={status?.market}
        />

        {/* Center Grid: Chart (Left) & Widgets (Right) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Main Chart Column (8 cols on large screens) */}
          <div className="lg:col-span-8">
            <ChartWidget
              position={status?.position}
              market={status?.market}
              symbol={activeSymbol}
            />
          </div>

          {/* Right Control & Position Column (4 cols) */}
          <div className="lg:col-span-4 flex flex-col space-y-4">
            <div className="flex-1 min-h-[220px]">
              <PositionWidget
                position={status?.position}
                onFlatten={handleFlatten}
              />
            </div>
            <div className="flex-1 min-h-[260px]">
              <ControlPanel
                status={status}
                currentSymbol={activeSymbol}
                onSymbolChange={handleSymbolChange}
                onModeChange={handleModeChange}
                onPause={handlePause}
                onResume={handleResume}
                onFlatten={handleFlatten}
              />
            </div>
          </div>
        </div>

        {/* Bottom Trade History & Telemetry Ledger */}
        <TradeLedger
          trades={status?.trade_history}
          logs={status?.logs}
        />
      </main>

      {/* Institutional Footer */}
      <footer className="border-t border-[#141b2b] bg-[#090d16] px-4 py-3 text-xs text-slate-500 font-mono">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center space-x-4">
            <span>SHARK EXCHANGE API v1</span>
            <span>•</span>
            <span>DONCHIAN EXPANSION ENGINE</span>
            <span>•</span>
            <span>LOCAL HOSTED: 5000 / 5001</span>
          </div>
          <div>
            <span>AWS EC2 READY • MODULAR ARCHITECTURE</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
