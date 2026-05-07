import math
from config import Config
from utils import max_leverage

def contract_size_for(symbol):
    if symbol in Config.CONTRACT_SIZES_SPECIFIC:
        return Config.CONTRACT_SIZES_SPECIFIC[symbol]
    if symbol == "XAUUSD":
        return Config.CONTRACT_SIZES["COMMODITIES"]
    return Config.CONTRACT_SIZES.get("FOREX", 100000)

def calc_margin(symbol, price, leverage, lot):
    """
    Calcula margem necessária.
    Se USE_DYNAMIC_LEVERAGE=True, 'leverage' já vem da função dinâmica.
    Se USE_FIXED_LEVERAGE=True (e dynamic=False), usa DEFAULT_LEVERAGE.
    """
    if Config.USE_FIXED_LEVERAGE and not Config.USE_DYNAMIC_LEVERAGE:
        leverage = Config.DEFAULT_LEVERAGE

    cs = contract_size_for(symbol)
    notional = lot * cs * price
    return round(notional / leverage, 2)

def commission_for(symbol, lot):
    cat = "COMMODITIES" if symbol == "XAUUSD" else "FOREX"
    rate = Config.COMMISSION_PER_LOT.get(cat, 0.0)
    return round(rate * lot, 2)

def calc_lot_for_risk(symbol, entry, sl_price, balance, risk_pct=2.0, atr=None, atr_mult=2.0):
    """
    Turtle-style position sizing com CAP de risco absoluto.

    Para pares JPY (USD/JPY, EUR/JPY, GBP/JPY):
      O P&L é denominado em JPY → precisa dividir pelo preço de entrada
      para converter para USD antes de calcular o lote.

    Para pares USD como cotação (EUR/USD, GBP/USD, XAU/USD):
      O P&L já está em USD → sem conversão necessária.
    """
    from utils import get_max_risk_absolute, is_jpy_pair

    risk_money = balance * risk_pct / 100.0

    # Cap de risco absoluto por banca
    max_risk_abs = get_max_risk_absolute(balance)
    risk_money = min(risk_money, max_risk_abs)

    if atr and atr > 0:
        stop_distance = atr * atr_mult
    else:
        stop_distance = abs(entry - sl_price)

    cs = contract_size_for(symbol)
    if stop_distance <= 0 or cs <= 0:
        return Config.MIN_LOT, 0.0, 0.0

    # ── Conversão de moeda para USD ──────────────────────────────
    # Para JPY: P&L por lote está em JPY → divide pelo rate para USD
    # Para XAUUSD e pares USD-quote: P&L já em USD → sem conversão
    if is_jpy_pair(symbol) and entry > 0:
        # Ex: USDJPY entry=156.49, stop=1.11 JPY
        # risco_usd_por_lote = (1.11 * 100000) / 156.49 = $709
        stop_distance_usd = (stop_distance * cs) / entry
    else:
        stop_distance_usd = stop_distance * cs

    if stop_distance_usd <= 0:
        return Config.MIN_LOT, 0.0, 0.0

    lot_ideal = risk_money / stop_distance_usd
    lot = max(Config.MIN_LOT, math.ceil(lot_ideal / Config.MIN_LOT) * Config.MIN_LOT)

    # Risco real em USD com o lote arredondado
    real_risk     = lot * stop_distance_usd
    risk_pct_real = (real_risk / balance) * 100 if balance > 0 else 0
    return round(lot, 2), round(real_risk, 2), round(risk_pct_real, 1)

def calc_trade_plan(symbol, entry, leverage, balance, margin_usd):
    """
    Plano de trade com alavancagem dinâmica e proteções.
    """
    from utils import get_dynamic_leverage

    entry = float(entry)
    margin_usd = float(margin_usd)

    if margin_usd <= 0:
        return {"ok": False, "error": "Margem deve ser positiva."}

    # ── Alavancagem efetiva ──────────────────────────────────────
    if Config.USE_DYNAMIC_LEVERAGE:
        eff_lev = get_dynamic_leverage(balance)
    elif Config.USE_FIXED_LEVERAGE:
        eff_lev = Config.DEFAULT_LEVERAGE
    else:
        eff_lev = min(leverage, max_leverage(symbol))

    cs = contract_size_for(symbol)
    lot_est = margin_usd * eff_lev / (cs * entry)
    lot_est = max(Config.MIN_LOT, math.floor(lot_est / Config.MIN_LOT) * Config.MIN_LOT)

    # Recalcula alavancagem se necessário
    if Config.USE_DYNAMIC_LEVERAGE:
        eff_lev = get_dynamic_leverage(balance)
    elif Config.USE_FIXED_LEVERAGE:
        eff_lev = Config.DEFAULT_LEVERAGE
    else:
        eff_lev = min(leverage, max_leverage(symbol, lot_est))

    min_margin_min_lot = calc_margin(symbol, entry, eff_lev, Config.MIN_LOT)
    if margin_usd < min_margin_min_lot:
        return {"ok": False, "error": f"Margem mínima para 0.01 lote: ${min_margin_min_lot:.2f}"}

    lot = margin_usd * eff_lev / (cs * entry)
    lot = max(Config.MIN_LOT, math.floor(lot / Config.MIN_LOT) * Config.MIN_LOT)

    # Alavancagem final
    if Config.USE_DYNAMIC_LEVERAGE:
        eff_lev = get_dynamic_leverage(balance)
    elif Config.USE_FIXED_LEVERAGE:
        eff_lev = Config.DEFAULT_LEVERAGE
    else:
        eff_lev = min(leverage, max_leverage(symbol, lot))

    from utils import get_sl_tp_pct
    sl_pct, tp_pct = get_sl_tp_pct(eff_lev)
    sl = round(entry * (1 - sl_pct/100), 5)
    tp = round(entry * (1 + tp_pct/100), 5)

    margin_required = calc_margin(symbol, entry, eff_lev, lot)
    commission = commission_for(symbol, lot)
    profit = (tp - entry) * cs * lot - commission

    return {
        "ok": True,
        "lot": lot,
        "sl": sl,
        "tp": tp,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "margin_required": margin_required,
        "commission": commission,
        "potential_profit": round(profit, 2),
        "leverage": eff_lev,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 4 — Limites de Perda, Correlação e Risco Dinâmico
# ═══════════════════════════════════════════════════════════════════════════════

# Grupos de correlação: pares que se movem juntos
_CORRELATION_GROUPS: list[list[str]] = [
    ["EURUSD", "GBPUSD", "EURGBP", "EURJPY", "GBPJPY"],  # EUR/GBP dominados
    ["USDJPY", "EURJPY", "GBPJPY"],                        # JPY cross
    ["AUDUSD", "NZDUSD", "USDCAD"],                        # Commodities/Oceania
    ["USDCHF", "EURUSD"],                                  # Safe haven inverso
    ["XAUUSD"],                                            # Ouro — isolado
]

# Limite máximo de sinais simultâneos no mesmo grupo correlacionado
_MAX_CORRELATED = getattr(Config, "MAX_CORRELATED_SIGNALS_PER_GROUP", 2)

# Limites de perda (% do balance) — podem ser sobrescritos pelo Config
_MAX_DAILY_LOSS_PCT  = getattr(Config, "MAX_DAILY_LOSS_PCT",  5.0)   # 5% diário
_MAX_WEEKLY_LOSS_PCT = getattr(Config, "MAX_WEEKLY_LOSS_PCT", 10.0)  # 10% semanal

# Fator de redução de risco por regime
_REGIME_RISK_FACTOR: dict[str, float] = {
    "TRENDING":  1.0,    # risco normal
    "RANGING":   0.75,   # risco reduzido 25%
    "VOLATILE":  0.5,    # risco reduzido 50%
    "BREAKOUT":  0.85,   # leve redução
    "UNKNOWN":   0.8,    # regime indefinido → conservador
}


def check_daily_loss_limit(
    trades_today: list[dict],
    balance: float,
    max_loss_pct: float | None = None,
) -> dict:
    """
    Verifica se a perda do dia já atingiu o limite máximo.

    Args:
        trades_today: lista de trades fechados hoje (dicts com 'pnl')
        balance: saldo atual
        max_loss_pct: limite percentual (default: Config.MAX_DAILY_LOSS_PCT ou 5%)

    Returns:
        dict com keys: blocked (bool), loss_pct (float), loss_usd (float), limit_pct (float)
    """
    limit = max_loss_pct if max_loss_pct is not None else _MAX_DAILY_LOSS_PCT

    if not trades_today or balance <= 0:
        return {"blocked": False, "loss_pct": 0.0, "loss_usd": 0.0, "limit_pct": limit}

    loss_usd = sum(
        abs(float(t.get("pnl", 0.0)))
        for t in trades_today
        if float(t.get("pnl", 0.0)) < 0
    )
    loss_pct = (loss_usd / balance) * 100.0

    blocked = loss_pct >= limit
    return {
        "blocked": blocked,
        "loss_pct": round(loss_pct, 2),
        "loss_usd": round(loss_usd, 2),
        "limit_pct": limit,
        "reason": f"Perda diária {loss_pct:.1f}% ≥ limite {limit}%" if blocked else "",
    }


def check_weekly_loss_limit(
    trades_week: list[dict],
    balance: float,
    max_loss_pct: float | None = None,
) -> dict:
    """
    Verifica se a perda da semana já atingiu o limite máximo.

    Args:
        trades_week: lista de trades fechados esta semana
        balance: saldo atual
        max_loss_pct: limite percentual (default: Config.MAX_WEEKLY_LOSS_PCT ou 10%)

    Returns:
        dict com keys: blocked (bool), loss_pct (float), loss_usd (float), limit_pct (float)
    """
    limit = max_loss_pct if max_loss_pct is not None else _MAX_WEEKLY_LOSS_PCT

    if not trades_week or balance <= 0:
        return {"blocked": False, "loss_pct": 0.0, "loss_usd": 0.0, "limit_pct": limit}

    loss_usd = sum(
        abs(float(t.get("pnl", 0.0)))
        for t in trades_week
        if float(t.get("pnl", 0.0)) < 0
    )
    loss_pct = (loss_usd / balance) * 100.0

    blocked = loss_pct >= limit
    return {
        "blocked": blocked,
        "loss_pct": round(loss_pct, 2),
        "loss_usd": round(loss_usd, 2),
        "limit_pct": limit,
        "reason": f"Perda semanal {loss_pct:.1f}% ≥ limite {limit}%" if blocked else "",
    }


def get_adjusted_risk_pct(
    base_risk_pct: float,
    regime: str = "UNKNOWN",
    consecutive_losses: int = 0,
) -> float:
    """
    Ajusta o risco percentual com base no regime de mercado e sequência de losses.

    Args:
        base_risk_pct: risco base configurado (ex: 2.0%)
        regime: string do regime atual ('TRENDING', 'VOLATILE', etc.)
        consecutive_losses: número de losses consecutivos recentes

    Returns:
        float: risco ajustado (sempre > 0, nunca > base_risk_pct)
    """
    # Fator de regime
    factor = _REGIME_RISK_FACTOR.get(regime.upper(), _REGIME_RISK_FACTOR["UNKNOWN"])

    # Fator adicional por sequência de losses (reduz progressivamente)
    # 0 losses → 1.0x | 1 loss → 0.9x | 2 → 0.8x | 3+ → 0.7x (mínimo)
    loss_factor = max(0.7, 1.0 - consecutive_losses * 0.1)

    adjusted = base_risk_pct * factor * loss_factor

    # Garante mínimo de 0.1% e máximo do base
    min_risk = getattr(Config, "MIN_RISK_PCT", 0.1)
    return round(max(min_risk, min(base_risk_pct, adjusted)), 3)


def check_correlation_limit(
    symbol: str,
    active_symbols: list[str],
    max_correlated: int | None = None,
) -> dict:
    """
    Verifica se abrir um sinal em `symbol` violaria o limite de correlação.

    Args:
        symbol: par que se quer abrir
        active_symbols: lista de pares com sinais/trades ativos
        max_correlated: máximo permitido por grupo (default: Config.MAX_CORRELATED_SIGNALS_PER_GROUP)

    Returns:
        dict com keys: blocked (bool), group (list), correlated_count (int), limit (int)
    """
    limit = max_correlated if max_correlated is not None else _MAX_CORRELATED

    # Encontra o grupo do símbolo-alvo
    target_group: list[str] = []
    for group in _CORRELATION_GROUPS:
        if symbol in group:
            target_group = group
            break

    if not target_group:
        # Ativo não pertence a nenhum grupo → sem restrição de correlação
        return {"blocked": False, "group": [], "correlated_count": 0, "limit": limit}

    # Conta quantos ativos do mesmo grupo já estão ativos
    active_in_group = [s for s in active_symbols if s in target_group and s != symbol]
    count = len(active_in_group)

    blocked = count >= limit
    return {
        "blocked": blocked,
        "group": target_group,
        "correlated_count": count,
        "active_in_group": active_in_group,
        "limit": limit,
        "reason": (
            f"Limite de correlação: {count}/{limit} pares do grupo já ativos {active_in_group}"
            if blocked else ""
        ),
    }


def get_max_total_exposure_pct(balance: float) -> float:
    """
    Retorna a exposição total máxima permitida (% do balance em risco simultâneo).

    Escala conservadoramente: bancas menores têm exposição relativa mais baixa.
    """
    if balance < 500:
        return 4.0
    if balance < 2000:
        return 6.0
    if balance < 5000:
        return 8.0
    return 10.0


def check_total_exposure(
    active_trades: list[dict],
    balance: float,
) -> dict:
    """
    Verifica se a exposição total atual está dentro do limite.

    Args:
        active_trades: lista de trades ativos (dicts com 'risk_usd')
        balance: saldo atual

    Returns:
        dict com keys: blocked (bool), exposure_pct (float), limit_pct (float)
    """
    if not active_trades or balance <= 0:
        return {"blocked": False, "exposure_pct": 0.0, "limit_pct": get_max_total_exposure_pct(balance)}

    total_risk_usd = sum(abs(float(t.get("risk_usd", t.get("margin_required", 0.0)))) for t in active_trades)
    exposure_pct = (total_risk_usd / balance) * 100.0
    limit = get_max_total_exposure_pct(balance)

    blocked = exposure_pct >= limit
    return {
        "blocked": blocked,
        "exposure_pct": round(exposure_pct, 2),
        "total_risk_usd": round(total_risk_usd, 2),
        "limit_pct": limit,
        "reason": f"Exposição total {exposure_pct:.1f}% ≥ limite {limit}%" if blocked else "",
    }
