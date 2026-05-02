from __future__ import annotations
from datetime import datetime, timezone, timedelta
from models import Candle

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def pip_size(symbol: str) -> float:
    s = symbol.upper()
    if "JPY" in s:
        return 0.01
    if "XAU" in s or "GOLD" in s:
        return 0.1
    return 0.0001

def round_price(symbol: str, price: float) -> float:
    p = pip_size(symbol)
    if p == 0.01:
        return round(price, 3)
    if p == 0.1:
        return round(price, 2)
    return round(price, 5)

def in_session(now_utc: datetime, london_start: int, london_end: int, ny_start: int, ny_end: int) -> bool:
    h = now_utc.hour
    london = london_start <= h < london_end
    ny = ny_start <= h < ny_end
    return london or ny

def is_high_impact_news_window(symbol: str) -> bool:
    # Placeholder para calendário econômico real.
    return False

def candle_body(c: Candle) -> float:
    return abs(c.close - c.open)

def candle_range(c: Candle) -> float:
    return max(c.high - c.low, 1e-12)
