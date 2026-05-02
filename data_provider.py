from __future__ import annotations
from typing import List
from datetime import timedelta
import math
import requests

from models import Candle, utc_now

class MarketDataProvider:
    def get_candles(self, symbol: str, timeframe: str, limit: int) -> List[Candle]:
        raise NotImplementedError

    def get_spread_pips(self, symbol: str) -> float:
        return 0.0

class TwelveDataProvider(MarketDataProvider):
    def __init__(self, api_key: str, base_url: str = "https://api.twelvedata.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def get_candles(self, symbol: str, timeframe: str, limit: int) -> List[Candle]:
        if not self.api_key:
            return self._demo_candles(symbol, limit)

        params = {
            "symbol": symbol,
            "interval": timeframe,
            "outputsize": limit,
            "apikey": self.api_key,
            "format": "JSON",
        }
        url = f"{self.base_url}/time_series"
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        payload = r.json()
        values = payload.get("values") or []
        candles: List[Candle] = []
        for row in reversed(values):
            candles.append(
                Candle(
                    timestamp=utc_now(),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                )
            )
        return candles[-limit:]

    def get_spread_pips(self, symbol: str) -> float:
        return 0.0

    def _demo_candles(self, symbol: str, limit: int) -> List[Candle]:
        base = 1.10 if "JPY" not in symbol else 150.0
        if "XAU" in symbol:
            base = 2300.0
        candles = []
        now = utc_now()
        price = base
        for i in range(limit):
            drift = math.sin(i / 7.0) * 0.002 + math.sin(i / 19.0) * 0.001
            noise = math.sin(i * 1.7) * 0.0006
            open_ = price
            close = price * (1 + drift + noise)
            high = max(open_, close) + abs(close - open_) * 0.8 + base * 0.0005
            low = min(open_, close) - abs(close - open_) * 0.8 - base * 0.0005
            candles.append(
                Candle(
                    timestamp=now - timedelta(minutes=(limit - i) * 60),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=1000 + i,
                )
            )
            price = close
        return candles
