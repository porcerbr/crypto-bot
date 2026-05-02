from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any

from models import Candle, Side
from strategy import SignalEngine
from config import BotConfig
from execution import calculate_pnl
from utils import pip_size

@dataclass
class BacktestTrade:
    side: Side
    entry: float
    stop_loss: float
    take_profit: float
    result: str = "OPEN"
    pnl: float = 0.0

class Backtester:
    def __init__(self, config: BotConfig):
        self.config = config
        self.strategy = SignalEngine(config)

    def run(self, symbol: str, candles: List[Candle]) -> Dict[str, Any]:
        trades: List[BacktestTrade] = []
        wins = losses = 0
        i = 60
        while i < len(candles):
            window = candles[: i + 1]
            signal = self.strategy.evaluate(symbol, window)
            if signal:
                future = candles[i + 1 :]
                trade = BacktestTrade(signal.side, signal.entry, signal.stop_loss, signal.take_profit)
                for c in future:
                    if trade.side == Side.BUY:
                        if c.low <= trade.stop_loss:
                            trade.result = "LOSS"
                            trade.pnl = calculate_pnl(
                                type("T", (), {"symbol": symbol, "side": trade.side, "entry": trade.entry, "volume": 1.0}),
                                trade.stop_loss,
                            )
                            losses += 1
                            break
                        if c.high >= trade.take_profit:
                            trade.result = "WIN"
                            trade.pnl = calculate_pnl(
                                type("T", (), {"symbol": symbol, "side": trade.side, "entry": trade.entry, "volume": 1.0}),
                                trade.take_profit,
                            )
                            wins += 1
                            break
                    else:
                        if c.high >= trade.stop_loss:
                            trade.result = "LOSS"
                            trade.pnl = calculate_pnl(
                                type("T", (), {"symbol": symbol, "side": trade.side, "entry": trade.entry, "volume": 1.0}),
                                trade.stop_loss,
                            )
                            losses += 1
                            break
                        if c.low <= trade.take_profit:
                            trade.result = "WIN"
                            trade.pnl = calculate_pnl(
                                type("T", (), {"symbol": symbol, "side": trade.side, "entry": trade.entry, "volume": 1.0}),
                                trade.take_profit,
                            )
                            wins += 1
                            break
                trades.append(trade)
                i += 8
            i += 1

        total = wins + losses
        return {
            "symbol": symbol,
            "trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / total * 100.0) if total else 0.0,
        }
