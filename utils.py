# utils.py
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

def asset_cat(symbol):
    for cat, info in Config.MARKET_CATEGORIES.items():
        if symbol in info["assets"]:
            return cat
    return "CRYPTO"

def asset_name(symbol):
    for info in Config.MARKET_CATEGORIES.values():
        if symbol in info["assets"]:
            return info["assets"][symbol]
    return symbol

def all_syms():
    syms = []
    for cat in Config.MARKET_CATEGORIES.values():
        syms.extend(cat["assets"].keys())
    return syms

def category_syms(cat):
    return list(Config.MARKET_CATEGORIES[cat]["assets"].keys())

def contract_size_for(symbol):
    if symbol in Config.CONTRACT_SIZES_SPECIFIC:
        return Config.CONTRACT_SIZES_SPECIFIC[symbol]
    return Config.CONTRACT_SIZES.get(asset_cat(symbol), 1)

def max_leverage(symbol):
    return Config.MAX_LEVERAGE.get(asset_cat(symbol), 50)

def get_sl_tp_pct(leverage, rr=None):
    """Calcula SL % baseado na alavancagem, TP pelo RR."""
    sl = Config.SL_TP_BASE_MULTIPLIER / max(1, leverage)
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    sl = round(sl, 2)
    rr = rr or Config.TP_SL_RATIO
    tp = round(sl * rr, 2)
    return sl, tp
