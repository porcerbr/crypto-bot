# utils.py
import time
from datetime import datetime, timezone
from config import Config

# ── formatação e log ─────────────────────────────────────────
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

# ── categorias de ativos ─────────────────────────────────────
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

# ── mapeamento Yahoo Finance ─────────────────────────────────
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

# ── moeda e conversões ────────────────────────────────────────
_FX_RATE_CACHE = {}

def currency_to_usd(currency):
    currency = (currency or "USD").upper()
    if currency == "USD":
        return 1.0
    now = time.time()
    cached = _FX_RATE_CACHE.get(currency)
    if cached and now - cached["ts"] < 300:
        return cached["rate"]
    # evita quebra se yfinance não estiver disponível
    try:
        import yfinance as yf
    except ImportError:
        return 1.0
    pair_map = {
        "EUR": "EURUSD=X", "GBP": "GBPUSD=X", "AUD": "AUDUSD=X", "NZD": "NZDUSD=X",
        "CAD": "USDCAD=X", "CHF": "USDCHF=X", "JPY": "USDJPY=X", "ZAR": "USDZAR=X",
    }
    ticker = pair_map.get(currency)
    rate = 1.0
    try:
        if ticker:
            df = yf.Ticker(ticker).history(period="5d", interval="1d")
            if len(df) and float(df["Close"].iloc[-1]) > 0:
                last = float(df["Close"].iloc[-1])
                if currency in {"CAD", "CHF", "JPY", "ZAR"}:
                    rate = 1.0 / last
                else:
                    rate = last
    except Exception:
        rate = 1.0
    _FX_RATE_CACHE[currency] = {"rate": float(rate), "ts": now}
    return float(rate)

# ── informações do símbolo ────────────────────────────────────
def contract_size_for(symbol):
    if symbol in Config.CONTRACT_SIZES_SPECIFIC:
        return Config.CONTRACT_SIZES_SPECIFIC[symbol]
    return Config.CONTRACT_SIZES.get(asset_cat(symbol), 1)

def max_leverage_for(symbol):
    if symbol in Config.MAX_LEVERAGE_BY_SYM:
        return Config.MAX_LEVERAGE_BY_SYM[symbol]
    return Config.MAX_LEVERAGE_BY_CAT.get(asset_cat(symbol), 100)

def symbol_profile(symbol):
    cat = asset_cat(symbol)
    cs = contract_size_for(symbol)
    if cat == "FOREX":
        return {"kind": "FX", "base": symbol[:3], "quote": symbol[3:], "contract_size": cs}
    if cat == "COMMODITIES":
        return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": cs}
    if cat == "INDICES":
        return {"kind": "INDEX", "base": "USD", "quote": "USD", "contract_size": cs}
    if cat == "CRYPTO":
        return {"kind": "CRYPTO", "base": "USD", "quote": "USD", "contract_size": cs}
    return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": cs}
