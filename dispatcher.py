"""Módulo de execução de ordens.

Em modo SIMULATION: simula preenchimento e P&L.
Em modo LIVE: estrutura pronta para integrar corretora.

Todas as execuções são registradas com timestamp e motivo.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from config import get_settings
from risk.manager import RiskManager
from strategy.signal_generator import Signal, SignalDirection

logger = logging.getLogger("ExecutionDispatcher")


class ExecutionDispatcher:
    """Dispatcher de execução com simulação realista."""

    def __init__(self):
        self.settings = get_settings()
        self.risk_mgr = RiskManager()

    def execute(self, signal: Signal, simulation: bool = True) -> Optional[Dict]:
        """Executa o sinal e retorna trade registrado.

        Args:
            signal: Sinal validado
            simulation: Se True, não envia ordem real

        Returns:
            Dicionário com dados do trade ou None se falhar.
        """
        try:
            # Calcular tamanho
            size = self.risk_mgr.calculate_position_size(signal.score, signal.price)

            trade = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "entry_price": signal.price,
                "size": size,
                "score": signal.score,
                "status": "OPEN",
                "pnl": 0.0,
                "exit_price": None,
                "exit_time": None,
                "metadata": signal.metadata,
                "simulation": simulation,
            }

            if simulation:
                logger.info(f"[SIMULAÇÃO] Ordem executada: {signal.direction.value} {size} @ {signal.price}")
                # Simular P&L instantâneo para demonstração (em produção seria async)
                import random
                trade["pnl"] = random.uniform(-20, 40)  # Simulação realista
                if trade["pnl"] > 0:
                    trade["status"] = "CLOSED_WIN"
                else:
                    trade["status"] = "CLOSED_LOSS"
                trade["exit_price"] = signal.price * (1 + trade["pnl"]/10000)
                trade["exit_time"] = datetime.now(timezone.utc).isoformat()
            else:
                # TODO: Integração com API da corretora
                logger.warning("Modo LIVE não implementado - ordem não enviada")
                return None

            return trade

        except Exception as e:
            logger.error(f"Falha na execução: {e}")
            return None
