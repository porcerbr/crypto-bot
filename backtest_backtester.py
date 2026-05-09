from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from core_indicators import add_indicators
from strategies_confluence_strategy import ConfluenceStrategy


@dataclass
class BacktestConfig:
    initial_balance: float = 10_000.0
    spread_pips: float = 1.2
    slippage_pips: float = 0.2
    commission_per_trade: float = 0.0
    risk_per_trade: float = 0.005


class Backtester:
    def __init__(self, strategy: ConfluenceStrategy, config: BacktestConfig | None = None) -> None:
        self.strategy = strategy
        self.config = config or BacktestConfig()

    def load(self, csv_path: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path, parse_dates=["time"])
        required = {"time", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"CSV faltando colunas: {sorted(missing)}")
        return add_indicators(df)

    def _simulate_trade(self, df: pd.DataFrame, entry: float, sl: float, tp: float, side: str) -> dict:
        risk = abs(entry - sl)
        for _, row in df.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            if side == "BUY":
                if low <= sl:
                    return {"r_multiple": -1.0}
                if high >= tp:
                    return {"r_multiple": abs(tp - entry) / risk}
            else:
                if high >= sl:
                    return {"r_multiple": -1.0}
                if low <= tp:
                    return {"r_multiple": abs(entry - tp) / risk}
        last_close = float(df.iloc[-1]["close"])
        if side == "BUY":
            return {"r_multiple": (last_close - entry) / risk}
        return {"r_multiple": (entry - last_close) / risk}

    def run(self, csv_path: str) -> dict:
        df = self.load(csv_path)
        signals = []
        start = 210
        for i in range(start, len(df) - 10):
            window = df.iloc[: i + 1]
            signal = self.strategy.generate_signal("EURUSD", window, window, window)
            if signal is None:
                continue
            future = df.iloc[i + 1 : min(len(df), i + 20)]
            trade = self._simulate_trade(future, signal.entry, signal.stop_loss, signal.take_profit, signal.side.value)
            signals.append({
                "time": signal.created_at.isoformat(),
                "side": signal.side.value,
                "entry": signal.entry,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "rr": signal.rr,
                "score": signal.score,
                "confidence": signal.confidence,
                **trade,
            })

        trades = pd.DataFrame(signals)
        if trades.empty:
            metrics = {
                "trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "max_drawdown": 0.0,
                "return_pct": 0.0,
            }
            return {"metrics": metrics, "trades": trades}

        wins = trades[trades["r_multiple"] > 0]
        losses = trades[trades["r_multiple"] <= 0]
        gross_profit = wins["r_multiple"].sum()
        gross_loss = abs(losses["r_multiple"].sum())
        win_rate = len(wins) / len(trades)
        profit_factor = float(gross_profit / gross_loss) if gross_loss else float("inf")
        expectancy = float(trades["r_multiple"].mean())

        equity = self.config.initial_balance * (1 + trades["r_multiple"].cumsum() * self.config.risk_per_trade)
        peaks = equity.cummax()
        drawdown = ((equity - peaks) / peaks).min()

        metrics = {
            "trades": int(len(trades)),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor if np.isfinite(profit_factor) else 999.0),
            "expectancy": float(expectancy),
            "max_drawdown": float(abs(drawdown)),
            "return_pct": float((equity.iloc[-1] / self.config.initial_balance - 1) * 100),
        }
        return {"metrics": metrics, "trades": trades}
