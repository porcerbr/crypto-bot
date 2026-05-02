from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from config import Config
from performance import calculate_metrics_from_history
from utils import calc_pnl_usd


@dataclass
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


def load_bars_from_csv(path: str | Path) -> list[Bar]:
    path = Path(path)
    bars: list[Bar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_raw = row.get("timestamp") or row.get("time") or row.get("date")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except Exception:
                try:
                    ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
                    ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
            try:
                bars.append(Bar(
                    timestamp=ts,
                    open=float(row["open"] if "open" in row else row["Open"]),
                    high=float(row["high"] if "high" in row else row["High"]),
                    low=float(row["low"] if "low" in row else row["Low"]),
                    close=float(row["close"] if "close" in row else row["Close"]),
                ))
            except Exception:
                continue
    return bars


def backtest_trades(trades: Iterable[dict], initial_balance: float | None = None) -> dict:
    return calculate_metrics_from_history(trades, initial_balance=initial_balance)


def backtest_from_strategy(
    bars: list[Bar],
    strategy: Callable[[list[Bar], int], list[dict]],
    initial_balance: float | None = None,
) -> dict:
    """
    Estratégia recebe (bars, index_atual) e retorna uma lista de trades fechados.
    Cada trade deve ter ao menos: result, pnl, symbol, dir, closed_at.
    """
    all_trades: list[dict] = []
    for i in range(1, len(bars)):
        generated = strategy(bars, i) or []
        for trade in generated:
            trade = dict(trade)
            trade.setdefault("closed_at", bars[i].timestamp.isoformat())
            all_trades.append(trade)
    return calculate_metrics_from_history(all_trades, initial_balance=initial_balance)


def main():
    parser = argparse.ArgumentParser(description="Backtester genérico do bot")
    parser.add_argument("csv", help="Arquivo CSV com OHLC")
    parser.add_argument("--initial-balance", type=float, default=Config.INITIAL_BALANCE)
    args = parser.parse_args()

    bars = load_bars_from_csv(args.csv)
    if not bars:
        raise SystemExit("Nenhum candle válido encontrado no CSV.")

    report = {
        "bars": len(bars),
        "symbol": Path(args.csv).stem,
        "initial_balance": args.initial_balance,
        "note": "Integre uma strategy callback para backtest operacional.",
    }
    print(report)


if __name__ == "__main__":
    main()
