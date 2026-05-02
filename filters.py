"""Filtros de risco pré-operacional.

Verificam condições de mercado e do sistema antes de
permitir a geração de sinais. Cada filtro é independente
e pode ser desabilitado futuramente via configuração.
"""
import logging
from datetime import datetime, timezone

import pandas as pd

from config import get_settings

logger = logging.getLogger("RiskFilter")


class RiskFilter:
    """Conjunto de filtros de segurança."""

    def __init__(self):
        self.settings = get_settings()

    def is_trading_hours(self) -> bool:
        """Verifica se está dentro do horário de operação configurado."""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        result = self.settings.trade_start_hour <= current_hour < self.settings.trade_end_hour
        if not result:
            logger.debug(f"Fora do horário de operação: {current_hour}h")
        return result

    def volatility_ok(self, df: pd.DataFrame, max_pct: float) -> bool:
        """Verifica se a volatilidade recente está dentro do limite.

        Usa desvio padrão dos retornos dos últimos 20 períodos.
        """
        if len(df) < 20:
            return False
        returns = df["close"].pct_change().dropna()
        vol = returns.tail(20).std() * 100  # percentual aproximado
        result = vol <= max_pct
        if not result:
            logger.warning(f"Volatilidade alta: {vol:.2f}% (limite: {max_pct}%)")
        return result

    def volume_ok(self, df: pd.DataFrame, min_ratio: float) -> bool:
        """Verifica se o volume está acima da média móvel."""
        if "volume" not in df.columns or len(df) < 20:
            return True  # Se não tem volume, não bloqueia por isso

        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        last_vol = df["volume"].iloc[-1]

        if avg_vol == 0:
            return True

        ratio = last_vol / avg_vol
        result = ratio >= min_ratio
        if not result:
            logger.debug(f"Volume baixo: ratio={ratio:.2f} (mínimo: {min_ratio})")
        return result
