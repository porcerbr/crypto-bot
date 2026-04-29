
import math
from config import Config
from utils import max_leverage, get_dynamic_leverage, get_max_risk_absolute, get_sl_tp_pct


def contract_size_for(symbol: str) -> int:
    if symbol in Config.CONTRACT_SIZES_SPECIFIC:
        return Config.CONTRACT_SIZES_SPECIFIC[symbol]
    if symbol == "XAUUSD":
        return Config.CONTRACT_SIZES["COMMODITIES"]
    return Config.CONTRACT_SIZES.get("FOREX", 100000)


def _effective_leverage(symbol: str, balance: float, lot: float, override: int = None) -> int:
    """
    Retorna a alavancagem efetiva respeitando a hierarquia:
      DYNAMIC > FIXED > override do broker.
    """
    if Config.USE_DYNAMIC_LEVERAGE:
        return get_dynamic_leverage(balance)
    if Config.USE_FIXED_LEVERAGE:
        return Config.DEFAULT_LEVERAGE
    base = override if override is not None else Config.DEFAULT_LEVERAGE
    return min(base, max_leverage(symbol, lot))


def calc_margin(symbol: str, price: float, leverage: int, lot: float) -> float:
    """
    Margem necess\u00e1ria = (lot \u00d7 contract_size \u00d7 price) / leverage
    `leverage` j\u00e1 deve vir resolvido (din\u00e2mica/fixa/broker).
    """
    if leverage <= 0:
        leverage = Config.DEFAULT_LEVERAGE
    cs = contract_size_for(symbol)
    notional = lot * cs * price
    return round(notional / leverage, 2)


def commission_for(symbol: str, lot: float) -> float:
    cat = "COMMODITIES" if symbol == "XAUUSD" else "FOREX"
    rate = Config.COMMISSION_PER_LOT.get(cat, 0.0)
    return round(rate * lot, 2)


def calc_lot_for_risk(
    symbol: str,
    entry: float,
    sl_price: float,
    balance: float,
    risk_pct: float = 2.0,
    atr: float = None,
    atr_mult: float = 2.0,
) -> tuple[float, float, float]:
    """
    Turtle-style position sizing com cap de risco absoluto.
    Retorna (lot, real_risk_usd, risk_pct_real).
    """
    if balance <= 0 or entry <= 0:
        return Config.MIN_LOT, 0.0, 0.0

    # Risco monet\u00e1rio (% do saldo) com cap absoluto
    risk_money = balance * risk_pct / 100.0
    risk_money = min(risk_money, get_max_risk_absolute(balance))

    # Dist\u00e2ncia do stop
    if atr and atr > 0:
        stop_distance = atr * atr_mult
    else:
        stop_distance = abs(entry - sl_price)

    cs = contract_size_for(symbol)
    if stop_distance <= 0 or cs <= 0:
        return Config.MIN_LOT, 0.0, 0.0

    lot_ideal = risk_money / (stop_distance * cs)
    lot = max(Config.MIN_LOT, math.ceil(lot_ideal / Config.MIN_LOT) * Config.MIN_LOT)

    real_risk = lot * stop_distance * cs
    risk_pct_real = (real_risk / balance) * 100 if balance > 0 else 0

    return round(lot, 2), round(real_risk, 2), round(risk_pct_real, 1)


def calc_trade_plan(
    symbol: str,
    entry: float,
    leverage: int,
    balance: float,
    margin_usd: float,
) -> dict:
    """
    Plano de trade: calcula lote, SL/TP de fallback, margem e comiss\u00e3o.
    Retorna dict com {ok, lot, sl, tp, sl_pct, tp_pct, margin_required, commission, ...}.
    """
    try:
        entry = float(entry)
        margin_usd = float(margin_usd)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Valores num\u00e9ricos inv\u00e1lidos."}

    if margin_usd <= 0:
        return {"ok": False, "error": "Margem deve ser positiva."}
    if entry <= 0:
        return {"ok": False, "error": "Pre\u00e7o de entrada inv\u00e1lido."}

    # Alavancagem efetiva
    eff_lev = _effective_leverage(symbol, balance, Config.MIN_LOT, leverage)

    cs = contract_size_for(symbol)
    if cs <= 0:
        return {"ok": False, "error": f"Contract size inv\u00e1lido para {symbol}"}

    # Margem m\u00ednima para 0.01 lote
    min_margin_min_lot = calc_margin(symbol, entry, eff_lev, Config.MIN_LOT)
    if margin_usd < min_margin_min_lot:
        return {
            "ok": False,
            "error": f"Margem m\u00ednima para 0.01 lote: ${min_margin_min_lot:.2f}",
        }

    # Calcula lote pela margem dispon\u00edvel (round DOWN para n\u00e3o estourar margem)
    lot = margin_usd * eff_lev / (cs * entry)
    lot = max(Config.MIN_LOT, math.floor(lot / Config.MIN_LOT) * Config.MIN_LOT)

    # Recalcula alavancagem com o lote definitivo (modo din\u00e2mico broker)
    eff_lev = _effective_leverage(symbol, balance, lot, leverage)

    # SL/TP de fallback em % (quando n\u00e3o v\u00eam de SMC)
    sl_pct, tp_pct = get_sl_tp_pct(eff_lev)
    sl = round(entry * (1 - sl_pct / 100), 5)
    tp = round(entry * (1 + tp_pct / 100), 5)

    margin_required = calc_margin(symbol, entry, eff_lev, lot)
    commission = commission_for(symbol, lot)
    profit = (tp - entry) * cs * lot - commission

    return {
        "ok":                True,
        "lot":               round(lot, 2),
        "sl":                sl,
        "tp":                tp,
        "sl_pct":            sl_pct,
        "tp_pct":            tp_pct,
        "margin_required":   margin_required,
        "commission":        commission,
        "potential_profit":  round(profit, 2),
        "leverage":          eff_lev,
    }
