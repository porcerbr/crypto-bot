"""
storage/state.py — Gerenciamento de estado persistente
Salva e restaura o estado completo do bot entre reinicializações.
Usa JSON para portabilidade e facilidade de inspeção manual.
"""

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from loguru import logger

from core.config import settings
from execution.handler import Signal, SignalHandler


class StateManager:
    """
    Estado em memória com persistência em JSON.
    Responsável por:
      - Trades abertos
      - Capital atual
      - Contadores diários
      - Drawdown tracking
    """

    def __init__(self):
        self._open_trades: list[Signal] = []
        self._capital = settings.INITIAL_CAPITAL
        self._peak_capital = settings.INITIAL_CAPITAL
        self._daily_counts: dict[str, int] = {}
        self._signal_handler = SignalHandler()
        self._path = Path(settings.STATE_FILE)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Persistência ──────────────────────────────────────────────

    def save(self):
        try:
            data = {
                "saved_at": datetime.utcnow().isoformat(),
                "capital": self._capital,
                "peak_capital": self._peak_capital,
                "daily_counts": self._daily_counts,
                "open_trades": [t.__dict__ for t in self._open_trades],
            }
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug(f"Estado salvo em {self._path}")
        except Exception as exc:
            logger.error(f"Falha ao salvar estado: {exc}")

    def load(self):
        if not self._path.exists():
            logger.info("Nenhum estado anterior encontrado — iniciando do zero")
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._capital = float(data.get("capital", settings.INITIAL_CAPITAL))
            self._peak_capital = float(data.get("peak_capital", self._capital))
            self._daily_counts = data.get("daily_counts", {})

            self._open_trades = []
            for td in data.get("open_trades", []):
                s = Signal(**{k: v for k, v in td.items() if k in Signal.__dataclass_fields__})
                if s.status == "open":
                    self._open_trades.append(s)

            logger.info(
                f"Estado restaurado: capital={self._capital:.2f} | "
                f"trades abertos={len(self._open_trades)}"
            )
        except Exception as exc:
            logger.error(f"Falha ao carregar estado: {exc} — iniciando limpo")

    # ── Trades ───────────────────────────────────────────────────

    def add_open_trade(self, signal: Signal):
        self._open_trades.append(signal)
        today = str(date.today())
        self._daily_counts[today] = self._daily_counts.get(today, 0) + 1
        logger.debug(f"Trade {signal.id} adicionado — total abertos: {len(self._open_trades)}")

    def update_open_trades(self, current_price: float):
        """Verifica SL/TP para cada trade aberto e atualiza capital."""
        closed = []
        for trade in self._open_trades:
            updated = self._signal_handler.update_signal(trade, current_price)
            if updated.status in ("hit_tp", "hit_sl"):
                pnl = self._capital * (updated.pnl_pct / 100) * (settings.RISK_PER_TRADE_PCT / 100)
                self._capital += pnl
                self._peak_capital = max(self._peak_capital, self._capital)
                closed.append(updated)
                logger.info(
                    f"Trade {updated.id} fechado ({updated.status}) | "
                    f"PnL: {updated.pnl_pct:+.2f}% | Capital: {self._capital:.2f}"
                )
        self._open_trades = [t for t in self._open_trades if t.status == "open"]

    def get_open_trades(self) -> list[Signal]:
        return list(self._open_trades)

    def get_daily_trade_count(self, day: date) -> int:
        return self._daily_counts.get(str(day), 0)

    def get_current_drawdown_pct(self) -> float:
        if self._peak_capital <= 0:
            return 0.0
        return ((self._peak_capital - self._capital) / self._peak_capital) * 100

    @property
    def capital(self) -> float:
        return self._capital

    @property
    def peak_capital(self) -> float:
        return self._peak_capital
