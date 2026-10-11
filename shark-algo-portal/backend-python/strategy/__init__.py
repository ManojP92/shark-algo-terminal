# strategy/__init__.py
from .donchian_breakout import DonchianBreakoutStrategy, TradeSignal, TrailingState, Signal
from .bollinger_rsi import BollingerRsiStrategy
from .supertrend import SupertrendMomentumStrategy
from .regime_adaptive import RegimeAdaptiveStrategy

STRATEGY_REGISTRY = {
    "DONCHIAN": DonchianBreakoutStrategy,
    "DONCHIAN_BREAKOUT": DonchianBreakoutStrategy,
    "BOLLINGER_RSI": BollingerRsiStrategy,
    "BOLLINGER_REVERSION": BollingerRsiStrategy,
    "SUPERTREND": SupertrendMomentumStrategy,
    "SUPERTREND_MOMENTUM": SupertrendMomentumStrategy,
    "REGIME_ADAPTIVE": RegimeAdaptiveStrategy,
    "ADAPTIVE_HYBRID": RegimeAdaptiveStrategy,
}


def get_strategy(name: str = "DONCHIAN", **kwargs):
    """Factory function returning strategy instance by name."""
    clean_name = (name or "DONCHIAN").strip().upper()
    cls = STRATEGY_REGISTRY.get(clean_name, DonchianBreakoutStrategy)
    try:
        return cls(**kwargs)
    except TypeError:
        # Fallback if kwargs don't match specific class constructor
        return cls()
