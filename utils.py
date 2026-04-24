# utils.py
from datetime import datetime, timezone
from config import Config

def fmt(p: float) -> str:
    if not p:
        return "0"
    if p >= 10000:
        return f"{p:,.2f}"
    if p >= 1000:
        return f"{p:.2f}"
    if p >= 10:
        return f"{p:.4f}"
    if p >= 1:
        return f"{p:.5f}"
    return f"{p:.6f}"

def log(msg):
    print(f"[{datetime.now(Config.BR_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)

def asset_cat(s):
    for cat, info in Config.MARKET_CATEGORIES.items():
        if s in info["assets"]:
            return cat
    return "CRYPTO"

def asset_name(s):
    for info in Config.MARKET_CATEGORIES.values():
        if s in info["assets"]:
            return info["assets"][s]
    return s

def vol_reliable(s):
    return asset_cat(s) not in ("INDICES",)

# ── Mapeamento Tickmill → Yahoo Finance ───────────────────────
TICKMILL_TO_YF = {
    "BTCUSD":  "BTC-USD",  "ETHUSD":  "ETH-USD",  "SOLUSD":  "SOL-USD",
    "BNBUSD":  "BNB-USD",  "XRPUSD":  "XRP-USD",  "ADAUSD":  "ADA-USD",
    "DOGEUSD": "DOGE-USD", "LTCUSD":  "LTC-USD",
    "XAUUSD":  "GC=F",     "XAGUSD":  "SI=F",
    "XTIUSD":  "CL=F",     "BRENT":   "BZ=F",
    "NATGAS":  "NG=F",     "COPPER":  "HG=F",
    "US500":   "ES=F",     "USTEC":   "NQ=F",     "US30":    "YM=F",
    "DE40":    "^GDAXI",   "UK100":   "^FTSE",    "JP225":   "^N225",
    "AUS200":  "^AXJO",    "STOXX50": "^STOXX50E",
}

def to_yf(s):
    if s in TICKMILL_TO_YF:
        return TICKMILL_TO_YF[s]
    if len(s) == 6 and s.isalpha():
        return f"{s}=X"
    if "-" in s or s.startswith("^") or s.endswith("=F"):
        return s
    return f"{s}=X"

def all_syms():
    out = []
    for c in Config.MARKET_CATEGORIES.values():
        out.extend(c["assets"].keys())
    return out

def mkt_open(cat):
    now = datetime.now(timezone.utc)
    h = now.hour
    wd = now.weekday()
    if cat == "CRYPTO":
        return True
    if wd >= 5:
        return False
    if cat == "FOREX":
        return Config.FOREX_OPEN_UTC <= h < Config.FOREX_CLOSE_UTC
    if cat == "COMMODITIES":
        return Config.COMM_OPEN_UTC <= h < Config.COMM_CLOSE_UTC
    if cat == "INDICES":
        return Config.IDX_OPEN_UTC <= h < Config.IDX_CLOSE_UTC
    return True
