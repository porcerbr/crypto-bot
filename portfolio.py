"""portfolio.py — gerenciamento de multi-conta e proteção de capital.

Esta camada mantém carteiras virtuais (core/growth/reserve) dentro do saldo do bot,
permitindo escalonamento de risco, bloqueio por drawdown e reserva de capital.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math

from config import Config


ACCOUNT_ORDER = ("core", "growth", "reserve")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _period_keys(dt: datetime | None = None) -> tuple[str, str]:
    dt = dt or _utc_now()
    iso = dt.date().isoformat()
    week = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
    return iso, week


def _default_allocations() -> dict[str, float]:
    alloc = getattr(Config, "ACCOUNT_ALLOCATIONS", None) or {
        "core": 0.55,
        "growth": 0.30,
        "reserve": 0.15,
    }
    total = sum(float(v) for v in alloc.values()) or 1.0
    return {k: float(v) / total for k, v in alloc.items()}


def _account_templates() -> dict[str, dict]:
    return {
        "core": {
            "name": "Core",
            "allocation": _default_allocations().get("core", 0.55),
            "risk_multiplier": getattr(Config, "ACCOUNT_RISK_MULTIPLIERS", {}).get("core", 0.9),
            "daily_loss_limit_pct": getattr(Config, "ACCOUNT_DAILY_LOSS_LIMIT_PCT", {}).get("core", 3.5),
            "weekly_loss_limit_pct": getattr(Config, "ACCOUNT_WEEKLY_LOSS_LIMIT_PCT", {}).get("core", 7.5),
            "max_drawdown_pct": getattr(Config, "ACCOUNT_MAX_DRAWDOWN_PCT", {}).get("core", 8.0),
            "min_reserve_pct": 0.18,
        },
        "growth": {
            "name": "Growth",
            "allocation": _default_allocations().get("growth", 0.30),
            "risk_multiplier": getattr(Config, "ACCOUNT_RISK_MULTIPLIERS", {}).get("growth", 1.10),
            "daily_loss_limit_pct": getattr(Config, "ACCOUNT_DAILY_LOSS_LIMIT_PCT", {}).get("growth", 4.5),
            "weekly_loss_limit_pct": getattr(Config, "ACCOUNT_WEEKLY_LOSS_LIMIT_PCT", {}).get("growth", 9.0),
            "max_drawdown_pct": getattr(Config, "ACCOUNT_MAX_DRAWDOWN_PCT", {}).get("growth", 10.0),
            "min_reserve_pct": 0.15,
        },
        "reserve": {
            "name": "Reserve",
            "allocation": _default_allocations().get("reserve", 0.15),
            "risk_multiplier": getattr(Config, "ACCOUNT_RISK_MULTIPLIERS", {}).get("reserve", 0.55),
            "daily_loss_limit_pct": getattr(Config, "ACCOUNT_DAILY_LOSS_LIMIT_PCT", {}).get("reserve", 2.0),
            "weekly_loss_limit_pct": getattr(Config, "ACCOUNT_WEEKLY_LOSS_LIMIT_PCT", {}).get("reserve", 4.0),
            "max_drawdown_pct": getattr(Config, "ACCOUNT_MAX_DRAWDOWN_PCT", {}).get("reserve", 5.0),
            "min_reserve_pct": 0.28,
        },
    }


def init_accounts(total_balance: float) -> dict[str, dict]:
    total_balance = max(0.0, float(total_balance))
    allocations = _default_allocations()
    accounts = {}
    today, week = _period_keys()

    for key, tpl in _account_templates().items():
        eq = round(total_balance * allocations.get(key, 0.0), 2)
        accounts[key] = {
            "id": key,
            "name": tpl["name"],
            "allocation": round(allocations.get(key, 0.0), 4),
            "equity": eq,
            "reserved_margin": 0.0,
            "realized_pnl": 0.0,
            "daily_pnl": 0.0,
            "weekly_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "consecutive_losses": 0,
            "open_trades": 0,
            "peak_equity": eq,
            "max_drawdown_pct": 0.0,
            "last_trade_at": None,
            "locked_until": 0.0,
            "day_key": today,
            "week_key": week,
            "risk_multiplier": tpl["risk_multiplier"],
            "daily_loss_limit_pct": tpl["daily_loss_limit_pct"],
            "weekly_loss_limit_pct": tpl["weekly_loss_limit_pct"],
            "max_drawdown_pct_limit": tpl["max_drawdown_pct"],
            "min_reserve_pct": tpl["min_reserve_pct"],
        }
    return accounts


def ensure_accounts(accounts: dict | None, total_balance: float) -> dict[str, dict]:
    if not accounts:
        return init_accounts(total_balance)

    result = deepcopy(accounts)
    templates = _account_templates()
    for key in ACCOUNT_ORDER:
        if key not in result:
            result[key] = deepcopy(init_accounts(total_balance).get(key, {}))
        result[key].setdefault("id", key)
        result[key].setdefault("name", templates[key]["name"])
        result[key].setdefault("allocation", templates[key]["allocation"])
        result[key].setdefault("equity", 0.0)
        result[key].setdefault("reserved_margin", 0.0)
        result[key].setdefault("realized_pnl", 0.0)
        result[key].setdefault("daily_pnl", 0.0)
        result[key].setdefault("weekly_pnl", 0.0)
        result[key].setdefault("wins", 0)
        result[key].setdefault("losses", 0)
        result[key].setdefault("consecutive_losses", 0)
        result[key].setdefault("open_trades", 0)
        result[key].setdefault("peak_equity", result[key]["equity"])
        result[key].setdefault("max_drawdown_pct", 0.0)
        result[key].setdefault("last_trade_at", None)
        result[key].setdefault("locked_until", 0.0)
        result[key].setdefault("day_key", _period_keys()[0])
        result[key].setdefault("week_key", _period_keys()[1])
        result[key].setdefault("risk_multiplier", templates[key]["risk_multiplier"])
        result[key].setdefault("daily_loss_limit_pct", templates[key]["daily_loss_limit_pct"])
        result[key].setdefault("weekly_loss_limit_pct", templates[key]["weekly_loss_limit_pct"])
        result[key].setdefault("max_drawdown_pct_limit", templates[key]["max_drawdown_pct"])
        result[key].setdefault("min_reserve_pct", templates[key]["min_reserve_pct"])
    return result


def _reset_period_if_needed(account: dict, now: datetime | None = None) -> None:
    now = now or _utc_now()
    day_key, week_key = _period_keys(now)
    if account.get("day_key") != day_key:
        account["day_key"] = day_key
        account["daily_pnl"] = 0.0
    if account.get("week_key") != week_key:
        account["week_key"] = week_key
        account["weekly_pnl"] = 0.0


def total_equity(accounts: dict[str, dict]) -> float:
    return round(sum(float(a.get("equity", 0.0)) for a in accounts.values()), 2)


def available_equity(account: dict) -> float:
    return round(max(0.0, float(account.get("equity", 0.0)) - float(account.get("reserved_margin", 0.0))), 2)


def drawdown_pct(account: dict) -> float:
    peak = float(account.get("peak_equity", 0.0))
    eq = float(account.get("equity", 0.0))
    if peak <= 0:
        return 0.0
    return round(max(0.0, (peak - eq) / peak * 100), 2)


def risk_tier(balance: float) -> float:
    tiers = getattr(Config, "RISK_SCALING_TIERS", None) or {
        200: 0.85,
        500: 1.00,
        1000: 1.15,
        2500: 1.30,
        float("inf"): 1.45,
    }
    for threshold, value in sorted(tiers.items(), key=lambda kv: float(kv[0])):
        if balance <= float(threshold):
            return float(value)
    return 1.0


def choose_account(signal: dict, accounts: dict[str, dict], balance: float) -> str:
    """Escolhe a carteira virtual mais apropriada para o sinal."""
    accounts = ensure_accounts(accounts, balance)
    regime = str(signal.get("market_regime", signal.get("regime", "neutral"))).lower()
    score = float(signal.get("score", 0) or 0)
    max_score = float(signal.get("max_score", 1) or 1)
    rr = float(signal.get("rr", 0) or 0)
    ai_conf = float(signal.get("ai_confidence", 0) or 0)
    quality = score / max(1.0, max_score)

    if balance <= 200:
        pref = "core"
    elif regime in ("trend", "transition") and (quality >= 0.55 or rr >= 2.0 or ai_conf >= 7):
        pref = "growth"
    elif regime == "range":
        pref = "core"
    else:
        pref = "core" if ai_conf < 7 else "growth"

    candidates = [pref, "core", "growth", "reserve"]
    now = time.time()
    for key in candidates:
        acc = accounts.get(key)
        if not acc:
            continue
        if float(acc.get("locked_until", 0.0)) > now:
            continue
        if drawdown_pct(acc) >= float(acc.get("max_drawdown_pct_limit", 0.0)) > 0:
            continue
        return key
    return "core"


# time imported lazily to avoid circular-ish startup issues
import time  # noqa: E402


def account_risk_pct(account_id: str, accounts: dict[str, dict], balance: float, signal: dict | None = None) -> float:
    accounts = ensure_accounts(accounts, balance)
    acc = accounts.get(account_id) or accounts.get("core")
    if not acc:
        return 1.0

    base = getattr(Config, "RISK_SCALING_BASE_PCT", None)
    if base is None:
        base = getattr(Config, "ATR_RISK_PCT", 1.0)
    base *= risk_tier(balance)

    mult = float(acc.get("risk_multiplier", 1.0))
    q_factor = 1.0
    if signal:
        score = float(signal.get("score", 0) or 0)
        max_score = float(signal.get("max_score", 1) or 1)
        rr = float(signal.get("rr", 0) or 0)
        quality = score / max(1.0, max_score)
        q_factor += min(0.18, max(0.0, quality - 0.45) * 0.25)
        if rr >= 2.5:
            q_factor += 0.05
        elif rr < 1.7:
            q_factor -= 0.05

    pct = base * mult * q_factor

    # Ajuste hedge fund: afina risco conforme cauda, drawdown e stress.
    try:
        from hedgefund import build_hedgefund_budget, risk_override
        dummy_bot = type(
            "_HF",
            (),
            {
                "balance": balance,
                "history": [],
                "active_trades": [],
                "pending_trades": [],
                "sync_accounts": lambda self=None: accounts,
                "choose_account_for_signal": lambda self, sig: account_id,
                "portfolio_snapshot": lambda self=None: {},
            },
        )()
        budget = build_hedgefund_budget(dummy_bot, signal=signal)
        pct = risk_override(pct, budget)
    except Exception:
        pass

    floor = getattr(Config, "MIN_RISK_PCT", 0.5)
    cap = getattr(Config, "MAX_RISK_PCT", 2.2)
    return round(max(floor, min(cap, pct)), 2)


def can_trade_account(account_id: str, accounts: dict[str, dict], balance: float, margin_required: float) -> tuple[bool, str]:
    accounts = ensure_accounts(accounts, balance)
    acc = accounts.get(account_id)
    if not acc:
        return False, f"Conta '{account_id}' indisponível"

    now = time.time()
    if float(acc.get("locked_until", 0.0)) > now:
        return False, f"Conta {account_id} bloqueada temporariamente"

    _reset_period_if_needed(acc)

    if acc.get("daily_pnl", 0.0) <= -abs(float(acc.get("equity", 0.0))) * float(acc.get("daily_loss_limit_pct", 0.0)) / 100:
        return False, f"Conta {account_id} atingiu limite diário"
    if acc.get("weekly_pnl", 0.0) <= -abs(float(acc.get("equity", 0.0))) * float(acc.get("weekly_loss_limit_pct", 0.0)) / 100:
        return False, f"Conta {account_id} atingiu limite semanal"

    if drawdown_pct(acc) >= float(acc.get("max_drawdown_pct_limit", 0.0)) > 0:
        return False, f"Conta {account_id} em drawdown excessivo"

    reserve_floor = float(acc.get("equity", 0.0)) * float(acc.get("min_reserve_pct", 0.0))
    if available_equity(acc) - float(margin_required) < reserve_floor:
        return False, f"Conta {account_id} sem reserva suficiente"

    return True, ""


def reserve_margin(account_id: str, accounts: dict[str, dict], margin_required: float) -> dict[str, dict]:
    accounts = ensure_accounts(accounts, sum(a.get("equity", 0.0) for a in accounts.values()) if accounts else 0.0)
    acc = accounts[account_id]
    acc["equity"] = round(float(acc.get("equity", 0.0)) - float(margin_required), 2)
    acc["reserved_margin"] = round(float(acc.get("reserved_margin", 0.0)) + float(margin_required), 2)
    acc["open_trades"] = int(acc.get("open_trades", 0)) + 1
    acc["last_trade_at"] = _utc_now().isoformat()
    acc["peak_equity"] = max(float(acc.get("peak_equity", 0.0)), float(acc["equity"]))
    return accounts


def release_margin(account_id: str, accounts: dict[str, dict], margin_required: float, pnl: float, result: str = "WIN") -> dict[str, dict]:
    accounts = ensure_accounts(accounts, sum(a.get("equity", 0.0) for a in accounts.values()) if accounts else 0.0)
    acc = accounts[account_id]
    margin_required = float(margin_required)
    pnl = float(pnl)
    acc["reserved_margin"] = round(max(0.0, float(acc.get("reserved_margin", 0.0)) - margin_required), 2)
    acc["equity"] = round(float(acc.get("equity", 0.0)) + margin_required + pnl, 2)
    acc["realized_pnl"] = round(float(acc.get("realized_pnl", 0.0)) + pnl, 2)
    acc["daily_pnl"] = round(float(acc.get("daily_pnl", 0.0)) + pnl, 2)
    acc["weekly_pnl"] = round(float(acc.get("weekly_pnl", 0.0)) + pnl, 2)
    acc["last_trade_at"] = _utc_now().isoformat()
    acc["open_trades"] = max(0, int(acc.get("open_trades", 0)) - 1)
    if result == "WIN":
        acc["wins"] = int(acc.get("wins", 0)) + 1
        acc["consecutive_losses"] = 0
    else:
        acc["losses"] = int(acc.get("losses", 0)) + 1
        acc["consecutive_losses"] = int(acc.get("consecutive_losses", 0)) + 1
        if acc["consecutive_losses"] >= getattr(Config, "ACCOUNT_CONSECUTIVE_LOSSES_PAUSE", 3):
            acc["locked_until"] = max(float(acc.get("locked_until", 0.0)), time.time() + getattr(Config, "ACCOUNT_LOCK_SECONDS", 3600))

    acc["peak_equity"] = max(float(acc.get("peak_equity", 0.0)), float(acc["equity"]))
    peak = float(acc.get("peak_equity", 0.0))
    if peak > 0:
        acc["max_drawdown_pct"] = round(max(float(acc.get("max_drawdown_pct", 0.0)), (peak - float(acc["equity"])) / peak * 100), 2)

    return accounts


def portfolio_snapshot(accounts: dict[str, dict]) -> dict:
    accounts = deepcopy(accounts or {})
    total = total_equity(accounts) if accounts else 0.0
    snap = {
        "total_equity": round(total, 2),
        "available_equity": round(sum(available_equity(a) for a in accounts.values()), 2) if accounts else 0.0,
        "accounts": {},
    }
    for key, acc in accounts.items():
        acc = deepcopy(acc)
        acc["available_equity"] = available_equity(acc)
        acc["drawdown_pct"] = drawdown_pct(acc)
        snap["accounts"][key] = acc
    return snap


def portfolio_report_lines(accounts: dict[str, dict]) -> list[str]:
    accounts = ensure_accounts(accounts, total_equity(accounts) if accounts else 0.0)
    lines = []
    for key in ACCOUNT_ORDER:
        acc = accounts.get(key, {})
        lines.append(
            f"{key.upper()}: eq={acc.get('equity', 0):.2f} | avail={available_equity(acc):.2f} | "
            f"dd={drawdown_pct(acc):.1f}% | W/L={acc.get('wins',0)}/{acc.get('losses',0)}"
        )
    return lines
