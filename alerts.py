"""Sistema de alertas simples.

Pode ser expandido para enviar webhooks, email, Telegram, etc.
Por enquanto, integra com o estado do engine para exibição
no dashboard.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger("AlertManager")


class AlertManager:
    """Gerenciador de alertas do sistema."""

    def __init__(self):
        self.alert_history = []

    def send(self, level: str, message: str):
        """Registra um alerta.

        Args:
            level: info, warning, error, critical
            message: conteúdo do alerta
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {"time": timestamp, "level": level, "message": message}
        self.alert_history.append(entry)

        # Também loga
        log_func = getattr(logger, level, logger.info)
        log_func(f"[ALERT] {message}")

        # Limitar histórico
        if len(self.alert_history) > 1000:
            self.alert_history.pop(0)

    def get_recent(self, limit: int = 50):
        """Retorna alertas recentes."""
        return self.alert_history[-limit:]
