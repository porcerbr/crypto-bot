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
    cs = contract_size_for(symbol)
    notional = lot * cs * price
    return round(notional / leverage, 2)

def commission_for(symbol, lot):
    cat = "COMMODITIES" if symbol == "XAUUSD" else "FOREX"
    rate = Config.COMMISSION_PER_LOT.get(cat, 0.0)
    return round(rate * lot, 2)

def calc_trade_plan(symbol, entry, leverage, balance, margin_usd):
    entry = float(entry)
    eff_lev = min(leverage, max_leverage(symbol))
    margin_usd = float(margin_usd)

    if margin_usd <= 0:
        return {"ok": False, "error": "Margem deve ser positiva."}

    min_margin_min_lot = calc_margin(symbol, entry, eff_lev, Config.MIN_LOT)
    if margin_usd < min_margin_min_lot:
        return {"ok": False, "error": f"Margem mínima para 0.01 lote: ${min_margin_min_lot:.2f}"}

    cs = contract_size_for(symbol)
    lot = margin_usd * eff_lev / (cs * entry)
    lot = max(Config.MIN_LOT, math.floor(lot / Config.MIN_LOT) * Config.MIN_LOT)

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
    }
