"""portfolio.py — neutro no modo signal-only.

Mantido apenas para compatibilidade com imports antigos.
Nenhuma lógica de capital, alocação ou bloqueio é aplicada.
"""

from copy import deepcopy
from config import Config


def init_accounts(total_balance: float) -> dict[str, dict]:
    return {}


def ensure_accounts(accounts: dict | None, total_balance: float) -> dict[str, dict]:
    return {}


def total_equity(accounts: dict[str, dict]) -> float:
    return 0.0


def portfolio_snapshot(accounts: dict[str, dict]) -> dict:
    return {"total_equity": 0.0, "accounts": {}}


def portfolio_report_lines(accounts: dict[str, dict]) -> list[str]:
    return ["Modo signal-only: capital desativado."]


def risk_tier(balance: float) -> float:
    return 1.0


def choose_account(signal: dict, accounts: dict[str, dict], balance: float) -> str:
    return "signal"


def account_risk_pct(account_id: str, accounts: dict[str, dict], balance: float, signal: dict | None = None) -> float:
    return 0.0


def can_trade_account(account_id: str, accounts: dict[str, dict], balance: float, margin_required: float) -> tuple[bool, str]:
    return True, "signal-only"


def reserve_margin(account_id: str, accounts: dict[str, dict], margin_required: float) -> dict[str, dict]:
    return {}


def release_margin(account_id: str, accounts: dict[str, dict], margin_required: float, pnl: float, result: str) -> dict[str, dict]:
    return {}
