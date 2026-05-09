from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

TIMEFRAME_MINUTES = {
    "M5": 5,
    "M15": 15,
    "H1": 60,
}


class MarketDataProvider(ABC):
    @abstractmethod
    async def get_candles(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    async def get_spread(self, symbol: str) -> float:
        raise NotImplementedError


class DemoLiveProvider(MarketDataProvider):
    def __init__(self, seed: int = 7) -> None:
        self.rng = np.random.default_rng(seed)
        self.buffers: dict[tuple[str, str], pd.DataFrame] = {}

    def _base_price(self, symbol: str) -> float:
        return {
            "EURUSD": 1.0850,
            "GBPUSD": 1.2750,
            "USDJPY": 154.00,
            "XAUUSD": 2350.0,
        }.get(symbol, 100.0)

    def _init_buffer(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        minutes = TIMEFRAME_MINUTES[timeframe]
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        times = [now - timedelta(minutes=minutes * i) for i in range(limit)][::-1]

        base = self._base_price(symbol)
        drift = self.rng.normal(0, 0.15 if symbol != "XAUUSD" else 1.4, size=limit).cumsum()
        prices = base + drift
        highs = prices + np.abs(self.rng.normal(0.03, 0.02, size=limit))
        lows = prices - np.abs(self.rng.normal(0.03, 0.02, size=limit))
        opens = prices + self.rng.normal(0, 0.01, size=limit)
        closes = prices + self.rng.normal(0, 0.01, size=limit)
        volumes = self.rng.integers(100, 1000, size=limit)

        df = pd.DataFrame({
            "time": times,
            "open": opens,
            "high": np.maximum(highs, np.maximum(opens, closes)),
            "low": np.minimum(lows, np.minimum(opens, closes)),
            "close": closes,
            "volume": volumes,
        })
        return df

    async def get_candles(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        await asyncio.sleep(0)
        key = (symbol, timeframe)
        if key not in self.buffers:
            self.buffers[key] = self._init_buffer(symbol, timeframe, limit=max(limit, 500))

        df = self.buffers[key].copy()
        minutes = TIMEFRAME_MINUTES[timeframe]
        last_time = pd.to_datetime(df.iloc[-1]["time"]).to_pydatetime()
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

        if now >= last_time + timedelta(minutes=minutes):
            last_close = float(df.iloc[-1]["close"])
            step = self.rng.normal(0, 0.02 if symbol != "XAUUSD" else 0.8)
            close = max(0.0001, last_close + step)
            open_ = last_close
            high = max(open_, close) + abs(self.rng.normal(0.015, 0.01))
            low = min(open_, close) - abs(self.rng.normal(0.015, 0.01))
            volume = int(self.rng.integers(100, 1000))
            new_row = pd.DataFrame([{
                "time": now,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            self.buffers[key] = df.tail(max(limit, 500)).reset_index(drop=True)

        return self.buffers[key].tail(limit).reset_index(drop=True)

    async def get_spread(self, symbol: str) -> float:
        base = {"EURUSD": 0.9, "GBPUSD": 1.3, "USDJPY": 1.1, "XAUUSD": 22.0}.get(symbol, 2.0)
        noise = abs(self.rng.normal(0, base * 0.15))
        return float(base + noise)
