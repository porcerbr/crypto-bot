from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core_models import SignalSide


class MarketFilters:
    def __init__(self, news_path: str = "data_news_high_impact.json") -> None:
        self.news_path = Path(news_path)

    def spread_ok(self, spread_pips: float, symbol: str) -> bool:
        limits = {"EURUSD": 1.8, "GBPUSD": 2.4, "USDJPY": 2.0, "XAUUSD": 30.0}
        return spread_pips <= limits.get(symbol, 3.0)

    def volatility_ok(self, df: pd.DataFrame) -> bool:
        return float(df["volatility"].iloc[-1]) > 0.00015

    def trend_ok(self, df: pd.DataFrame, side: SignalSide) -> bool:
        last = df.iloc[-1]
        if side == SignalSide.BUY:
            return last["ema_20"] >= last["ema_50"] >= last["ema_200"]
        return last["ema_20"] <= last["ema_50"] <= last["ema_200"]

    def consolidation_ok(self, df: pd.DataFrame) -> bool:
        last = df.iloc[-1]
        atr = float(last["atr_14"])
        width = float(last["bb_width"])
        return not (atr < df["atr_14"].rolling(20, min_periods=5).median().iloc[-1] * 0.7 and width < 0.01)

    def session_ok(self) -> bool:
        hour = datetime.now(timezone.utc).hour
        return 6 <= hour <= 20

    def news_ok(self, symbol: str) -> bool:
        if not self.news_path.exists():
            return True
        try:
            payload = pd.read_json(self.news_path)
            now = datetime.now(timezone.utc)
            for _, row in payload.iterrows():
                if str(row.get("symbol", "")).upper() not in ("", symbol.upper()):
                    continue
                impact = str(row.get("impact", "")).lower()
                if impact != "high":
                    continue
                ts = pd.to_datetime(row.get("time"), utc=True)
                if abs((now - ts).total_seconds()) <= 60 * 60:
                    return False
        except Exception:
            return True
        return True
