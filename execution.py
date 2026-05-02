from __future__ import annotations
import time
from typing import Optional, Tuple
from models import Signal, TradeState, Side, utc_now, to_iso
from utils import pip_size

class ExecutionEngine:
    def open_trade(self, signal: Signal, volume: float) -> TradeState:
        trade_id = f"{signal.symbol.replace('/', '')}-{int(time.time())}"
        return TradeState(
            trade_id=trade_id,
            symbol=signal.symbol,
            side=signal.side,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            volume=volume,
            opened_at=to_iso(utc_now()),
        )

    def simulate_update(self, trade: TradeState, last_price: float) -> Optional[Tuple[str, float]]:
        if trade.status != "OPEN":
            return None
        if trade.side == Side.BUY:
            if last_price <= trade.stop_loss:
                return ("LOSS", trade.stop_loss)
            if last_price >= trade.take_profit:
                return ("WIN", trade.take_profit)
        elif trade.side == Side.SELL:
            if last_price >= trade.stop_loss:
                return ("LOSS", trade.stop_loss)
            if last_price <= trade.take_profit:
                return ("WIN", trade.take_profit)
        return None

def calculate_pnl(trade: TradeState, close_price: float) -> float:
    pip = pip_size(trade.symbol)
    pnl_points = (close_price - trade.entry) if trade.side == Side.BUY else (trade.entry - close_price)
    return pnl_points / pip * trade.volume * 1.0
