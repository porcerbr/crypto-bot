# risk.py
import math
from config import Config
from utils import asset_cat, contract_size_for, max_leverage, get_sl_tp_pct

def calc_margin(symbol, price, leverage, lot):
    cs = contract_size_for(symbol)
    notional = lot * cs * price  # simplificado para ativos USD
    return round(notional / leverage, 2)

def commission_for(symbol, lot):
    cat = asset_cat(symbol)
    rate = Config.COMMISSION_PER_LOT.get(cat, 0.0)
    return round(rate * lot, 2)

def calc_trade_plan(symbol, entry, leverage, balance, margin_usd):
    entry = float(entry)
    eff_lev = min(leverage, max_leverage(symbol))
    margin_usd = float(margin_usd)

    if margin_usd <= 0:
        return {"ok": False, "error": "Margem deve ser positiva."}

    # Lote necessário para usar exatamente essa margem
    min_margin = calc_margin(symbol, entry, eff_lev, Config.MIN_LOT)
    if margin_usd < min_margin:
        return {"ok": False, "error": f"Margem mínima para 0.01 lote: ${min_margin:.2f}"}

    lot = round(margin_usd / (contract_size_for(symbol) * entry) * eff_lev, 2)
    lot = max(Config.MIN_LOT, math.floor(lot / 0.01) * 0.01)

    sl_pct, tp_pct = get_sl_tp_pct(eff_lev)
    sl = round(entry * (1 - sl_pct/100), 5)
    tp = round(entry * (1 + tp_pct/100), 5)

    margin_required = calc_margin(symbol, entry, eff_lev, lot)
    commission = commission_for(symbol, lot)
    profit = (tp - entry) * contract_size_for(symbol) * lot - commission

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
