from datetime import datetime
from config import Config

def fmt(value: float) -> str:
    if value is None: return "0"
    if abs(value) >= 10000: return f"{value:,.2f}"
    if abs(value) >= 1000: return f"{value:.2f}"
    if abs(value) >= 10: return f"{value:.4f}"
    if abs(value) >= 1: return f"{value:.5f}"
    return f"{value:.6f}"

def log(msg: str):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

def asset_name(symbol):
    return Config.FXGOLD_ASSETS.get(symbol, symbol)

def is_jpy_pair(symbol):
    return symbol.endswith("JPY")

def jpy_to_usd(pnl_jpy, usdjpy_price):
    """Converte P&L em JPY para USD usando cotação atual de USDJPY."""
    if usdjpy_price and usdjpy_price > 0:
        return pnl_jpy / usdjpy_price
    return 0.0

def max_leverage(symbol, lot=0.01):
    """
    Alavancagem dinâmica Tickmill (MT5):
    Forex: 0-2 lotes → 1:1000 | 2.01-200 → 1:500
    XAUUSD: 0-1 lote → 1:1000 | 1.01-100 → 1:500
    """
    if symbol == "XAUUSD":
        return 1000 if lot <= 1.0 else 500
    return 1000 if lot <= 2.0 else 500

def get_sl_tp_pct(leverage, rr=None):
    """Fallback porcentagem. Preferir ATR-based em signals.py."""
    sl = Config.SL_TP_BASE_MULTIPLIER / max(1, leverage)
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    sl = round(sl, 2)
    rr = rr or Config.TP_SL_RATIO
    tp = round(sl * rr, 2)
    return sl, tp

def get_sl_tp_atr(entry, atr, direction, atr_sl_mult=1.5, atr_tp_mult=2.5):
    """SL/TP baseado em ATR — mais preciso para Tickmill."""
    sl_dist = atr * atr_sl_mult
    tp_dist = atr * atr_tp_mult
    if direction == "BUY":
        sl = round(entry - sl_dist, 5)
        tp = round(entry + tp_dist, 5)
    else:
        sl = round(entry + sl_dist, 5)
        tp = round(entry - tp_dist, 5)
    return sl, tp, sl_dist, tp_dist
