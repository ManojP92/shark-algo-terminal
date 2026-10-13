import React, { useEffect, useState, useCallback, useRef } from 'react';
import Navbar from './components/Navbar';
import MetricsPanel from './components/MetricsPanel';
import ChartWidget from './components/ChartWidget';
import PositionWidget from './components/PositionWidget';
import ControlPanel from './components/ControlPanel';
import TradeLedger from './components/TradeLedger';
import BacktestModal from './components/BacktestModal';
import LoginPage from './components/LoginPage';

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  // Check 2FA Auth Session on initial load
  useEffect(() => {
    const token = localStorage.getItem('shark_auth_token');
    if (!token) {
      setIsAuthenticated(false);
      setIsCheckingAuth(false);
      return;
    }

    fetch(`/api/auth/check?token=${encodeURIComponent(token)}`)
      .then((res) => res.json())
      .then((data) => {
        if (data?.authenticated) {
          setIsAuthenticated(true);
        } else {
          localStorage.removeItem('shark_auth_token');
          setIsAuthenticated(false);
        }
      })
      .catch((err) => {
        console.warn('Auth check failed:', err);
        setIsAuthenticated(false);
      })
      .finally(() => {
        setIsCheckingAuth(false);
      });
  }, []);

  const handleLogout = async () => {
    const token = localStorage.getItem('shark_auth_token');
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
    } catch (e) {
      console.warn('Logout error:', e);
    }
    localStorage.removeItem('shark_auth_token');
    setIsAuthenticated(false);
  };

  // REST fallback fetch
  const fetchStatus = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (e) {
      console.warn('REST status fetch failed:', e);
    }
  }, [isAuthenticated]);

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

  const handleClosePosition = async () => {
    try {
      const res = await fetch('/api/control/close-position', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || data.error || 'Failed to close position');
      }
      alert('✅ Position closed successfully at market price');
      fetchStatus();
    } catch (e) {
      alert('Error closing position: ' + e.message);
    }
  };

  const handleFlatten = async () => {
    try {
      const res = await fetch('/api/control/flatten', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || data.error || 'Failed to execute emergency flatten');
      }
      alert('✅ Emergency Flatten executed: position closed and bot halted');
      fetchStatus();
    } catch (e) {
      alert('Error executing flatten: ' + e.message);
    }
  };


  const [selectedSymbol, setSelectedSymbol] = useState('BTCUSDT');
  const [isBacktestOpen, setIsBacktestOpen] = useState(false);
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

  // Show loader while checking stored session
  if (isCheckingAuth) {
    return (
      <div className="min-h-screen bg-[#080b11] text-slate-100 flex flex-col items-center justify-center space-y-4">
        <div className="w-12 h-12 rounded-2xl bg-[#0e1424] border border-[#1b263b] flex items-center justify-center shadow-lg animate-pulse">
          <span className="text-2xl">🦈</span>
        </div>
        <div className="flex items-center space-x-2 text-xs font-mono text-slate-400">
          <span className="w-2 h-2 rounded-full bg-[#00e5ff] animate-ping" />
          <span>VERIFYING SHARK TERMINAL SECURITY...</span>
        </div>
      </div>
    );
  }

  // Display Telegram 2FA Login Screen if unauthenticated
  if (!isAuthenticated) {
    return <LoginPage onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  return (
    <div className="min-h-screen bg-[#080b11] text-slate-100 flex flex-col">
      {/* Top Navigation */}
      <Navbar
        status={status}
        connected={connected}
        currentSymbol={activeSymbol}
        onSymbolChange={handleSymbolChange}
        onModeChange={handleModeChange}
        onOpenBacktest={() => setIsBacktestOpen(true)}
        onPause={handlePause}
        onResume={handleResume}
        onFlatten={handleFlatten}
        onLogout={handleLogout}
      />

      {/* Main Terminal Body */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 space-y-4">
        {/* Top Analytics Metrics */}
        <MetricsPanel
          stats={status?.stats}
          risk={status?.risk}
          market={status?.market}
          wallet={status?.wallet}
          equity={status?.equity}
          mode={status?.mode}
          capitalBase={status?.sizing?.capital_base}
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
                onClose={handleClosePosition}
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

      {/* Strategy Backtesting & Monte Carlo Modal */}
      <BacktestModal
        isOpen={isBacktestOpen}
        onClose={() => setIsBacktestOpen(false)}
        defaultPair={activeSymbol}
      />
    </div>
  );
}
