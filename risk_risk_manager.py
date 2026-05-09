from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from core_models import Signal
from utils_config import settings


@dataclass
class RiskState:
    trades_today: int = 0
    daily_loss: float = 0.0
    loss_streak: int = 0
    date: date = field(default_factory=date.today)


class RiskManager:
    def __init__(self, balance: float | None = None) -> None:
        self.balance = float(balance or settings.account_balance)
        self.state = RiskState()

    def _reset_if_new_day(self) -> None:
        today = date.today()
        if self.state.date != today:
            self.state = RiskState(date=today)

    def can_trade(self, signal: Signal | None = None) -> bool:
        self._reset_if_new_day()
        if self.state.trades_today >= settings.max_daily_trades:
            return False
        if self.state.daily_loss >= settings.max_daily_loss:
            return False
        if self.state.loss_streak >= settings.max_loss_streak:
            return False
        return signal is not None

    def _calculate_position_size(self, risk_amount: float, stop_distance: float, symbol: str) -> float:
        pip_value = 10.0 if symbol != "USDJPY" else 9.0
        size = risk_amount / max(stop_distance * pip_value, 1e-9)
        return max(round(size, 2), 0.01)

    def apply(self, signal: Signal) -> Signal | None:
        self._reset_if_new_day()
        if not self.can_trade(signal):
            return None

        risk_amount = self.balance * settings.risk_per_trade
        stop_distance = abs(signal.entry - signal.stop_loss)
        if stop_distance <= 0:
            return None

        signal.position_size = self._calculate_position_size(
            risk_amount=risk_amount,
            stop_distance=stop_distance,
            symbol=signal.symbol,
        )
        return signal

    def register_result(self, r_multiple: float) -> None:
        self._reset_if_new_day()
        self.state.trades_today += 1
        if r_multiple < 0:
            self.state.loss_streak += 1
            self.state.daily_loss += abs(r_multiple) * settings.risk_per_trade
        else:
            self.state.loss_streak = 0
