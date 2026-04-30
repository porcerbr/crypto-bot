
import time
import random
from datetime import datetime, timezone
from ai_validator import load_ai_params, validate_signal
from config import Config
from utils import (
    log, is_jpy_pair, is_good_session, pip_factor,
    get_dynamic_max_trades, is_symbol_allowed, is_weekend_gap_risk,
    get_allowed_symbols, get_dynamic_cooldown, get_dynamic_leverage,
)
from analysis import get_multi_timeframe
from risk import calc_margin, contract_size_for, calc_lot_for_risk
from news_filter import is_high_impact_news_window


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# SAFETY CHECK
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def _is_safe_to_trade(bot, symbol: str) -> tuple[bool, str]:
    """Retorna (True, "") se seguro, ou (False, "motivo") se bloqueado."""
    # 1. Limite de trades ativos por banca
    max_trades = get_dynamic_max_trades(bot.balance)
    if len(bot.active_trades) >= max_trades:
        return False, f"Limite de {max_trades} trade(s) ativo(s)"

    # 2. Tier de ativos permitidos
    if not is_symbol_allowed(symbol, bot.balance):
        allowed = get_allowed_symbols(bot.balance)
        return False, f"Ativo bloqueado. Permitidos: {', '.join(allowed)}"

    # 3. Fim de semana / gap
    if is_weekend_gap_risk():
        return False, "Prote\u00e7\u00e3o de fim de semana/gap ativa"

    # 4. Cooldown din\u00e2mico ap\u00f3s loss
    cooldown = get_dynamic_cooldown(bot.balance)
    last_loss_ts = bot.asset_cooldown.get(symbol, 0)
    if time.time() < last_loss_ts:
        return False, f"Cooldown ativo ({cooldown // 60}min)"

    # 5. Sess\u00e3o principal do par
    if not is_good_session(symbol):
        return False, "Fora da sess\u00e3o principal"

    # 6. Horas bloqueadas pela IA (Opus mensal)
    from ai_validator import load_ai_params
    ai_params = load_ai_params()
    avoid_hours = ai_params.get("avoid_hours_utc", [])
    if avoid_hours and datetime.now(timezone.utc).hour in avoid_hours:
        return False, f"Hora bloqueada pela IA ({datetime.now(timezone.utc).hour}h UTC)"

    # 7. Pares bloqueados por aprendizado
    if symbol in ai_params.get("blocked_pairs", []):
        return False, "Par bloqueado pela IA (WR baixo)"

    return True, ""


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# CONFLU\u00caNCIA
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def calc_confluence(res: dict, direction: str, mtf: dict = None) -> tuple[int, int, list, bool, int]:
    """
    Calcula score de conflu\u00eancia.
    Retorna (score, total_checks, checks, passed, min_required).
    """
    price = res["price"]

    # \u2500\u2500 T\u00e9cnicos base \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if direction == "BUY":
        checks = [
            ("Pre\u00e7o > EMA200",              res["price"] > res["ema200"]),
            ("EMA9 > EMA21",                res["ema9"]  > res["ema21"]),
            ("MACD bullish",                res["macd_bull"]),
            ("RSI entre 40-65",             40 < res["rsi"] < 65),
            ("ADX > 25",                    res["adx"] > 25),
            ("Pre\u00e7o perto da banda inferior", res["price"] < res["lower"] * 1.01),
            ("Candle de for\u00e7a",             res.get("candle_bull", False)),
        ]
    else:
        checks = [
            ("Pre\u00e7o < EMA200",              res["price"] < res["ema200"]),
            ("EMA9 < EMA21",                res["ema9"]  < res["ema21"]),
            ("MACD bearish",                res["macd_bear"]),
            ("RSI entre 35-60",             35 < res["rsi"] < 60),
            ("ADX > 25",                    res["adx"] > 25),
            ("Pre\u00e7o perto da banda superior", res["price"] > res["upper"] * 0.99),
            ("Candle de for\u00e7a",             res.get("candle_bear", False)),
        ]

    # \u2500\u2500 SMC \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    fvg = res.get("fvg", {}) or {}
    ob = res.get("ob", {}) or {}
    sweep = res.get("sweep", {}) or {}

    if direction == "BUY":
        fvg_active = any(f.get("active") for f in fvg.get("bullish", []))
        ob_active  = any(o.get("active") for o in ob.get("bullish", []))
        swing_low  = sweep.get("swing_low")
        # CORRIGIDO: s\u00f3 passa se swing_low existe E price > swing_low
        structure_ok = swing_low is not None and price > swing_low

        checks.append(("FVG Bullish ativo",       fvg_active))
        checks.append(("Order Block Bullish",     ob_active))
        checks.append(("Liquidity Sweep Bullish", bool(sweep.get("bullish"))))
        checks.append(("Estrutura intacta",       structure_ok))
    else:
        fvg_active = any(f.get("active") for f in fvg.get("bearish", []))
        ob_active  = any(o.get("active") for o in ob.get("bearish", []))
        swing_high = sweep.get("swing_high")
        structure_ok = swing_high is not None and price < swing_high

        checks.append(("FVG Bearish ativo",       fvg_active))
        checks.append(("Order Block Bearish",     ob_active))
        checks.append(("Liquidity Sweep Bearish", bool(sweep.get("bearish"))))
        checks.append(("Estrutura intacta",       structure_ok))

    # \u2500\u2500 MTF H4 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if mtf:
        checks.append(("MTF H4 alinhado", bool(mtf.get("aligned", False))))
        h4 = mtf.get("h4", {}) or {}
        if h4:
            if direction == "BUY":
                checks.append(("H4 > EMA200", h4.get("price", 0) > h4.get("ema200", float('inf'))))
            else:
                checks.append(("H4 < EMA200", h4.get("price", float('inf')) < h4.get("ema200", 0)))

    score  = sum(1 for _, ok in checks if ok)
    total  = len(checks)
    passed = score >= Config.MIN_CONFLUENCE
    return score, total, checks, passed, Config.MIN_CONFLUENCE


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# SL/TP BASEADOS EM SMC
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def _get_smc_sl_tp(entry: float, direction: str, res: dict, mtf: dict, atr: float):
    """
    Retorna (sl, tp, rr, sl_source, tp_source).
    """
    sl = None
    tp = None
    sl_source = "atr"
    tp_source = "atr"

    ob    = res.get("ob", {}) or {}
    sweep = res.get("sweep", {}) or {}
    fvg   = res.get("fvg", {}) or {}

    # \u2500\u2500 SL: extremo do Order Block \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if Config.USE_OB_FOR_SL:
        if direction == "BUY":
            obs = ob.get("bullish", [])
            if obs:
                best_ob = min(obs, key=lambda x: abs(x["low"] - entry))
                if best_ob["low"] < entry:
                    buffer = 0.5 * atr if atr and atr > 0 else abs(entry - best_ob["low"]) * 0.1
                    sl = round(best_ob["low"] - buffer, 5)
                    sl_source = "ob"
        else:
            obs = ob.get("bearish", [])
            if obs:
                best_ob = min(obs, key=lambda x: abs(x["high"] - entry))
                if best_ob["high"] > entry:
                    buffer = 0.5 * atr if atr and atr > 0 else abs(best_ob["high"] - entry) * 0.1
                    sl = round(best_ob["high"] + buffer, 5)
                    sl_source = "ob"

    # Fallback ATR
    if sl is None:
        if atr and atr > 0:
            if direction == "BUY":
                sl = round(entry - Config.ATR_SL_MULT * atr, 5)
            else:
                sl = round(entry + Config.ATR_SL_MULT * atr, 5)
        else:
            # sem ATR: usa 0.5% como fallback
            if direction == "BUY":
                sl = round(entry * 0.995, 5)
            else:
                sl = round(entry * 1.005, 5)

    # \u2500\u2500 TP: liquidity pool H4 \u2192 FVG \u2192 ATR \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if Config.USE_LIQUIDITY_FOR_TP and mtf:
        h4_sweep = (mtf.get("h4") or {}).get("sweep", {}) or {}
        if direction == "BUY" and h4_sweep.get("swing_high"):
            tp = round(h4_sweep["swing_high"], 5)
            tp_source = "liquidity"
        elif direction == "SELL" and h4_sweep.get("swing_low"):
            tp = round(h4_sweep["swing_low"], 5)
            tp_source = "liquidity"

    if tp is None and Config.USE_FVG_FOR_TP:
        if direction == "BUY":
            valid = [f for f in fvg.get("bullish", []) if f["top"] > entry]
            if valid:
                tp = round(max(f["top"] for f in valid), 5)
                tp_source = "fvg"
        else:
            valid = [f for f in fvg.get("bearish", []) if f["bottom"] < entry]
            if valid:
                tp = round(min(f["bottom"] for f in valid), 5)
                tp_source = "fvg"

    if tp is None:
        if atr and atr > 0:
            if direction == "BUY":
                tp = round(entry + Config.ATR_TP_MULT * atr, 5)
            else:
                tp = round(entry - Config.ATR_TP_MULT * atr, 5)
        else:
            tp = round(entry * (1.01 if direction == "BUY" else 0.99), 5)

    # \u2500\u2500 R:R din\u00e2mico baseado em SMC score \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    side = "bullish" if direction == "BUY" else "bearish"
    smc_checks = sum(1 for ok in [
        any(f.get("active") for f in fvg.get(side, [])),
        any(o.get("active") for o in ob.get(side, [])),
        bool(sweep.get(side)),
        bool(mtf.get("aligned") if mtf else False),
    ] if ok)

    rr_target = Config.TP_SL_RATIO_BASE + (smc_checks * Config.TP_SL_RATIO_STEP)
    rr_target = min(rr_target, Config.MAX_TP_SL_RATIO)

    # Valida\u00e7\u00f5es finais: TP/SL devem estar do lado correto
    if direction == "BUY":
        if sl >= entry or tp <= entry:
            return None, None, 0, sl_source, tp_source
    else:
        if sl <= entry or tp >= entry:
            return None, None, 0, sl_source, tp_source

    dist_sl = abs(entry - sl)
    dist_tp = abs(tp - entry)
    if dist_sl <= 0:
        return None, None, 0, sl_source, tp_source

    rr_real = round(dist_tp / dist_sl, 2)

    # Se o R:R din\u00e2mico \u00e9 maior que o do SMC, ajusta TP para atingi-lo
    if rr_target > rr_real:
        if direction == "BUY":
            tp = round(entry + rr_target * dist_sl, 5)
        else:
            tp = round(entry - rr_target * dist_sl, 5)
        tp_source = "rr_dynamic"
        rr_real = rr_target

    return sl, tp, rr_real, sl_source, tp_source


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# SCAN PRINCIPAL
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
def scan(bot):
    if bot.is_paused():
        return

    max_trades = get_dynamic_max_trades(bot.balance)
    if len(bot.active_trades) >= max_trades:
        return

    if is_high_impact_news_window(minutes_before=15, minutes_after=30):
        return

    if is_weekend_gap_risk():
        return

    symbols = list(Config.FXGOLD_ASSETS.keys())
    random.shuffle(symbols)  # evita vi\u00e9s

    for sym in symbols:
        safe, reason = _is_safe_to_trade(bot, sym)
        if not safe:
            if reason and "Cooldown" not in reason:
                log(f"[SAFETY] {sym}: {reason}")
            continue

        if any(t["symbol"] == sym for t in bot.active_trades + bot.pending_trades):
            continue

        mtf = get_multi_timeframe(sym)
        if not mtf or not mtf.get("h1"):
            continue

        res = mtf["h1"]
        if res.get("cenario") == "NEUTRO":
            continue

        direction = "BUY" if res["cenario"] == "ALTA" else "SELL"
        sc, tot_c, checks, passed, _ = calc_confluence(res, direction, mtf)
        if not passed:
            continue

        entry = res["price"]
        atr = res.get("atr", 0) or 0

        sl, tp, rr, sl_src, tp_src = _get_smc_sl_tp(entry, direction, res, mtf, atr)
        if not sl or not tp:
            log(f"[SMC] {sym}: SL/TP inv\u00e1lido, descartado")
            continue

        sl_pct = round((abs(entry - sl) / entry) * 100, 2) if entry else 0
        tp_pct = round((abs(tp - entry) / entry) * 100, 2) if entry else 0

        pf = pip_factor(sym)
        sl_pips = round(abs(entry - sl) / pf)
        tp_pips = round(abs(tp - entry) / pf)

        # \u2500\u2500 Position sizing \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        eff_lev = get_dynamic_leverage(bot.balance)

        suggested_lot, suggested_risk_usd, suggested_risk_pct = calc_lot_for_risk(
            sym, entry, sl, bot.balance,
            risk_pct=Config.ATR_RISK_PCT,
            atr=atr,
            atr_mult=Config.ATR_MULT_FOR_RISK,
        )

        min_lot_margin = calc_margin(sym, entry, eff_lev, Config.MIN_LOT)
        dist_sl = abs(entry - sl)
        cs_val = contract_size_for(sym)
        risk_001_lot = dist_sl * cs_val * 0.01
        risk_pct_001 = (risk_001_lot / bot.balance) * 100 if bot.balance > 0 else 0

        # \u2500\u2500 Filtro de correla\u00e7\u00e3o \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        est_risk_usd = suggested_risk_usd
        if is_jpy_pair(sym):
            usdjpy = bot._usdjpy_price or 150.0
            est_risk_usd = est_risk_usd / usdjpy

        ok_corr, msg_corr = bot.check_correlation_exposure(sym, est_risk_usd)
        if not ok_corr:
            log(f"[CORR] {sym}: {msg_corr} \u2014 sinal descartado")
            continue

        # \u2500\u2500 Valida\u00e7\u00e3o final pela IA (par\u00e2metros aprendidos) \u2500\u2500\u2500\u2500\u2500\u2500
        
        ai_params = load_ai_params()
        min_rr = ai_params.get("min_rr", 1.5)

        base_conf = ai_params.get("min_confluence", Config.MIN_CONFLUENCE)
        bias      = ai_params.get("strategy_bias", "balanced")

        bias_adj = {"conservative": +1, "aggressive": -1}.get(bias, 0)
        live_conf = ai_params.get("live_confluence", base_conf)
        effective_min_conf = max(6, min(9, live_conf + bias_adj))

        if sc < effective_min_conf:
            log(
                f"[CONF] {sym}: score {sc} < m\u00ednimo {effective_min_conf} "
                f"(base={base_conf}, bias={bias}, regime={ai_params.get('live_regime','?')})"
            )
            continue

        if rr < min_rr:
            log(f"[RR] {sym}: R:R {rr} abaixo do m\u00ednimo {min_rr}, descartado")
            continue

        # \u2500\u2500 Monta sinal pendente \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        pend = {
            "pending_id":           bot.next_pending_id(),
            "symbol":               sym,
            "name":                 Config.FXGOLD_ASSETS.get(sym, sym),
            "dir":                  direction,
            "entry":                entry,
            "sl":                   sl,
            "tp":                   tp,
            "sl_pct":               sl_pct,
            "tp_pct":               tp_pct,
            "sl_pips":              sl_pips,
            "tp_pips":              tp_pips,
            "rr":                   rr,
            "score":                sc,
            "max_score":            tot_c,
            "checks":               [{"name": nm, "ok": ok} for nm, ok in checks],
            "min_lot_margin":       round(min_lot_margin, 2),
            "risk_001_lot":         round(risk_001_lot, 2),
            "risk_pct_001":         round(risk_pct_001, 2),
            "suggested_lot":        suggested_lot,
            "suggested_risk_usd":   suggested_risk_usd,
            "suggested_risk_pct":   suggested_risk_pct,
            "created_at":           datetime.now().strftime("%d/%m %H:%M"),
            "created_ts":           time.time(),
            "atr":                  atr,
            "adx":                  res.get("adx", 0),
            "mtf_aligned":          mtf.get("aligned", False),
            "h4_cenario":           mtf.get("h4_cenario", "NEUTRO"),
            "sl_source":            sl_src,
            "tp_source":            tp_src,
        }

        # \u2500\u2500 Valida\u00e7\u00e3o pela IA (camada 1) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        approved, ai_reason = validate_signal(pend, mtf, bot)
        if not approved:
            log(f"[AI] {sym} {direction} rejeitado: {ai_reason}")
            continue

        ai_confidence = 0
        try:
            if "IA (" in ai_reason:
                ai_confidence = int(ai_reason.split("(")[1].split("/")[0])
        except (ValueError, IndexError):
            pass

        pend["ai_reason"]     = ai_reason
        pend["ai_approved"]   = True
        pend["ai_confidence"] = ai_confidence

        bot.add_pending(pend)
        break  # gera 1 sinal por scan


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# SNAPSHOT DE CONFLU\u00caNCIA (dashboard/telegram)
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
_snapshot_cache: list = []
_snapshot_ts: float  = 0.0
_SNAPSHOT_TTL: int   = 600  # 10 min


def get_confluence_snapshot() -> list[dict]:
    """Varre todos os pares e retorna score de conflu\u00eancia atual. Cacheado 10min."""
    global _snapshot_cache, _snapshot_ts

    if time.time() - _snapshot_ts < _SNAPSHOT_TTL and _snapshot_cache:
        return _snapshot_cache

    results = []
    for sym in Config.FXGOLD_ASSETS:
        try:
            mtf = get_multi_timeframe(sym)
            h1  = mtf.get("h1")
            if not h1:
                continue

            buy_sc,  buy_tot,  buy_checks,  _, _ = calc_confluence(h1, "BUY",  mtf)
            sell_sc, sell_tot, sell_checks, _, _ = calc_confluence(h1, "SELL", mtf)

            best_dir   = "BUY" if buy_sc >= sell_sc else "SELL"
            best_score = max(buy_sc, sell_sc)

            results.append({
                "symbol":      sym,
                "buy_score":   buy_sc,
                "sell_score":  sell_sc,
                "best_dir":    best_dir,
                "best_score":  best_score,
                "total":       buy_tot,
                "rsi":         round(h1.get("rsi", 0), 1),
                "adx":         round(h1.get("adx", 0), 1),
                "cenario":     h1.get("cenario", "NEUTRO"),
                "h4_aligned":  mtf.get("aligned", False),
                "buy_checks":  [{"name": n, "ok": ok} for n, ok in buy_checks],
                "sell_checks": [{"name": n, "ok": ok} for n, ok in sell_checks],
            })
        except Exception as e:
            log(f"[SNAPSHOT] Erro em {sym}: {e}")

    results.sort(key=lambda x: x["best_score"], reverse=True)
    _snapshot_cache = results
    _snapshot_ts    = time.time()
    return results


def check_near_signals(bot) -> None:
    """Alerta pares pr\u00f3ximos do score m\u00ednimo (s\u00f3 os permitidos pelo tier)."""
    from ai_validator import load_ai_params

    ai_params      = load_ai_params()
    effective_conf = ai_params.get("live_confluence", Config.MIN_CONFLUENCE)
    near_threshold = effective_conf - 2

    if not hasattr(bot, "_near_signal_cooldown"):
        bot._near_signal_cooldown = {}

    allowed_symbols = get_allowed_symbols(bot.balance)
    now             = time.time()
    snapshot        = get_confluence_snapshot()

    for item in snapshot:
        sym   = item["symbol"]
        score = item["best_score"]
        total = item["total"]
        direc = item["best_dir"]

        if sym not in allowed_symbols:
            continue
        if score < near_threshold or score >= effective_conf:
            continue

        last_alert = bot._near_signal_cooldown.get(sym, 0)
        if now - last_alert < 7200:
            continue

        checks = item["buy_checks"] if direc == "BUY" else item["sell_checks"]
        missing = [c["name"] for c in checks if not c["ok"]][:3]

        bars = "\ud83d\udfe2" * score + "\u26aa" * (total - score)
        msg = (
            f"\ud83d\udcca QUASE SINAL \u2014 {sym}\
"
            f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\
"
            f"Dire\u00e7\u00e3o: {direc} | Score: {score}/{total}\
"
            f"{bars}\
"
            f"RSI: {item['rsi']} | ADX: {item['adx']}\
"
            f"H4: {'\u2705 Alinhado' if item['h4_aligned'] else '\u274c Desalinhado'}\
\
"
            f"\u274c Falta confirmar:\
" +
            "\
".join(f"  \u2022 {m}" for m in missing) +
            f"\
\
Faltam {effective_conf - score} check(s) para virar sinal."
        )
        bot.send(msg)
        bot._near_signal_cooldown[sym] = now
        log(f"[NEAR] {sym} {direc} {score}/{total} \u2014 alerta enviado")
