"""Geração de sinais de trading.

Combina múltiplos fatores técnicos em um score ponderado.
Só emite sinal se o score ultrapassar o limiar configurado.
Cada decisão é registrada com justificativa completa.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from strategy.analyzer import MarketContext

logger = logging.getLogger("SignalGenerator")


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"


@dataclass
class Signal:
    """Sinal de trading gerado pelo sistema."""
    timestamp: datetime
    direction: SignalDirection
    score: int  # 0-100
    price: float
    symbol: str
    reason: str
    metadata: dict


class SignalGenerator:
    """Gerador de sinais baseado em score multi-fator."""

    def generate(self, df, context: MarketContext) -> Optional[Signal]:
        """Avalia condições de mercado e gera sinal se apropriado.

        Fatores ponderados:
        - Tendência (30%)
        - RSI (25%)
        - Bollinger Position (20%)
        - Volume (15%)
        - Volatilidade/ATR (10%)
        """
        close = df["close"].iloc[-1]
        symbol = "ASSET"  # Simplificado

        scores = []
        reasons = []

        # 1. Tendência (30 pts)
        trend_score = 0
        if context.trend == "up":
            trend_score = 30
            reasons.append("tendencia_alta")
        elif context.trend == "down":
            trend_score = 30
            reasons.append("tendencia_baixa")
        else:
            trend_score = 10
            reasons.append("tendencia_neutra")
        scores.append(trend_score)

        # 2. RSI (25 pts) - comprado/sobrevendido
        rsi_score = 0
        if context.rsi < 30:
            rsi_score = 25  # Sobrevendido = potencial compra
            reasons.append("rsi_sobrevendido")
        elif context.rsi > 70:
            rsi_score = 25  # Sobrecomprado = potencial venda
            reasons.append("rsi_sobrecomprado")
        else:
            rsi_score = 15
            reasons.append("rsi_neutro")
        scores.append(rsi_score)

        # 3. Bollinger (20 pts)
        bb_score = 0
        if context.bb_position < 0.2:
            bb_score = 20
            reasons.append("bb_faixa_baixa")
        elif context.bb_position > 0.8:
            bb_score = 20
            reasons.append("bb_faixa_alta")
        else:
            bb_score = 10
            reasons.append("bb_meio")
        scores.append(bb_score)

        # 4. Volume (15 pts)
        vol_score = 0
        if context.volume_ratio > 1.5:
            vol_score = 15
            reasons.append("volume_alto")
        elif context.volume_ratio > 1.0:
            vol_score = 10
            reasons.append("volume_normal")
        else:
            vol_score = 5
            reasons.append("volume_baixo")
        scores.append(vol_score)

        # 5. Volatilidade (10 pts) - volatilidade moderada é boa
        volat_score = 0
        if 1.0 <= context.volatility <= 5.0:
            volat_score = 10
            reasons.append("volatilidade_ok")
        else:
            volat_score = 5
            reasons.append("volatilidade_extrema")
        scores.append(volat_score)

        total_score = sum(scores)

        # Determinar direção
        direction = SignalDirection.HOLD
        if context.trend == "up" and context.rsi < 60 and context.bb_position < 0.5:
            direction = SignalDirection.LONG
        elif context.trend == "down" and context.rsi > 40 and context.bb_position > 0.5:
            direction = SignalDirection.SHORT

        # Se direção é HOLD, score é reduzido
        if direction == SignalDirection.HOLD:
            total_score = int(total_score * 0.6)

        # Log da decisão
        logger.info(f"Análise: score={total_score}, dir={direction.value}, rsi={context.rsi:.1f}")

        if total_score < 50:
            return None

        signal = Signal(
            timestamp=datetime.now(timezone.utc),
            direction=direction,
            score=total_score,
            price=close,
            symbol=symbol,
            reason=" | ".join(reasons),
            metadata={
                "rsi": round(context.rsi, 2),
                "ema_fast": round(context.ema_fast, 2),
                "ema_slow": round(context.ema_slow, 2),
                "volatility": round(context.volatility, 2),
                "volume_ratio": round(context.volume_ratio, 2),
            }
        )

        logger.info(f"SINAL GERADO: {direction.value} @ {close:.2f} (score: {total_score})")
        return signal
