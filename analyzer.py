"""Análise técnica de mercado.

Calcula indicadores clássicos (RSI, Médias Móveis, Bollinger, ATR)
para fornecer contexto ao gerador de sinais.
"""
import logging
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("MarketAnalyzer")


@dataclass
class MarketContext:
    """Contexto de mercado calculado a partir dos dados."""
    trend: str = "neutral"  # up, down, neutral
    volatility: float = 0.0
    rsi: float = 50.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    bb_position: float = 0.5  # 0=inferior, 0.5=média, 1=superior
    volume_ratio: float = 1.0
    atr: float = 0.0
    support: float = 0.0
    resistance: float = 0.0


class MarketAnalyzer:
    """Analisador técnico com múltiplos indicadores."""

    def analyze(self, df: pd.DataFrame) -> MarketContext:
        """Calcula todos os indicadores e retorna contexto."""
        ctx = MarketContext()

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df.get("volume", pd.Series([0] * len(df)))

        # Tendência via EMAs
        ctx.ema_fast = self._ema(close, 9)
        ctx.ema_slow = self._ema(close, 21)

        if ctx.ema_fast > ctx.ema_slow * 1.001:
            ctx.trend = "up"
        elif ctx.ema_fast < ctx.ema_slow * 0.999:
            ctx.trend = "down"
        else:
            ctx.trend = "neutral"

        # RSI
        ctx.rsi = self._rsi(close, 14)

        # Bollinger Bands position
        ctx.bb_position = self._bb_position(close, 20)

        # Volatilidade (ATR percentual)
        ctx.atr = self._atr(high, low, close, 14)
        ctx.volatility = (ctx.atr / close.iloc[-1]) * 100 if close.iloc[-1] != 0 else 0

        # Volume ratio vs média
        avg_vol = volume.rolling(20).mean().iloc[-1]
        last_vol = volume.iloc[-1]
        ctx.volume_ratio = (last_vol / avg_vol) if avg_vol > 0 else 1.0

        # Suporte/Resistência simples (mínimos/máximos recentes)
        ctx.support = low.rolling(20).min().iloc[-1]
        ctx.resistance = high.rolling(20).max().iloc[-1]

        logger.debug(f"Contexto: trend={ctx.trend}, rsi={ctx.rsi:.1f}, vol={ctx.volatility:.2f}%")
        return ctx

    @staticmethod
    def _ema(series: pd.Series, period: int) -> float:
        return series.ewm(span=period, adjust=False).mean().iloc[-1]

    @staticmethod
    def _rsi(series: pd.Series, period: int) -> float:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta.where(delta < 0, 0.0))
        avg_gain = gain.rolling(window=period, min_periods=1).mean()
        avg_loss = loss.rolling(window=period, min_periods=1).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - (100 / (1 + rs)).iloc[-1]

    @staticmethod
    def _bb_position(series: pd.Series, period: int) -> float:
        ma = series.rolling(period).mean().iloc[-1]
        std = series.rolling(period).std().iloc[-1]
        last = series.iloc[-1]
        upper = ma + 2 * std
        lower = ma - 2 * std
        if upper == lower:
            return 0.5
        return max(0.0, min(1.0, (last - lower) / (upper - lower)))

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> float:
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period, min_periods=1).mean().iloc[-1]
