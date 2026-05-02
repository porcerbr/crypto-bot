"""Gerenciamento de risco e exposição.

Controla limites de capital, número de operações e
exposição agregada do portfólio.
"""
import logging
import threading
from typing import Dict, List

from config import get_settings
from storage.database import TradeDatabase

logger = logging.getLogger("RiskManager")


class RiskManager:
    """Controlador central de risco."""

    def __init__(self):
        self.settings = get_settings()
        self.db = TradeDatabase()
        self._lock = threading.Lock()

    def is_max_exposure_reached(self) -> bool:
        """Verifica se exposição atual ultrapassa limite.

        Em modo simulação, calcula com base no valor total
        das operações abertas vs capital fictício.
        """
        open_trades = self.db.get_open_trades()
        if not open_trades:
            return False

        # Capital fictício base para simulação
        simulated_capital = 10000.0
        total_exposure = sum(t.get("size", 0) * t.get("entry_price", 0) for t in open_trades)
        exposure_pct = (total_exposure / simulated_capital) * 100

        result = exposure_pct >= self.settings.max_exposure
        if result:
            logger.warning(f"Exposição máxima atingida: {exposure_pct:.1f}%")
        return result

    def is_max_trades_reached(self) -> bool:
        """Verifica se atingiu limite de operações abertas."""
        open_count = len(self.db.get_open_trades())
        result = open_count >= self.settings.max_open_trades
        if result:
            logger.warning(f"Máximo de trades abertos: {open_count}/{self.settings.max_open_trades}")
        return result

    def calculate_position_size(self, signal_score: int, entry_price: float) -> float:
        """Calcula tamanho da posição baseado no score e risco.

        Quanto maior o score, maior a posição (dentro do limite).
        """
        max_risk = self.settings.max_risk_per_trade / 100
        simulated_capital = 10000.0

        # Fator de confiança baseado no score (0.5 a 1.0)
        confidence = 0.5 + (signal_score / 200)
        risk_amount = simulated_capital * max_risk * confidence

        # Tamanho da posição (assumindo stop de 1% para simplificar)
        stop_pct = 0.01
        position_size = risk_amount / (entry_price * stop_pct)

        logger.info(f"Position size calculado: {position_size:.4f} (score={signal_score})")
        return position_size
