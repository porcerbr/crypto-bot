from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NONE = "NONE"

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

@dataclass
class Signal:
    symbol: str
    side: Side
    timeframe: str
    entry: float
    stop_loss: float
    take_profit: float
    score: int
    rr: float
    reason: str
    timestamp: datetime
    atr: float = 0.0
    spread_pips: float = 0.0

@dataclass
class TradeState:
    trade_id: str
    symbol: str
    side: Side
    entry: float
    stop_loss: float
    take_profit: float
    volume: float
    opened_at: str
    status: str = "OPEN"
    close_price: Optional[float] = None
    closed_at: Optional[str] = None
    pnl: float = 0.0
    result: Optional[str] = None

@dataclass
class BotState:
    balance: float = 1000.0
    equity: float = 1000.0
    day_start_equity: float = 1000.0
    open_trades: List[TradeState] = field(default_factory=list)
    recent_signals: List[Signal] = field(default_factory=list)
    last_loss_at_utc: Optional[str] = None
    total_wins: int = 0
    total_losses: int = 0
    total_breakeven: int = 0
    last_run_at_utc: Optional[str] = None
    daily_pnl: float = 0.0
