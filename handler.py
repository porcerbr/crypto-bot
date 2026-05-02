"""
execution/handler.py — Criação e gerenciamento de sinais
Em modo simulado: registra sinal sem enviar ordens reais.
Em modo live: conecta com broker via API.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from loguru import logger

from core.config import settings


@dataclass
class Signal:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    score: float = 0.0
    risk_reward: float = 0.0
    reasons: list = field(default_factory=list)
    status: str = "open"           # open | hit_tp | hit_sl | closed
    pnl_pct: float = 0.0
    market_regime: str = ""
    timeframe: str = ""


class SignalHandler:
    """
    Cria objetos Signal com SL/TP calculados automaticamente.
    Em produção, aqui ficaria a integração com o broker.
    """

    def create_signal(self, analysis, current_price: float) -> Signal:
        sl_mult = 1 - settings.STOP_LOSS_PCT / 100
        tp_mult = 1 + settings.TAKE_PROFIT_PCT / 100

        if analysis.direction == "long":
            stop_loss = current_price * sl_mult
            take_profit = current_price * tp_mult
        else:  # short
            stop_loss = current_price * (1 + settings.STOP_LOSS_PCT / 100)
            take_profit = current_price * (1 - settings.TAKE_PROFIT_PCT / 100)

        risk = abs(current_price - stop_loss)
        reward = abs(take_profit - current_price)
        rr = reward / risk if risk > 0 else 0

        signal = Signal(
            symbol=settings.SYMBOL,
            direction=analysis.direction,
            entry_price=round(current_price, 2),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            score=round(analysis.score, 2),
            risk_reward=round(rr, 2),
            reasons=analysis.reasons,
            market_regime=analysis.market_regime,
            timeframe=settings.TIMEFRAME,
        )

        logger.info(
            f"Signal criado: {signal.id} | {signal.direction.upper()} "
            f"@ {signal.entry_price:.2f} | SL={signal.stop_loss:.2f} "
            f"| TP={signal.take_profit:.2f} | R:R={signal.risk_reward:.2f}"
        )
        return signal

    def update_signal(self, signal: Signal, current_price: float) -> Signal:
        """Verifica se SL ou TP foi atingido."""
        if signal.status != "open":
            return signal

        if signal.direction == "long":
            if current_price >= signal.take_profit:
                signal.status = "hit_tp"
                signal.pnl_pct = round(settings.TAKE_PROFIT_PCT, 2)
                logger.success(f"🎯 TP atingido: {signal.id} +{signal.pnl_pct:.2f}%")
            elif current_price <= signal.stop_loss:
                signal.status = "hit_sl"
                signal.pnl_pct = round(-settings.STOP_LOSS_PCT, 2)
                logger.warning(f"🛑 SL atingido: {signal.id} {signal.pnl_pct:.2f}%")
        else:
            if current_price <= signal.take_profit:
                signal.status = "hit_tp"
                signal.pnl_pct = round(settings.TAKE_PROFIT_PCT, 2)
                logger.success(f"🎯 TP atingido: {signal.id} +{signal.pnl_pct:.2f}%")
            elif current_price >= signal.stop_loss:
                signal.status = "hit_sl"
                signal.pnl_pct = round(-settings.STOP_LOSS_PCT, 2)
                logger.warning(f"🛑 SL atingido: {signal.id} {signal.pnl_pct:.2f}%")

        return signal
