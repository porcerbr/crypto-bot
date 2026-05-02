from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import sqrt
from typing import Iterable

from config import Config


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_time_key(trade: dict) -> float:
    iso = trade.get("closed_ts_iso") or trade.get("opened_ts_iso")
    if iso:
        try:
            dt = datetime.fromisoformat(str(iso))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    ts = trade.get("closed_ts") or trade.get("opened_ts")
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


def normalize_history(history: Iterable[dict]) -> list[dict]:
    items = [dict(h) for h in history or []]
    items.sort(key=_trade_time_key)
    return items


def equity_curve_from_history(history: Iterable[dict], initial_balance: float | None = None) -> list[dict]:
    initial_balance = float(initial_balance if initial_balance is not None else Config.INITIAL_BALANCE)
    balance = initial_balance
    peak = initial_balance
    curve: list[dict] = []

    for trade in normalize_history(history):
        pnl = _safe_float(trade.get("pnl", 0.0))
        balance += pnl
        peak = max(peak, balance)
        drawdown = ((peak - balance) / peak * 100) if peak > 0 else 0.0
        curve.append({
            "t": trade.get("closed_at") or trade.get("closed_ts_iso") or trade.get("opened_at") or "",
            "balance": round(balance, 2),
            "pnl": round(pnl, 2),
            "drawdown_pct": round(drawdown, 2),
        })

    return curve


def calculate_metrics_from_history(
    history: Iterable[dict],
    initial_balance: float | None = None,
    current_balance: float | None = None,
    active_trades_count: int = 0,
    pending_trades_count: int = 0,
) -> dict:
    history_list = normalize_history(history)
    initial_balance = float(initial_balance if initial_balance is not None else Config.INITIAL_BALANCE)

    wins = [h for h in history_list if h.get("result") == "WIN"]
    losses = [h for h in history_list if h.get("result") == "LOSS"]
    total = len(wins) + len(losses)
    wr = round(len(wins) / total * 100, 1) if total > 0 else 0.0

    win_pnl = sum(_safe_float(h.get("pnl", 0.0)) for h in wins)
    loss_pnl = sum(abs(_safe_float(h.get("pnl", 0.0))) for h in losses)
    profit_factor = round(win_pnl / loss_pnl, 2) if loss_pnl > 0 else (float("inf") if win_pnl > 0 else 0.0)

    avg_win = win_pnl / len(wins) if wins else 0.0
    avg_loss = loss_pnl / len(losses) if losses else 0.0
    expectancy = round((wr / 100 * avg_win) - ((100 - wr) / 100 * avg_loss), 2) if total > 0 else 0.0

    equity_curve = equity_curve_from_history(history_list, initial_balance=initial_balance)
    max_dd = 0.0
    peak = initial_balance
    for point in equity_curve:
        bal = _safe_float(point.get("balance", initial_balance))
        peak = max(peak, bal)
        dd = ((peak - bal) / peak * 100) if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    returns = []
    prev_balance = initial_balance
    for point in equity_curve:
        bal = _safe_float(point.get("balance", prev_balance))
        if prev_balance > 0:
            returns.append((bal - prev_balance) / prev_balance)
        prev_balance = bal
    if returns:
        avg_ret = sum(returns) / len(returns)
        if len(returns) > 1:
            variance = sum((r - avg_ret) ** 2 for r in returns) / (len(returns) - 1)
            std = variance ** 0.5
        else:
            std = 0.0

        # ── Sharpe anualizado corretamente ────────────────────────────────────
        # Returns aqui são por trade, não diários. Annualizar por sqrt(252) é
        # incorreto — usamos o número de trades/ano estimado.
        # Se há timestamps ISO disponíveis, calcula a frequência real;
        # caso contrário assume 250 trades/ano como proxy conservador.
        trades_per_year = 250.0
        if len(history_list) >= 2:
            try:
                t_first = _trade_time_key(history_list[0])
                t_last  = _trade_time_key(history_list[-1])
                span_years = (t_last - t_first) / (365.25 * 24 * 3600)
                if span_years > 0.01:
                    trades_per_year = len(history_list) / span_years
            except Exception:
                pass

        sharpe = (avg_ret / std * sqrt(trades_per_year)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    current_balance = float(current_balance if current_balance is not None else (equity_curve[-1]["balance"] if equity_curve else initial_balance))
    total_pnl = round(current_balance - initial_balance, 2)

    return {
        "initial_balance": round(initial_balance, 2),
        "current_balance": round(current_balance, 2),
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "winrate": wr,
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": expectancy,
        "max_drawdown_pct": round(max_dd, 2),
        "total_pnl": total_pnl,
        "active_trades_count": int(active_trades_count),
        "pending_trades_count": int(pending_trades_count),
        "sharpe_ratio": round(sharpe, 3),
        "equity_curve": equity_curve,
    }


def trade_breakdown(history: Iterable[dict]) -> dict:
    history_list = normalize_history(history)
    by_symbol: dict[str, dict] = {}
    by_dir: dict[str, dict] = {}

    for trade in history_list:
        sym = trade.get("symbol", "?")
        direction = trade.get("dir") or trade.get("direction") or trade.get("direc", "?")
        pnl = _safe_float(trade.get("pnl", 0.0))

        sym_bucket = by_symbol.setdefault(sym, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        sym_bucket["trades"] += 1
        sym_bucket["pnl"] += pnl
        if trade.get("result") == "WIN":
            sym_bucket["wins"] += 1
        elif trade.get("result") == "LOSS":
            sym_bucket["losses"] += 1

        dir_bucket = by_dir.setdefault(direction, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        dir_bucket["trades"] += 1
        dir_bucket["pnl"] += pnl
        if trade.get("result") == "WIN":
            dir_bucket["wins"] += 1
        elif trade.get("result") == "LOSS":
            dir_bucket["losses"] += 1

    return {"by_symbol": by_symbol, "by_direction": by_dir}
