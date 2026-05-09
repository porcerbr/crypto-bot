from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SignalSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(slots=True)
class Signal:
    symbol: str
    side: SignalSide
    timeframe: str
    entry: float
    stop_loss: float
    take_profit: float
    rr: float
    score: float
    confidence: float
    probability: float
    reason: str
    created_at: datetime
    position_size: float = 0.0


@dataclass(slots=True)
class MarketState:
    symbol: str
    timeframe: str
    spread_pips: float
    volatility: float
    trend: str
    consolidation: bool
    last_price: float
    updated_at: datetime
