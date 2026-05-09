"""copytrade.py — utilidades de roteamento estilo copy trade.

Mantém a lógica de execução desacoplada: o bot continua em modo sinalizador,
mas cada sinal recebe uma rota (core/growth/reserve) com risco e margem
controlados por conta virtual.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from config import Config
from portfolio import account_risk_pct, choose_account, portfolio_snapshot


@dataclass(frozen=True)
class CopyTradeRoute:
    enabled: bool
    profile: str
    account_id: str
    account_name: str
    risk_pct: float
    allocation: float
    follower_accounts: list[str]
    master_account: str


def _account_name(accounts: dict[str, dict], account_id: str) -> str:
    acc = (accounts or {}).get(account_id, {})
    return str(acc.get("name") or account_id)


def _account_allocation(accounts: dict[str, dict], account_id: str) -> float:
    acc = (accounts or {}).get(account_id, {})
    try:
        return round(float(acc.get("allocation", 0.0)) * 100.0, 2)
    except Exception:
        return 0.0


def build_route(bot, signal: dict) -> CopyTradeRoute:
    """Seleciona a conta que receberá o sinal e define os followers."""
    accounts = bot.sync_accounts() if hasattr(bot, "sync_accounts") else {}
    enabled = bool(getattr(Config, "MULTI_ACCOUNT_ENABLED", True))
    profile = "signal_only"

    if enabled and accounts:
        account_id = choose_account(signal, accounts, getattr(bot, "balance", 0.0))
        risk = account_risk_pct(account_id, accounts, getattr(bot, "balance", 0.0), signal)
        master = "core"
        followers = [k for k in accounts.keys() if k != account_id]
        profile = "proportional"
    else:
        account_id = "signal_only"
        risk = float(getattr(Config, "RISK_PERCENT_PER_TRADE", 1.0))
        master = "signal_only"
        followers = []

    return CopyTradeRoute(
        enabled=enabled,
        profile=profile,
        account_id=account_id,
        account_name=_account_name(accounts, account_id),
        risk_pct=round(float(risk), 2),
        allocation=_account_allocation(accounts, account_id),
        follower_accounts=followers,
        master_account=master,
    )


def build_route_payload(bot, signal: dict) -> dict[str, Any]:
    """Versão serializável da rota para persistência e API."""
    route = build_route(bot, signal)
    payload = asdict(route)
    try:
        payload["portfolio"] = portfolio_snapshot(bot.sync_accounts())
    except Exception:
        payload["portfolio"] = {}
    return payload
