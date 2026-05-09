from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core_models import Signal, SignalSide
from filters_market_filters import MarketFilters
from utils_config import settings


@dataclass(slots=True)
class StrategyConfig:
    min_score: float = settings.min_signal_score
    min_rr: float = settings.min_rr
    atr_sl_mult: float = 1.4
    atr_tp_mult: float = 2.8
    min_adx: float = 18.0
    min_confidence: float = 0.60


class ConfluenceStrategy:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()
        self.filters = MarketFilters()

    def _confirmation(self, prev: pd.Series, current: pd.Series, side: SignalSide) -> bool:
        body_prev = abs(float(prev["close"]) - float(prev["open"]))
        body_cur = abs(float(current["close"]) - float(current["open"]))
        if side == SignalSide.BUY:
            return current["close"] > current["open"] and current["close"] > prev["high"] and body_cur >= body_prev * 0.6
        return current["close"] < current["open"] and current["close"] < prev["low"] and body_cur >= body_prev * 0.6

    def generate_signal(self, symbol: str, m5: pd.DataFrame, m15: pd.DataFrame, h1: pd.DataFrame) -> Signal | None:
        if len(m5) < 210 or len(m15) < 210 or len(h1) < 210:
            return None

        for df in (m5, m15, h1):
            if any(col not in df.columns for col in ["ema_20", "ema_50", "ema_200", "rsi_14", "macd_hist", "atr_14"]):
                return None

        last = m5.iloc[-1]
        prev = m5.iloc[-2]
        side = SignalSide.BUY if last["ema_20"] > last["ema_50"] and last["macd_hist"] >= 0 else SignalSide.SELL

        score = 0.0
        reasons: list[str] = []

        # Trend
        if side == SignalSide.BUY:
            if h1.iloc[-1]["ema_20"] > h1.iloc[-1]["ema_50"] > h1.iloc[-1]["ema_200"]:
                score += 20; reasons.append("Tendência H1 compradora")
            if m15.iloc[-1]["ema_20"] > m15.iloc[-1]["ema_50"]:
                score += 10; reasons.append("M15 alinhado")
        else:
            if h1.iloc[-1]["ema_20"] < h1.iloc[-1]["ema_50"] < h1.iloc[-1]["ema_200"]:
                score += 20; reasons.append("Tendência H1 vendedora")
            if m15.iloc[-1]["ema_20"] < m15.iloc[-1]["ema_50"]:
                score += 10; reasons.append("M15 alinhado")

        # Momentum
        rsi_value = float(last["rsi_14"])
        if side == SignalSide.BUY and rsi_value >= 52:
            score += 10; reasons.append("RSI favorável")
        if side == SignalSide.SELL and rsi_value <= 48:
            score += 10; reasons.append("RSI favorável")

        # MACD / ADX / ATR
        if (side == SignalSide.BUY and last["macd_hist"] > 0) or (side == SignalSide.SELL and last["macd_hist"] < 0):
            score += 10; reasons.append("MACD alinhado")

        if float(last["adx_14"]) >= self.config.min_adx:
            score += 10; reasons.append("ADX forte")

        atr_value = float(last["atr_14"])
        if atr_value > float(m5["atr_14"].rolling(20, min_periods=5).median().iloc[-1]) * 0.9:
            score += 10; reasons.append("Volatilidade suficiente")

        # Candle confirmation
        if self._confirmation(prev, last, side):
            score += 10; reasons.append("Confirmação de candle")

        if self.filters.consolidation_ok(m5):
            score += 10; reasons.append("Sem consolidação forte")

        confidence = min(score / 100.0, 0.99)
        probability = min(0.50 + confidence * 0.45, 0.95)

        entry = float(last["close"])
        if side == SignalSide.BUY:
            stop_loss = entry - atr_value * self.config.atr_sl_mult
            take_profit = entry + atr_value * self.config.atr_tp_mult
        else:
            stop_loss = entry + atr_value * self.config.atr_sl_mult
            take_profit = entry - atr_value * self.config.atr_tp_mult

        rr = abs(take_profit - entry) / max(abs(entry - stop_loss), 1e-9)

        if score < self.config.min_score or rr < self.config.min_rr:
            return None

        return Signal(
            symbol=symbol,
            side=side,
            timeframe="M5",
            entry=entry,
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            rr=float(rr),
            score=float(score),
            confidence=float(confidence),
            probability=float(probability),
            reason=" | ".join(reasons) if reasons else "Sem confluência suficiente",
            created_at=datetime.now(timezone.utc),
        )
