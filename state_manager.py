"""Gerenciador de estado runtime.

Salva estado volátil em JSON para recuperação em caso
de reinício inesperado do processo.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

from config import get_settings

logger = logging.getLogger("StateManager")


class StateManager:
    """Persistência leve de estado em JSON."""

    def __init__(self):
        self.settings = get_settings()
        self.state_path = Path("data_storage/runtime_state.json")

    def save(self, state: Dict[str, Any]):
        """Salva estado atual em disco."""
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")

    def load(self) -> Dict[str, Any]:
        """Carrega estado do disco."""
        if not self.state_path.exists():
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar estado: {e}")
            return {}
