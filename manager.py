"""
risk/manager.py — Gerenciamento de risco e filtros de segurança
Nunca opera sem aprovação explícita do risk manager.
Cada decisão é justificada e registrada.
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional
from loguru import logger

from core.config import settings


@dataclass
class RiskResult:
    approved: bool
    reason: str
    score_penalty: float = 0.0


class RiskManager:
    """
    Camada de proteção multi-nível. Avalia uma análise contra todas as
    regras de risco ativas. Bloqueia qualquer entrada insegura.

    Regras (em ordem de prioridade):
      1. Máximo de trades abertos simultâneos
      2. Máximo de trades diários
      3. Drawdown máximo atingido
      4. Volume insuficiente
      5. Regime de mercado inadequado
      6. Spread/volatilidade excessiva
      7. ADX muito baixo (mercado sem direção)
    """

    def __init__(self):
        self._active_filters: list[str] = []

    def evaluate(self, analysis, state) -> RiskResult:
        self._active_filters = []

        checks = [
            self._check_open_trades(state),
            self._check_daily_limit(state),
            self._check_drawdown(state),
            self._check_volume(analysis),
            self._check_market_regime(analysis),
            self._check_adx(analysis),
            self._check_score_minimum(analysis),
        ]

        for result in checks:
            if not result.approved:
                logger.warning(f"Risk block: {result.reason}")
                return result

        logger.debug("Risk manager: todos os filtros aprovados")
        return RiskResult(approved=True, reason="all_clear")

    def _check_open_trades(self, state) -> RiskResult:
        open_count = len(state.get_open_trades())
        if open_count >= settings.MAX_OPEN_TRADES:
            self._active_filters.append("max_open_trades")
            return RiskResult(
                approved=False,
                reason=f"Máximo de trades abertos atingido ({open_count}/{settings.MAX_OPEN_TRADES})",
            )
        return RiskResult(approved=True, reason="ok")

    def _check_daily_limit(self, state) -> RiskResult:
        today_count = state.get_daily_trade_count(date.today())
        if today_count >= settings.MAX_DAILY_TRADES:
            self._active_filters.append("daily_limit")
            return RiskResult(
                approved=False,
                reason=f"Limite diário atingido ({today_count}/{settings.MAX_DAILY_TRADES})",
            )
        return RiskResult(approved=True, reason="ok")

    def _check_drawdown(self, state) -> RiskResult:
        drawdown = state.get_current_drawdown_pct()
        if drawdown >= settings.MAX_DRAWDOWN_PCT:
            self._active_filters.append("max_drawdown")
            return RiskResult(
                approved=False,
                reason=f"Drawdown máximo atingido ({drawdown:.2f}% >= {settings.MAX_DRAWDOWN_PCT}%)",
            )
        return RiskResult(approved=True, reason="ok")

    def _check_volume(self, analysis) -> RiskResult:
        if analysis.volume_ratio < settings.MIN_VOLUME_FACTOR:
            self._active_filters.append("low_volume")
            return RiskResult(
                approved=False,
                reason=f"Volume insuficiente ({analysis.volume_ratio:.2f}x < {settings.MIN_VOLUME_FACTOR}x)",
            )
        return RiskResult(approved=True, reason="ok")

    def _check_market_regime(self, analysis) -> RiskResult:
        if analysis.market_regime == "volatile":
            self._active_filters.append("volatile_market")
            return RiskResult(
                approved=False,
                reason=f"Mercado muito volátil — regime: {analysis.market_regime}",
            )
        return RiskResult(approved=True, reason="ok")

    def _check_adx(self, analysis) -> RiskResult:
        if analysis.adx < 15:
            self._active_filters.append("weak_trend")
            return RiskResult(
                approved=False,
                reason=f"ADX muito baixo ({analysis.adx:.1f}) — sem direção clara",
            )
        return RiskResult(approved=True, reason="ok")

    def _check_score_minimum(self, analysis) -> RiskResult:
        if analysis.score < settings.MIN_SIGNAL_SCORE:
            return RiskResult(
                approved=False,
                reason=f"Score {analysis.score:.1f} abaixo do mínimo {settings.MIN_SIGNAL_SCORE}",
            )
        return RiskResult(approved=True, reason="ok")

    def get_active_filters(self) -> list[str]:
        return list(self._active_filters)
