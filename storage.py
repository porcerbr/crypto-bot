from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json

from models import BotState, TradeState, Signal, Side, from_iso, to_iso

class StateStore:
    def __init__(self, path: str):
        self.path = Path(path)

    def load(self) -> BotState:
        if not self.path.exists():
            return BotState()
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        open_trades = [TradeState(**t) for t in data.get("open_trades", [])]
        recent_signals = []
        for s in data.get("recent_signals", []):
            s["timestamp"] = from_iso(s["timestamp"])
            s["side"] = Side(s["side"])
            recent_signals.append(Signal(**s))
        return BotState(
            balance=data.get("balance", 1000.0),
            equity=data.get("equity", 1000.0),
            day_start_equity=data.get("day_start_equity", 1000.0),
            open_trades=open_trades,
            recent_signals=recent_signals,
            last_loss_at_utc=data.get("last_loss_at_utc"),
            total_wins=data.get("total_wins", 0),
            total_losses=data.get("total_losses", 0),
            total_breakeven=data.get("total_breakeven", 0),
            last_run_at_utc=data.get("last_run_at_utc"),
            daily_pnl=data.get("daily_pnl", 0.0),
        )

    def save(self, state: BotState) -> None:
        payload = asdict(state)
        payload["recent_signals"] = [
            {**asdict(s), "timestamp": to_iso(s.timestamp), "side": s.side.value}
            for s in state.recent_signals[-200:]
        ]
        payload["open_trades"] = [
            {**asdict(t), "side": t.side.value}
            for t in state.open_trades
        ]
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)
