import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import { RefreshCw, TrendingUp, BarChart2 } from 'lucide-react';

export default function ChartWidget({ position, market, symbol = 'BTCUSDT' }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const volumeSeriesRef = useRef(null);
  const dcUpperLineRef = useRef(null);
  const dcLowerLineRef = useRef(null);
  const entryLineRef = useRef(null);
  const slLineRef = useRef(null);

  const [timeframe, setTimeframe] = useState('15m');
  const [loading, setLoading] = useState(true);
  const [lastPrice, setLastPrice] = useState(null);

  // Initialize TradingView Lightweight Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b0f19' },
        textColor: '#94a3b8',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: '#00e5ff', width: 1, style: 3 },
        horzLine: { color: '#00e5ff', width: 1, style: 3 },
      },
      rightPriceScale: {
        borderColor: '#1e293b',
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
      },
      width: chartContainerRef.current.clientWidth,
      height: 480,
    });

    // Candlestick Series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00e676',
      downColor: '#ff1744',
      borderVisible: false,
      wickUpColor: '#00e676',
      wickDownColor: '#ff1744',
    });

    // Volume Series
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '', // overlay
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    // Donchian Channel Line Series
    const dcUpperLine = chart.addLineSeries({
      color: 'rgba(0, 229, 255, 0.65)',
      lineWidth: 1,
      lineStyle: 2, // dashed
      title: 'DC 25 High',
    });

    const dcLowerLine = chart.addLineSeries({
      color: 'rgba(255, 171, 0, 0.65)',
      lineWidth: 1,
      lineStyle: 2, // dashed
      title: 'DC 25 Low',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    dcUpperLineRef.current = dcUpperLine;
    dcLowerLineRef.current = dcLowerLine;

    // Window resize handler
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // Fetch candle data
  const loadCandles = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/candles/${timeframe}?symbol=${symbol}&limit=250`);
      const body = await res.json();
      if (body.ok && Array.isArray(body.data)) {
        const sorted = [...body.data].sort((a, b) => Number(a.startTime) - Number(b.startTime));

        const candles = sorted.map((c) => ({
          time: Math.floor(Number(c.startTime) / 1000),
          open: parseFloat(c.open),
          high: parseFloat(c.high),
          low: parseFloat(c.low),
          close: parseFloat(c.close),
        }));

        const volumes = sorted.map((c) => ({
          time: Math.floor(Number(c.startTime) / 1000),
          value: parseFloat(c.volume),
          color: parseFloat(c.close) >= parseFloat(c.open) ? 'rgba(0, 230, 118, 0.25)' : 'rgba(255, 23, 68, 0.25)',
        }));

        if (candleSeriesRef.current && volumeSeriesRef.current) {
          candleSeriesRef.current.setData(candles);
          volumeSeriesRef.current.setData(volumes);

          // Calculate Donchian 25 lines on client
          const dcHighs = [];
          const dcLows = [];
          const period = 25;

          for (let i = period; i < candles.length; i++) {
            const slice = candles.slice(i - period, i); // strictly prior candles
            const highest = Math.max(...slice.map((k) => k.high));
            const lowest = Math.min(...slice.map((k) => k.low));
            dcHighs.push({ time: candles[i].time, value: highest });
            dcLows.push({ time: candles[i].time, value: lowest });
          }

          if (dcUpperLineRef.current && dcLowerLineRef.current) {
            dcUpperLineRef.current.setData(dcHighs);
            dcLowerLineRef.current.setData(dcLows);
          }

          if (candles.length > 0) {
            setLastPrice(candles[candles.length - 1].close);
          }
        }
      }
    } catch (err) {
      console.error('Error fetching candles:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCandles();
    const interval = setInterval(loadCandles, 15000); // refresh every 15s
    return () => clearInterval(interval);
  }, [timeframe, symbol]);

  // Overlay trade position lines (Entry & Trailing SL)
  useEffect(() => {
    if (!candleSeriesRef.current) return;

    // Remove previous price lines
    if (entryLineRef.current) {
      try { candleSeriesRef.current.removePriceLine(entryLineRef.current); } catch (e) {}
      entryLineRef.current = null;
    }
    if (slLineRef.current) {
      try { candleSeriesRef.current.removePriceLine(slLineRef.current); } catch (e) {}
      slLineRef.current = null;
    }

    if (position && position.entry) {
      // Entry line
      entryLineRef.current = candleSeriesRef.current.createPriceLine({
        price: position.entry,
        color: '#00e5ff',
        lineWidth: 2,
        lineStyle: 0,
        axisLabelVisible: true,
        title: `ENTRY (${position.side})`,
      });

      // Stop loss / Trailing stop line
      if (position.trail_sl || position.sl) {
        slLineRef.current = candleSeriesRef.current.createPriceLine({
          price: position.trail_sl || position.sl,
          color: '#ff1744',
          lineWidth: 2,
          lineStyle: 1,
          axisLabelVisible: true,
          title: 'TRAIL SL',
        });
      }
    }
  }, [position]);

  return (
    <div className="bg-[#0e131f] border border-[#1b2336] rounded-xl p-4 shadow-xl">
      {/* Chart Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3 pb-3 border-b border-[#1b2336]">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-1.5">
            <span className="font-bold text-base text-white">
              {symbol.replace('USDT', ' / USDT')}
            </span>
            <span className="text-xs text-slate-400 font-mono">Perpetual</span>
          </div>

          {lastPrice !== null && (
            <div className="flex items-center space-x-2 pl-3 border-l border-[#1b2336]">
              <span className="text-lg font-mono font-bold text-white">
                ${lastPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
              </span>
            </div>
          )}
        </div>

        {/* Chart Tools & Timeframe */}
        <div className="flex items-center space-x-2">
          <div className="flex bg-[#090d16] p-0.5 rounded-lg border border-[#1b2336]">
            {['5m', '15m', '1h'].map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-3 py-1 rounded-md text-xs font-mono font-bold transition ${
                  timeframe === tf
                    ? 'bg-[#1b2336] text-[#00e5ff] shadow'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          <button
            onClick={loadCandles}
            className="p-1.5 bg-[#172136] hover:bg-[#202c46] text-slate-300 rounded-lg border border-[#233150] transition"
            title="Reload candles"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Chart Indicator Legend */}
      <div className="flex items-center space-x-4 text-[11px] font-mono text-slate-400 mb-2 px-1">
        <span className="flex items-center space-x-1">
          <span className="w-2.5 h-0.5 bg-[#00e5ff]"></span>
          <span>Donchian Upper (25)</span>
        </span>
        <span className="flex items-center space-x-1">
          <span className="w-2.5 h-0.5 bg-[#ffab00]"></span>
          <span>Donchian Lower (25)</span>
        </span>
        {position && (
          <>
            <span className="flex items-center space-x-1 text-[#00e5ff]">
              <span className="w-2.5 h-0.5 bg-[#00e5ff]"></span>
              <span>Entry: ${position.entry}</span>
            </span>
            <span className="flex items-center space-x-1 text-rose-400">
              <span className="w-2.5 h-0.5 bg-rose-500"></span>
              <span>Trail SL: ${position.trail_sl || position.sl}</span>
            </span>
          </>
        )}
      </div>

      {/* Chart Canvas Container */}
      <div className="relative w-full overflow-hidden rounded-lg">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40 backdrop-blur-xs">
            <div className="flex items-center space-x-2 text-xs font-mono text-[#00e5ff]">
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>SYNCING MARKET DATA...</span>
            </div>
          </div>
        )}
        <div ref={chartContainerRef} className="w-full" />
      </div>
    </div>
  );
}
