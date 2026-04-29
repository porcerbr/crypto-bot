
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import Config


# =============================================================================
# FORMATAÇÃO E LOG
# =============================================================================

def fmt(value: Any) -> str:
    """Formata números para exibição sem quebrar com None/strings."""
    try:
        if value is None:
            return "0"
        value = float(value)
    except (TypeError, ValueError):
        return str(value)

    av = abs(value)
    if av >= 10000:
        return f"{value:,.2f}"
    if av >= 1000:
        return f"{value:.2f}"
    if av >= 10:
        return f"{value:.4f}"
    if av >= 1:
        return f"{value:.5f}"
    return f"{value:.6f}"


def log(msg: str):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def asset_name(symbol: str) -> str:
    return Config.FXGOLD_ASSETS.get(symbol, symbol)


def is_jpy_pair(symbol: str) -> bool:
    return symbol.endswith("JPY")


def jpy_to_usd(pnl_jpy: float, usdjpy_price: float) -> float:
    if usdjpy_price and usdjpy_price > 0:
        return pnl_jpy / usdjpy_price
    return 0.0


# =============================================================================
# PIP FACTOR E P&L UNIFICADO
# =============================================================================

def pip_factor(symbol: str) -> float:
    """Retorna o tamanho de 1 pip em unidades de preço."""
    if is_jpy_pair(symbol) or symbol == "XAUUSD":
        return 0.01
    return 0.0001


def contract_size(symbol: str) -> int:
    """Tamanho do contrato por lote padrão (evita import circular com risk.py)."""
    if symbol in Config.CONTRACT_SIZES_SPECIFIC:
        return Config.CONTRACT_SIZES_SPECIFIC[symbol]
    if symbol == "XAUUSD":
        return Config.CONTRACT_SIZES["COMMODITIES"]
    return Config.CONTRACT_SIZES.get("FOREX", 100000)


def calc_pnl_usd(
    symbol: str,
    direction: str,
    entry: float,
    exit_price: float,
    lot: float,
    usdjpy_price: float = 150.0,
    commission: float = 0.0,
) -> float:
    """
    Cálculo unificado de P&L em USD.
    """
    cs = contract_size(symbol)
    if direction == "BUY":
        raw = (exit_price - entry) * cs * lot
    else:
        raw = (entry - exit_price) * cs * lot

    raw -= commission

    if is_jpy_pair(symbol):
        return jpy_to_usd(raw, usdjpy_price)
    return raw


def calc_pnl_pips(symbol: str, direction: str, entry: float, exit_price: float) -> float:
    """Distância em pips entre entry e exit, com sinal."""
    pf = pip_factor(symbol)
    if pf <= 0:
        return 0.0
    if direction == "BUY":
        return round((exit_price - entry) / pf, 1)
    return round((entry - exit_price) / pf, 1)


# =============================================================================
# ALAVANCAGEM
# =============================================================================

def max_leverage(symbol: str, lot: float = 0.01) -> int:
    """
    Retorna a alavancagem efetiva.
    Prioridade:
      1) dinâmica, se habilitada
      2) fixa, se habilitada
      3) fallback do broker/modelo
    """
    if getattr(Config, "USE_DYNAMIC_LEVERAGE", False):
        return get_dynamic_leverage(0.0)
    if getattr(Config, "USE_FIXED_LEVERAGE", True):
        return int(getattr(Config, "DEFAULT_LEVERAGE", 500))

    # Fallback de broker/modelo (mantido para compatibilidade)
    if symbol == "XAUUSD":
        return 1000 if lot <= 1.0 else 500
    return 1000 if lot <= 2.0 else 500


def get_sl_tp_pct(leverage: int, rr: float | None = None) -> tuple[float, float]:
    sl = Config.SL_TP_BASE_MULTIPLIER / max(1, int(leverage or 1))
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    sl = round(sl, 2)
    rr = rr or Config.TP_SL_RATIO
    tp = round(sl * rr, 2)
    return sl, tp


def get_sl_tp_atr(
    entry: float,
    atr: float,
    direction: str,
    atr_sl_mult: float = 1.5,
    atr_tp_mult: float = 2.5,
) -> tuple[float, float, float, float]:
    if not atr or atr <= 0:
        sl_dist = entry * 0.005
        tp_dist = sl_dist * (atr_tp_mult / max(atr_sl_mult, 1e-9))
    else:
        sl_dist = atr * atr_sl_mult
        tp_dist = atr * atr_tp_mult

    if direction == "BUY":
        sl = round(entry - sl_dist, 5)
        tp = round(entry + tp_dist, 5)
    else:
        sl = round(entry + sl_dist, 5)
        tp = round(entry - tp_dist, 5)
    return sl, tp, sl_dist, tp_dist


# =============================================================================
# SEGURANÇA DINÂMICA POR FAIXA DE SALDO
# =============================================================================

def _lookup_by_threshold(balance: float, table: dict, default):
    """Retorna o valor da primeira threshold >= balance."""
    try:
        bal = float(balance)
    except (TypeError, ValueError):
        bal = 0.0

    for threshold, value in sorted(table.items(), key=lambda kv: kv[0]):
        if bal <= threshold:
            return value
    return default


def get_dynamic_leverage(balance: float) -> int:
    """Alavancagem baseada no capital atual."""
    if not getattr(Config, "USE_DYNAMIC_LEVERAGE", False):
        return int(getattr(Config, "DEFAULT_LEVERAGE", 500))
    return int(_lookup_by_threshold(balance, Config.DYNAMIC_LEVERAGE_TABLE, getattr(Config, "DEFAULT_LEVERAGE", 500)))


def get_dynamic_max_trades(balance: float) -> int:
    """Máximo de trades ativos permitidos para o capital atual."""
    return int(_lookup_by_threshold(balance, Config.DYNAMIC_MAX_TRADES, getattr(Config, "MAX_TRADES", 1)))


def get_allowed_symbols(balance: float) -> list:
    """Lista de símbolos permitidos para o capital atual."""
    allowed: list[str] = []
    tiers = getattr(Config, "ASSET_TIERS", {})
    for tier in sorted(tiers.keys(), key=lambda x: (x if isinstance(x, (int, float)) else float("inf"))):
        tier_data = tiers[tier]
        if balance >= tier_data.get("min_balance", 0):
            allowed = list(tier_data.get("symbols", []))
    return allowed


def get_max_risk_absolute(balance: float) -> float:
    """Risco máximo absoluto (USD) permitido por trade."""
    return float(_lookup_by_threshold(balance, Config.MAX_RISK_ABSOLUTE_USD, 100.0))


def get_min_free_margin_pct(balance: float) -> float:
    """% mínima de margem livre obrigatória."""
    return float(_lookup_by_threshold(balance, Config.MIN_FREE_MARGIN_PCT, 0.15))


def get_dynamic_cooldown(balance: float) -> int:
    """Cooldown em segundos após loss, baseado no capital."""
    return int(_lookup_by_threshold(balance, Config.DYNAMIC_COOLDOWN, getattr(Config, "ASSET_COOLDOWN", 900)))


def is_symbol_allowed(symbol: str, balance: float) -> bool:
    return symbol in get_allowed_symbols(balance)


def is_weekend_gap_risk() -> bool:
    """
    True se estiver em período de alto risco de gap:
    - Sexta após FRIDAY_NO_TRADE_AFTER_HOUR UTC
    - Sábado inteiro
    - Domingo antes de SUNDAY_NO_TRADE_BEFORE_HOUR UTC
    """
    now = datetime.now(timezone.utc)
    dow = now.weekday()
    hour = now.hour

    friday_after = getattr(Config, "FRIDAY_NO_TRADE_AFTER_HOUR", 20)
    sunday_before = getattr(Config, "SUNDAY_NO_TRADE_BEFORE_HOUR", 21)

    if dow == 4 and hour >= friday_after:
        return True
    if dow == 5:
        return True
    if dow == 6 and hour < sunday_before:
        return True
    return False


def is_weekend() -> bool:
    """True durante sábado inteiro ou domingo antes da abertura."""
    return is_weekend_gap_risk() and datetime.now(timezone.utc).weekday() >= 5


# =============================================================================
# FILTRO DE SESSÃO POR PAR
# =============================================================================

_SESSION_WINDOWS: dict[str, list[tuple[int, int]]] = {
    "EURUSD": [(7, 20)],
    "GBPUSD": [(7, 20)],
    "EURGBP": [(7, 18)],
    "EURJPY": [(7, 20)],
    "GBPJPY": [(7, 20)],
    "USDJPY": [(0, 9), (12, 16)],
    "USDCAD": [(12, 21)],
    "USDCHF": [(7, 20)],
    "AUDUSD": [(22, 24), (0, 14)],
    "NZDUSD": [(21, 24), (0, 13)],
    "XAUUSD": [(7, 21)],
}


def is_good_session(symbol: str) -> bool:
    """
    True se o horário atual (UTC) está dentro da janela
    de liquidez principal do par.
    """
    windows = _SESSION_WINDOWS.get(symbol)
    if not windows:
        return True

    hour = datetime.now(timezone.utc).hour
    for start, end in windows:
        if start < end:
            if start <= hour < end:
                return True
        else:
            if hour >= start or hour < end:
                return True
    return False
