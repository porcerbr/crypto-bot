# risk.py
import math
from config import Config
from utils import currency_to_usd, symbol_profile, contract_size_for, max_leverage_for, asset_cat

def normalize_lot(lot):
    if lot <= 0:
        return 0.0
    step = Config.LOT_STEP
    return round(math.floor(lot / step) * step, 4)

def calc_margin(symbol, price, leverage, lot):
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    kind = profile["kind"]
    base = profile["base"]
    quote = profile["quote"]
    lot = float(lot)
    leverage = max(1.0, float(leverage))
    if kind == "FX":
        if quote == "USD":
            notional = lot * cs * float(price)
        elif base == "USD":
            notional = lot * cs
        else:
            base_to_usd = currency_to_usd(base)
            notional = lot * cs * base_to_usd
    else:
        notional = lot * cs * float(price)
    return round(notional / leverage, 2)

def commission_for(symbol, lot):
    if Config.ACCOUNT_TYPE not in ("RAW", "PRO"):
        return 0.0
    cat = asset_cat(symbol)
    rate = Config.COMMISSION_PER_LOT_SIDE.get(cat, 0.0)
    return round(rate * float(lot) * 2, 2)

def get_sl_tp_pct(leverage, rr_ratio=None):
    leverage = max(1, int(leverage))
    sl = Config.SL_TP_BASE_MULTIPLIER / leverage
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    rr = rr_ratio if rr_ratio is not None else Config.TP_SL_RATIO
    tp = sl * rr
    return round(sl, 2), round(tp, 2)

def calc_lot_from_margin(symbol, entry, leverage, margin_usd):
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    kind = profile["kind"]
    base = profile["base"]
    quote = profile["quote"]
    entry = float(entry)
    leverage = max(1.0, float(leverage))
    margin_usd = max(0.0, float(margin_usd))
    if kind == "FX":
        if quote == "USD":
            lot = margin_usd * leverage / (cs * entry)
        elif base == "USD":
            lot = margin_usd * leverage / cs
        else:
            base_to_usd = currency_to_usd(base)
            lot = margin_usd * leverage / (cs * base_to_usd)
    else:
        lot = margin_usd * leverage / (cs * entry)
    return normalize_lot(lot)

def calc_lot_from_risk(symbol, entry, sl_price, balance, risk_pct):
    risk_money = float(balance) * (float(risk_pct) / 100.0)
    sl_distance = abs(float(entry) - float(sl_price))
    if sl_distance <= 0 or risk_money <= 0:
        return Config.MIN_LOT
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    kind = profile["kind"]
    quote = profile["quote"]
    if kind == "FX":
        if profile["quote"] == "USD":
            loss_per_lot = sl_distance * cs
        elif profile["base"] == "USD":
            quote_to_usd = currency_to_usd(quote)
            loss_per_lot = sl_distance * cs * quote_to_usd
        else:
            quote_to_usd = currency_to_usd(quote)
            loss_per_lot = sl_distance * cs * quote_to_usd
    else:
        loss_per_lot = sl_distance * cs
    if loss_per_lot <= 0:
        return Config.MIN_LOT
    lot = risk_money / loss_per_lot
    return normalize_lot(lot)

def calc_trade_plan(symbol, entry, leverage, balance, risk_pct, margin_usd):
    entry = float(entry)
    # alavancagem efetiva já limita ao máximo do símbolo
    eff_lev = max(1.0, min(float(leverage), max_leverage_for(symbol)))
    balance = float(balance)
    risk_pct = float(risk_pct)
    margin_usd = float(margin_usd)

    # margem necessária para o LOTE MÍNIMO (0.01) com essa alavancagem
    min_margin_min_lot = calc_margin(symbol, entry, eff_lev, Config.MIN_LOT)

    if margin_usd <= 0:
        return {"ok": False, "error": "Valor de investimento deve ser maior que zero."}
    if entry <= 0:
        return {"ok": False, "error": "Preço de entrada inválido."}
    if balance <= 0:
        return {"ok": False, "error": "Saldo inválido."}

    sl_pct, tp_pct = get_sl_tp_pct(eff_lev)

    sl_price_buy = round(entry * (1 - sl_pct/100), 5)
    tp_price_buy = round(entry * (1 + tp_pct/100), 5)
    sl_price_sell = round(entry * (1 + sl_pct/100), 5)
    tp_price_sell = round(entry * (1 - tp_pct/100), 5)

    lot_by_margin = calc_lot_from_margin(symbol, entry, eff_lev, margin_usd)
    lot_by_risk_buy = calc_lot_from_risk(symbol, entry, sl_price_buy, balance, risk_pct)
    lot_by_risk_sell = calc_lot_from_risk(symbol, entry, sl_price_sell, balance, risk_pct)
    lot_by_risk = min(lot_by_risk_buy, lot_by_risk_sell)
    final_lot = normalize_lot(min(lot_by_margin, lot_by_risk))

    if final_lot < Config.MIN_LOT:
        return {
            "ok": False,
            "error": f"Valor insuficiente. Mínimo para 0.01 lotes de {symbol}: ${min_margin_min_lot:.2f} de margem.",
            "min_margin_required": min_margin_min_lot,
            "lot_by_margin": lot_by_margin,
            "lot_by_risk": lot_by_risk,
            "min_margin_for_min_lot": min_margin_min_lot,
        }

    margin_required = calc_margin(symbol, entry, eff_lev, final_lot)
    sl_dist_buy = abs(entry - sl_price_buy)
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])

    if profile["kind"] == "FX" and profile["quote"] == "USD":
        risk_loss_buy = sl_dist_buy * cs * final_lot
    elif profile["kind"] == "FX" and profile["base"] == "USD":
        quote_to_usd = currency_to_usd(profile["quote"])
        risk_loss_buy = sl_dist_buy * cs * final_lot * quote_to_usd
    else:
        risk_loss_buy = sl_dist_buy * cs * final_lot

    commission = commission_for(symbol, final_lot)
    tp_dist_buy = abs(tp_price_buy - entry)
    if profile["kind"] == "FX" and profile["quote"] == "USD":
        potential_profit = tp_dist_buy * cs * final_lot - commission
    elif profile["kind"] == "FX" and profile["base"] == "USD":
        quote_to_usd = currency_to_usd(profile["quote"])
        potential_profit = tp_dist_buy * cs * final_lot * quote_to_usd - commission
    else:
        potential_profit = tp_dist_buy * cs * final_lot - commission

    ratio = round(tp_pct / sl_pct, 2) if sl_pct > 0 else 0

    return {
        "ok": True,
        "symbol": symbol,
        "entry": entry,
        "leverage": eff_lev,
        "max_leverage": max_leverage_for(symbol),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "sl_price_buy": sl_price_buy,
        "tp_price_buy": tp_price_buy,
        "sl_price_sell": sl_price_sell,
        "tp_price_sell": tp_price_sell,
        "lot": final_lot,
        "lot_by_margin": round(lot_by_margin, 4),
        "lot_by_risk": round(lot_by_risk, 4),
        "margin_required": margin_required,
        "margin_usd": margin_usd,
        "risk_money": round(risk_loss_buy, 2),
        "risk_pct_of_balance": round(risk_loss_buy / balance * 100, 2),
        "commission": commission,
        "potential_profit": round(potential_profit, 2),
        "ratio": ratio,
        "contract_size": cs,
        "min_margin_for_min_lot": min_margin_min_lot,
        "note": [],
    }
