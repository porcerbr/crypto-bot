"""hedgefund.py — camada de risco e monitoramento estilo hedge fund.

A ideia aqui não é prometer retorno alto; é fazer o bot pensar em
portfólio, cauda, concentração e regime antes de aceitar qualquer sinal.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite
from statistics import mean
from typing import Iterable

from config import Config
from performance import calculate_metrics_from_history


@dataclass(frozen=True)
class HedgeFundBudget:
    enabled: bool
    allowed: bool
    mode: str
    base_risk_pct: float
    recommended_risk_pct: float
    portfolio_factor: float
    account_factor: float
    concentration_factor: float
    tail_factor: float
    regime_factor: float
    reason: str
    var_95_pct: float
    cvar_95_pct: float
    stress_loss_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return values[0]
    if q >= 1:
        return values[-1]
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return values[lo] * (1 - frac) + values[hi] * frac


def _history_returns(history: Iterable[dict], initial_balance: float) -> list[float]:
    balance = max(1e-9, float(initial_balance))
    returns: list[float] = []
    for trade in history or []:
        pnl = _safe_float(trade.get("pnl", 0.0))
        if balance > 0:
            returns.append(pnl / balance)
        balance = max(1e-9, balance + pnl)
    return returns


def historical_var_cvar(
    history: Iterable[dict],
    initial_balance: float,
    confidence: float = 0.95,
) -> dict:
    """VaR/CVaR históricos em % e valor monetário."""
    returns = sorted(_history_returns(history, initial_balance))
    if not returns:
        return {
            "var_pct": 0.0,
            "cvar_pct": 0.0,
            "var_cash": 0.0,
            "cvar_cash": 0.0,
        }

    alpha = 1.0 - confidence
    var_pct = _quantile(returns, alpha)
    tail = [r for r in returns if r <= var_pct]
    cvar_pct = mean(tail) if tail else var_pct
    current_balance = max(1e-9, float(initial_balance) + sum(_safe_float(t.get("pnl", 0.0)) for t in history or []))
    return {
        "var_pct": round(abs(var_pct) * 100.0, 2),
        "cvar_pct": round(abs(cvar_pct) * 100.0, 2),
        "var_cash": round(abs(var_pct) * current_balance, 2),
        "cvar_cash": round(abs(cvar_pct) * current_balance, 2),
    }


def concentration_profile(history: Iterable[dict]) -> dict:
    history_list = list(history or [])
    if not history_list:
        return {
            "top_symbol": None,
            "top_symbol_share_pct": 0.0,
            "top_direction": None,
            "top_direction_share_pct": 0.0,
            "symbol_counts": {},
            "direction_counts": {},
        }

    sym_counter = Counter(str(t.get("symbol", "?")) for t in history_list)
    dir_counter = Counter(str(t.get("dir", t.get("direction", "?"))) for t in history_list)
    top_symbol, top_symbol_count = sym_counter.most_common(1)[0]
    top_direction, top_direction_count = dir_counter.most_common(1)[0]
    total = max(1, len(history_list))
    return {
        "top_symbol": top_symbol,
        "top_symbol_share_pct": round(top_symbol_count / total * 100.0, 2),
        "top_direction": top_direction,
        "top_direction_share_pct": round(top_direction_count / total * 100.0, 2),
        "symbol_counts": dict(sym_counter),
        "direction_counts": dict(dir_counter),
    }


def _portfolio_factor(metrics: dict, var_data: dict) -> float:
    sharpe = _safe_float(metrics.get("sharpe_ratio", 0.0))
    winrate = _safe_float(metrics.get("winrate", 0.0))
    dd = _safe_float(metrics.get("max_drawdown_pct", 0.0))
    profit_factor_raw = metrics.get("profit_factor", 0.0)
    profit_factor = 0.0 if profit_factor_raw == "inf" else _safe_float(profit_factor_raw, 0.0)
    cvar_pct = _safe_float(var_data.get("cvar_pct", 0.0))

    factor = 1.0
    if dd >= 15:
        factor *= 0.45
    elif dd >= 10:
        factor *= 0.65
    elif dd >= 6:
        factor *= 0.8

    if cvar_pct >= 2.5:
        factor *= 0.55
    elif cvar_pct >= 1.8:
        factor *= 0.72
    elif cvar_pct >= 1.2:
        factor *= 0.85

    if sharpe > 1.8:
        factor *= 1.10
    elif sharpe < 0.4:
        factor *= 0.80

    if winrate >= 60:
        factor *= 1.05
    elif winrate < 45:
        factor *= 0.90

    if profit_factor > 1.8:
        factor *= 1.06
    elif 0 < profit_factor < 1.0:
        factor *= 0.85

    return _clamp(factor, 0.25, 1.25)


def _account_factor(accounts: dict[str, dict], account_id: str) -> float:
    acc = (accounts or {}).get(account_id) or (accounts or {}).get("core") or {}
    equity = max(1e-9, _safe_float(acc.get("equity", 0.0), 0.0))
    reserved = max(0.0, _safe_float(acc.get("reserved_margin", 0.0), 0.0))
    open_trades = int(acc.get("open_trades", 0) or 0)
    dd = _safe_float(acc.get("max_drawdown_pct", 0.0), 0.0)
    available_ratio = max(0.0, (equity - reserved) / equity)
    factor = available_ratio

    if dd >= 10:
        factor *= 0.55
    elif dd >= 6:
        factor *= 0.75
    elif dd >= 3:
        factor *= 0.90

    if open_trades >= 3:
        factor *= 0.80
    elif open_trades == 0:
        factor *= 1.05

    return _clamp(factor, 0.20, 1.10)


def _regime_factor(signal: dict | None) -> float:
    if not signal:
        return 1.0
    regime = str(signal.get("market_regime", signal.get("regime", "neutral"))).lower()
    rr = _safe_float(signal.get("rr", 0.0), 0.0)
    score = _safe_float(signal.get("score", 0.0), 0.0)
    max_score = max(1.0, _safe_float(signal.get("max_score", 1.0), 1.0))
    quality = score / max_score

    factor = 1.0
    if regime in ("trend", "transition"):
        factor *= 1.05
    elif regime in ("range", "mean_reversion"):
        factor *= 0.88
    elif regime in ("weak_trend", "mixed_mtf", "wait"):
        factor *= 0.78

    if rr >= 2.5:
        factor *= 1.05
    elif rr < 1.6:
        factor *= 0.85

    if quality >= 0.7:
        factor *= 1.06
    elif quality < 0.5:
        factor *= 0.92

    return _clamp(factor, 0.60, 1.15)


def _concentration_factor(concentration: dict, active_trades: list[dict]) -> float:
    top_symbol_share = _safe_float(concentration.get("top_symbol_share_pct", 0.0), 0.0)
    top_direction_share = _safe_float(concentration.get("top_direction_share_pct", 0.0), 0.0)
    active_count = len(active_trades or [])
    factor = 1.0

    if top_symbol_share >= 60:
        factor *= 0.72
    elif top_symbol_share >= 45:
        factor *= 0.84

    if top_direction_share >= 70:
        factor *= 0.85
    elif top_direction_share >= 60:
        factor *= 0.92

    if active_count >= getattr(Config, "MAX_TRADES", 3):
        factor *= 0.80

    return _clamp(factor, 0.55, 1.0)


def stress_test_portfolio(
    active_trades: Iterable[dict],
    balance: float,
    var_data: dict | None = None,
) -> dict:
    active_list = list(active_trades or [])
    risk_usd = sum(abs(_safe_float(t.get("risk_usd", t.get("margin_required", 0.0)), 0.0)) for t in active_list)
    var_data = var_data or {}
    cvar_cash = _safe_float(var_data.get("cvar_cash", 0.0), 0.0)
    stress_loss_cash = risk_usd + cvar_cash
    stress_loss_pct = (stress_loss_cash / balance * 100.0) if balance > 0 else 0.0
    return {
        "stress_loss_cash": round(stress_loss_cash, 2),
        "stress_loss_pct": round(stress_loss_pct, 2),
        "risk_usd": round(risk_usd, 2),
        "open_trades": len(active_list),
    }


def build_hedgefund_budget(bot, signal: dict | None = None) -> HedgeFundBudget:
    balance = max(0.0, _safe_float(getattr(bot, "balance", 0.0), 0.0))
    history = list(getattr(bot, "history", []) or [])
    accounts = getattr(bot, "sync_accounts", lambda: {})() if hasattr(bot, "sync_accounts") else {}
    active_trades = list(getattr(bot, "active_trades", []) or [])

    metrics = calculate_metrics_from_history(
        history,
        initial_balance=Config.INITIAL_BALANCE,
        current_balance=balance,
        active_trades_count=len(active_trades),
        pending_trades_count=len(getattr(bot, "pending_trades", []) or []),
    )
    var_data = historical_var_cvar(history, initial_balance=Config.INITIAL_BALANCE, confidence=0.95)
    concentration = concentration_profile(history[-50:] if history else [])
    stress = stress_test_portfolio(active_trades, balance, var_data)

    base_risk_pct = _safe_float(getattr(Config, "RISK_PERCENT_PER_TRADE", 1.0), 1.0)
    account_id = "core"
    if hasattr(bot, "choose_account_for_signal") and signal is not None:
        try:
            account_id = bot.choose_account_for_signal(signal)
        except Exception:
            account_id = "core"

    portfolio_factor = _portfolio_factor(metrics, var_data)
    account_factor = _account_factor(accounts, account_id)
    regime_factor = _regime_factor(signal)
    concentration_factor = _concentration_factor(concentration, active_trades)
    tail_factor = _clamp(1.0 - (_safe_float(var_data.get("cvar_pct", 0.0), 0.0) / 10.0), 0.35, 1.0)

    recommended = base_risk_pct * portfolio_factor * account_factor * regime_factor * concentration_factor * tail_factor
    recommended = _clamp(recommended, getattr(Config, "MIN_RISK_PCT", 0.5), getattr(Config, "MAX_RISK_PCT", 2.2))

    reason_parts: list[str] = []
    if metrics.get("max_drawdown_pct", 0.0) >= 12:
        reason_parts.append("drawdown alto")
    if var_data.get("cvar_pct", 0.0) >= 2.5:
        reason_parts.append("cauda pesada")
    if concentration.get("top_symbol_share_pct", 0.0) >= 50:
        reason_parts.append("concentração por símbolo")
    if stress.get("stress_loss_pct", 0.0) >= 8:
        reason_parts.append("stress elevado")
    if signal and str(signal.get("market_regime", "neutral")).lower() in {"wait", "weak_trend", "mixed_mtf"}:
        reason_parts.append("regime fraco")

    allowed = balance > 0 and not (metrics.get("max_drawdown_pct", 0.0) >= 18 or stress.get("stress_loss_pct", 0.0) >= 12)
    mode = "aggressive"
    if not allowed or metrics.get("max_drawdown_pct", 0.0) >= 12 or var_data.get("cvar_pct", 0.0) >= 2.5:
        mode = "defensive"
    elif metrics.get("max_drawdown_pct", 0.0) >= 7 or var_data.get("cvar_pct", 0.0) >= 1.5:
        mode = "balanced"

    return HedgeFundBudget(
        enabled=bool(getattr(Config, "MULTI_ACCOUNT_ENABLED", True)),
        allowed=allowed,
        mode=mode,
        base_risk_pct=round(base_risk_pct, 2),
        recommended_risk_pct=round(recommended, 2),
        portfolio_factor=round(portfolio_factor, 3),
        account_factor=round(account_factor, 3),
        concentration_factor=round(concentration_factor, 3),
        tail_factor=round(tail_factor, 3),
        regime_factor=round(regime_factor, 3),
        reason="; ".join(reason_parts) if reason_parts else "OK",
        var_95_pct=_safe_float(var_data.get("var_pct", 0.0), 0.0),
        cvar_95_pct=_safe_float(var_data.get("cvar_pct", 0.0), 0.0),
        stress_loss_pct=_safe_float(stress.get("stress_loss_pct", 0.0), 0.0),
        sharpe_ratio=_safe_float(metrics.get("sharpe_ratio", 0.0), 0.0),
        max_drawdown_pct=_safe_float(metrics.get("max_drawdown_pct", 0.0), 0.0),
    )


def hedgefund_snapshot(bot, signal: dict | None = None) -> dict:
    budget = build_hedgefund_budget(bot, signal=signal)
    concentration = concentration_profile(getattr(bot, "history", []) or [])
    active = list(getattr(bot, "active_trades", []) or [])
    snapshot = {
        "budget": budget.__dict__,
        "active_trades": len(active),
        "open_risk_usd": round(sum(_safe_float(t.get("risk_usd", t.get("margin_required", 0.0)), 0.0) for t in active), 2),
        "portfolio": getattr(bot, "portfolio_snapshot", lambda: {})(),
        "concentration": concentration,
        "mode": budget.mode,
    }
    return snapshot


def risk_override(base_risk_pct: float, budget: HedgeFundBudget) -> float:
    if not budget.allowed:
        return 0.0
    return round(_clamp(min(base_risk_pct, budget.recommended_risk_pct), getattr(Config, "MIN_RISK_PCT", 0.5), getattr(Config, "MAX_RISK_PCT", 2.2)), 2)
