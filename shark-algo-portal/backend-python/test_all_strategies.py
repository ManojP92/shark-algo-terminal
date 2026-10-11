import requests
import pandas as pd
from backtester import run_backtest

res = requests.get('http://localhost:3001/api/klines/history?pair=BTCUSDT&interval=15m&days=14')
raw = res.json()['data']
df = pd.DataFrame(raw)
df.rename(columns={'startTime': 'timestamp'}, inplace=True)
df['timestamp'] = pd.to_datetime(df['timestamp'].astype('int64'), unit='ms', utc=True)
for col in ['open', 'high', 'low', 'close', 'volume']:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df.sort_values('timestamp', inplace=True)
df.reset_index(drop=True, inplace=True)

strategies = ['DONCHIAN', 'BOLLINGER_RSI', 'SUPERTREND', 'REGIME_ADAPTIVE']
print(f"=== Testing 4 Strategies over {len(df)} 15m BTC candles ===")
for s in strategies:
    bt = run_backtest(df.copy(), strategy_name=s, initial_capital=100.0, risk_pct=1.0, leverage=10, min_qty=0.001, step_size=0.001, min_notional=115.0)
    summ = bt['summary']
    print(f"[{s:<16}] ROI: {summ['roi_pct']:>6.2f}% | WinRate: {summ['win_rate']:>4.1f}% | PF: {summ['profit_factor']:>4.2f} | Trades: {summ['total_trades']:>2d} | MaxDD: {summ['max_drawdown_pct']}%")
