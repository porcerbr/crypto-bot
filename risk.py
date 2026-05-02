from __future__ import annotations
from typing import Tuple
from datetime import timedelta

from config import BotConfig
from models import BotState
from models import from_iso, utc_now

class RiskManager:
    def __init__(self, config: BotConfig):
        self.config = config

    def daily_drawdown_pct(self, state: BotState) -> float:
        if state.day_start_equity <= 0:
            return 0.0
        return max(0.0, (state.day_start_equity - state.equity) / state.day_start_equity * 100.0)

    def can_open_trade(self, state: BotState) -> Tuple[bool, str]:
        if len([t for t in state.open_trades if t.status == "OPEN"]) >= self.config.max_open_trades:
            return False, "máximo de trades ativos atingido"

        if self.daily_drawdown_pct(state) >= self.config.max_daily_loss_pct:
            return False, "limite diário de perda atingido"

        if state.last_loss_at_utc:
            last_loss = from_iso(state.last_loss_at_utc)
            if utc_now() - last_loss < timedelta(minutes=self.config.cooldown_minutes_after_loss):
                return False, "cooldown após loss ativo"

        return True, "ok"

    def position_size(self, symbol: str, entry: float, stop_loss: float, balance: float) -> float:
        risk_amount = balance * (self.config.risk_per_trade_pct / 100.0)
        stop_distance = abs(entry - stop_loss)
        if stop_distance <= 0:
            return 0.0
        lot_value_proxy = 100000.0 if "XAU" not in symbol else 100.0
        lots = risk_amount / (stop_distance * lot_value_proxy)
        return max(0.0, round(lots, 2))
