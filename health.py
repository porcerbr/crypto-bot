"""
monitoring/health.py — Monitor de saúde do sistema
Rastreia erros, latências, disponibilidade de dados e métricas operacionais.
"""

from collections import deque
from datetime import datetime
from loguru import logger


class HealthMonitor:
    def __init__(self, engine):
        self._engine = engine
        self._errors: deque = deque(maxlen=50)
        self._data_misses = 0
        self._cycle_times: deque = deque(maxlen=100)
        self._last_price_update = None
        self._last_signal_time = None

    def record_error(self, message: str):
        self._errors.appendleft({
            "timestamp": datetime.utcnow().isoformat(),
            "message": message,
        })

    def record_data_miss(self):
        self._data_misses += 1

    def record_cycle(self, analysis, price: float):
        self._last_price_update = datetime.utcnow()
        if hasattr(self._engine, "_last_cycle_time") and self._engine._last_cycle_time:
            self._cycle_times.append(self._engine._last_cycle_time)

    def get_recent_errors(self, limit: int = 10) -> list:
        return list(self._errors)[:limit]

    def get_summary(self) -> dict:
        avg_cycle = (
            sum(self._cycle_times) / len(self._cycle_times)
            if self._cycle_times else 0
        )
        return {
            "total_errors": len(self._errors),
            "data_misses": self._data_misses,
            "avg_cycle_seconds": round(avg_cycle, 2),
            "last_price_update": (
                self._last_price_update.isoformat() if self._last_price_update else None
            ),
        }
