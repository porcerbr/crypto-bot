from __future__ import annotations
from models import BotState

def win_rate(state: BotState) -> float:
    total = state.total_wins + state.total_losses + state.total_breakeven
    if total == 0:
        return 0.0
    return state.total_wins / total * 100.0

def profit_factor(state: BotState) -> float:
    gross_win = 0.0
    gross_loss = 0.0
    for t in state.open_trades:
        if t.status != "CLOSED":
            continue
        if t.pnl >= 0:
            gross_win += t.pnl
        else:
            gross_loss += abs(t.pnl)
    if gross_loss == 0:
        return gross_win if gross_win > 0 else 0.0
    return gross_win / gross_loss
