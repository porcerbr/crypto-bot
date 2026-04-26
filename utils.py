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

def max_leverage(symbol):
    if symbol in Config.MAX_LEVERAGE:
        return Config.MAX_LEVERAGE[symbol]
    # fallback
    if symbol == "XAUUSD":
        return Config.MAX_LEVERAGE["XAUUSD"]
    return Config.MAX_LEVERAGE.get("FOREX", 500)

def get_sl_tp_pct(leverage, rr=None):
    sl = Config.SL_TP_BASE_MULTIPLIER / max(1, leverage)
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    sl = round(sl, 2)
    rr = rr or Config.TP_SL_RATIO
    tp = round(sl * rr, 2)
    return sl, tp
