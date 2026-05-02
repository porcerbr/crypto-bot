"""Monitoramento de saúde do sistema.

Registra métricas de performance dos ciclos para detectar
degradação antes que vire falha.
"""
import logging
import statistics
from collections import deque
from datetime import datetime, timezone
from typing import Dict

logger = logging.getLogger("HealthMonitor")


class HealthMonitor:
    """Monitor de saúde com histórico de ciclos."""

    def __init__(self, max_history: int = 100):
        self.cycle_times: deque = deque(maxlen=max_history)
        self.errors_count = 0
        self.last_cycle: datetime = datetime.now(timezone.utc)

    def record_cycle(self, duration: float):
        """Registra duração de um ciclo completo."""
        self.cycle_times.append(duration)
        self.last_cycle = datetime.now(timezone.utc)

        if duration > 30:
            logger.warning(f"Ciclo lento detectado: {duration:.2f}s")

    def get_stats(self) -> Dict:
        """Retorna estatísticas de saúde."""
        if not self.cycle_times:
            return {"status": "unknown", "avg_cycle": 0, "max_cycle": 0}

        times = list(self.cycle_times)
        return {
            "status": "healthy" if statistics.mean(times) < 10 else "degraded",
            "avg_cycle": round(statistics.mean(times), 2),
            "max_cycle": round(max(times), 2),
            "min_cycle": round(min(times), 2),
            "cycles_recorded": len(times),
        }
