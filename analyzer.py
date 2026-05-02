"""
strategy/analyzer.py — Análise de mercado e scoring
Recebe o DataFrame de preços e retorna um objeto Analysis com:
  - Indicadores calculados
  - Score de 0-100
  - Direção recomendada
  - Regime de mercado
  - Justificativa detalhada
"""

from dataclasses import dataclass, field
from typing import Literal
from datetime import datetime
import pandas as pd
from loguru import logger

from core.config import settings
from strategy import indicators as ind


Direction = Literal["long", "short", "neutral"]
Regime = Literal["trending_up", "trending_down", "ranging", "volatile", "unknown"]


@dataclass
class Analysis:
    timestamp: datetime = field(default_factory=datetime.utcnow)
    symbol: str = ""
    direction: Direction = "neutral"
    score: float = 0.0
    market_regime: Regime = "unknown"
    reasons: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)

    # Indicadores (snapshot)
    rsi: float = 0.0
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    adx: float = 0.0
    atr: float = 0.0
    volume_ratio: float = 0.0
    support: float = 0.0
    resistance: float = 0.0
    close: float = 0.0


class MarketAnalyzer:
    """
    Sistema de análise multi-indicador com pontuação ponderada.

    Pesos dos indicadores:
      RSI          → 20 pts
      MACD         → 25 pts
      EMA crossover → 20 pts
      Bollinger    → 15 pts
      Volume       → 10 pts
      ADX (força)  → 10 pts
    Total: 100 pts — sinal ativado acima de MIN_SIGNAL_SCORE
    """

    def analyze(self, df: pd.DataFrame) -> Analysis:
        analysis = Analysis(symbol=settings.SYMBOL)

        try:
            analysis = self._compute_indicators(df, analysis)
            analysis = self._detect_regime(df, analysis)
            analysis = self._score_and_direction(analysis)
        except Exception as exc:
            logger.error(f"Erro no analyzer: {exc}", exc_info=True)
            analysis.direction = "neutral"
            analysis.score = 0.0

        return analysis

    # ── Indicadores ───────────────────────────────────────────────

    def _compute_indicators(self, df: pd.DataFrame, a: Analysis) -> Analysis:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        rsi_s = ind.rsi(close, settings.RSI_PERIOD)
        macd_l, macd_sig, macd_h = ind.macd(
            close, settings.MACD_FAST, settings.MACD_SLOW, settings.MACD_SIGNAL
        )
        ema_f = ind.ema(close, settings.EMA_FAST)
        ema_sl = ind.ema(close, settings.EMA_SLOW)
        bb_up, bb_mid, bb_lo = ind.bollinger_bands(close, settings.BB_PERIOD, settings.BB_STD)
        adx_s = ind.adx(high, low, close)
        atr_s = ind.atr(high, low, close)
        vol_sma = ind.volume_sma(volume)
        support, resistance = ind.support_resistance(high, low)

        a.close = float(close.iloc[-1])
        a.rsi = float(rsi_s.iloc[-1])
        a.macd_line = float(macd_l.iloc[-1])
        a.macd_signal = float(macd_sig.iloc[-1])
        a.macd_hist = float(macd_h.iloc[-1])
        a.ema_fast = float(ema_f.iloc[-1])
        a.ema_slow = float(ema_sl.iloc[-1])
        a.bb_upper = float(bb_up.iloc[-1])
        a.bb_middle = float(bb_mid.iloc[-1])
        a.bb_lower = float(bb_lo.iloc[-1])
        a.adx = float(adx_s.iloc[-1])
        a.atr = float(atr_s.iloc[-1])
        a.volume_ratio = float(volume.iloc[-1] / vol_sma.iloc[-1]) if float(vol_sma.iloc[-1]) > 0 else 1.0
        a.support = support
        a.resistance = resistance
        return a

    # ── Regime ────────────────────────────────────────────────────

    def _detect_regime(self, df: pd.DataFrame, a: Analysis) -> Analysis:
        bb_width = (a.bb_upper - a.bb_lower) / a.bb_middle if a.bb_middle > 0 else 0
        if a.adx > 25:
            a.market_regime = "trending_up" if a.ema_fast > a.ema_slow else "trending_down"
        elif bb_width > 0.08:
            a.market_regime = "volatile"
        else:
            a.market_regime = "ranging"
        return a

    # ── Scoring ───────────────────────────────────────────────────

    def _score_and_direction(self, a: Analysis) -> Analysis:
        long_score = 0.0
        short_score = 0.0

        # ── RSI (20 pts) ───────────────────────────────────────
        if a.rsi < settings.RSI_OVERSOLD:
            long_score += 20
            a.reasons.append(f"RSI={a.rsi:.1f} em zona de sobrevenda")
        elif a.rsi > settings.RSI_OVERBOUGHT:
            short_score += 20
            a.reasons.append(f"RSI={a.rsi:.1f} em zona de sobrecompra")
        elif 40 <= a.rsi <= 55:
            long_score += 5
            short_score += 5
            a.reasons.append(f"RSI={a.rsi:.1f} neutro")

        # ── MACD (25 pts) ──────────────────────────────────────
        if a.macd_line > a.macd_signal and a.macd_hist > 0:
            long_score += 25
            a.reasons.append(f"MACD bullish (hist={a.macd_hist:.4f})")
        elif a.macd_line < a.macd_signal and a.macd_hist < 0:
            short_score += 25
            a.reasons.append(f"MACD bearish (hist={a.macd_hist:.4f})")
        elif abs(a.macd_hist) < 0.0001:
            long_score += 5
            short_score += 5

        # ── EMA Cross (20 pts) ─────────────────────────────────
        ema_gap_pct = abs(a.ema_fast - a.ema_slow) / a.ema_slow * 100 if a.ema_slow > 0 else 0
        if a.ema_fast > a.ema_slow:
            pts = min(20, 10 + ema_gap_pct * 2)
            long_score += pts
            a.reasons.append(f"EMA fast > slow ({ema_gap_pct:.2f}% gap)")
        elif a.ema_fast < a.ema_slow:
            pts = min(20, 10 + ema_gap_pct * 2)
            short_score += pts
            a.reasons.append(f"EMA fast < slow ({ema_gap_pct:.2f}% gap)")

        # ── Bollinger Bands (15 pts) ───────────────────────────
        bb_pos = (a.close - a.bb_lower) / (a.bb_upper - a.bb_lower) if (a.bb_upper - a.bb_lower) > 0 else 0.5
        if bb_pos < 0.2:
            long_score += 15
            a.reasons.append(f"Preço próximo à banda inferior (BB pos={bb_pos:.2f})")
        elif bb_pos > 0.8:
            short_score += 15
            a.reasons.append(f"Preço próximo à banda superior (BB pos={bb_pos:.2f})")
        else:
            long_score += 5
            short_score += 5

        # ── Volume (10 pts) ────────────────────────────────────
        if a.volume_ratio >= 1.5:
            if long_score > short_score:
                long_score += 10
            else:
                short_score += 10
            a.reasons.append(f"Volume acima da média ({a.volume_ratio:.1f}x)")
        elif a.volume_ratio >= settings.MIN_VOLUME_FACTOR:
            long_score += 5
            short_score += 5

        # ── ADX (10 pts) ───────────────────────────────────────
        if a.adx > 25:
            if long_score > short_score:
                long_score += 10
            else:
                short_score += 10
            a.reasons.append(f"Tendência forte (ADX={a.adx:.1f})")
        elif a.adx > 20:
            long_score += 5
            short_score += 5

        # ── Decisão ───────────────────────────────────────────
        if long_score > short_score:
            a.direction = "long"
            a.score = min(long_score, 100.0)
        elif short_score > long_score:
            a.direction = "short"
            a.score = min(short_score, 100.0)
        else:
            a.direction = "neutral"
            a.score = 0.0

        logger.debug(
            f"Scoring → Long: {long_score:.1f} | Short: {short_score:.1f} "
            f"→ {a.direction.upper()} @ {a.score:.1f}"
        )
        return a
