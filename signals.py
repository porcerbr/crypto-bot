import time
import random
from datetime import datetime
from config import Config
from utils import log, fmt, max_leverage, get_sl_tp_atr, is_jpy_pair, is_good_session
from analysis import get_multi_timeframe
from risk import calc_margin, contract_size_for, calc_lot_for_risk
from news_filter import is_high_impact_news_window


def _is_safe_to_trade(bot, symbol):
    """
    Verificações de segurança consolidadas.
    Retorna (True, "") se seguro, ou (False, "motivo") se bloqueado.
    """
    from utils import (
        get_dynamic_max_trades, is_symbol_allowed, is_weekend_gap_risk,
        get_allowed_symbols, get_dynamic_cooldown
    )

    # 1. Verifica limite de trades ativos por banca
    max_trades = get_dynamic_max_trades(bot.balance)
    if len(bot.active_trades) >= max_trades:
        return False, f"Limite de {max_trades} trade(s) ativo(s)"

    # 2. Verifica se ativo é permitido para banca atual
    if not is_symbol_allowed(symbol, bot.balance):
        allowed = get_allowed_symbols(bot.balance)
        return False, f"Ativo bloqueado. Permitidos: {', '.join(allowed)}"

    # 3. Proteção de fim de semana / gap
    if is_weekend_gap_risk():
        return False, "Proteção de fim de semana/gap ativa"

    # 4. Cooldown dinâmico
    cooldown = get_dynamic_cooldown(bot.balance)
    if time.time() - bot.asset_cooldown.get(symbol, 0) < cooldown:
        return False, f"Cooldown ativo ({cooldown//60}min)"

    # 5. Filtro de sessão — só opera na janela de liquidez do par
    if not is_good_session(symbol):
        return False, "Fora da sessão principal"

    return True, ""


def calc_confluence(res, direction, mtf=None):
    checks = []
    price = res["price"]

    # Técnicos base
    if direction == "BUY":
        checks = [
            ("Preço > EMA200", res["price"] > res["ema200"]),
            ("EMA9 > EMA21", res["ema9"] > res["ema21"]),
            ("MACD bullish", res["macd_bull"]),
            ("RSI entre 40-65", 40 < res["rsi"] < 65),
            ("ADX > 25", res["adx"] > 25),
            ("Preço perto da banda inferior", res["price"] < res["lower"] * 1.01),
            ("Candle de força", res.get("candle_bull", True)),
        ]
    else:
        checks = [
            ("Preço < EMA200", res["price"] < res["ema200"]),
            ("EMA9 < EMA21", res["ema9"] < res["ema21"]),
            ("MACD bearish", res["macd_bear"]),
            ("RSI entre 35-60", 35 < res["rsi"] < 60),
            ("ADX > 25", res["adx"] > 25),
            ("Preço perto da banda superior", res["price"] > res["upper"] * 0.99),
            ("Candle de força", res.get("candle_bear", True)),
        ]

    # SMC
    fvg = res.get("fvg", {})
    ob = res.get("ob", {})
    sweep = res.get("sweep", {})

    if direction == "BUY":
        fvg_active = any(f.get("active") for f in fvg.get("bullish", []))
        checks.append(("FVG Bullish ativo", fvg_active))
        ob_active = any(o.get("active") for o in ob.get("bullish", []))
        checks.append(("Order Block Bullish", ob_active))
        checks.append(("Liquidity Sweep Bullish", sweep.get("bullish", False)))
        checks.append(("Estrutura intacta (acima SL)", price > sweep.get("swing_low", 0)))
    else:
        fvg_active = any(f.get("active") for f in fvg.get("bearish", []))
        checks.append(("FVG Bearish ativo", fvg_active))
        ob_active = any(o.get("active") for o in ob.get("bearish", []))
        checks.append(("Order Block Bearish", ob_active))
        checks.append(("Liquidity Sweep Bearish", sweep.get("bearish", False)))
        checks.append(("Estrutura intacta (abaixo SH)", price < sweep.get("swing_high", float('inf'))))

    # MTF
    if mtf:
        checks.append(("MTF H4 alinhado", mtf.get("aligned", False)))
        h4 = mtf.get("h4", {})
        if h4:
            if direction == "BUY":
                checks.append(("H4 > EMA200", h4.get("price", 0) > h4.get("ema200", float('inf'))))
            else:
                checks.append(("H4 < EMA200", h4.get("price", float('inf')) < h4.get("ema200", 0)))

    score = sum(1 for _, ok in checks if ok)
    passed = score >= Config.MIN_CONFLUENCE
    return score, len(checks), checks, passed, Config.MIN_CONFLUENCE

def _get_smc_sl_tp(entry, direction, res, mtf, atr):
    """
    Retorna (sl, tp, rr, sl_source, tp_source) baseado em SMC.
    sl_source/tp_source indicam o que definiu o nível ('ob', 'atr', 'liquidity', 'fvg').
    """
    sl = None
    tp = None
    sl_source = "atr"
    tp_source = "atr"

    ob = res.get("ob", {})
    sweep = res.get("sweep", {})
    fvg = res.get("fvg", {})

    # ── SL: extremo do Order Block (mais preciso) ────────────────
    if Config.USE_OB_FOR_SL:
        if direction == "BUY":
            obs = ob.get("bullish", [])
            if obs:
                # OB bullish: SL no low do OB
                best_ob = min(obs, key=lambda x: abs(x["low"] - entry))
                if best_ob["low"] < entry:
                    sl = round(best_ob["low"] - 0.5 * atr, 5)  # buffer de 0.5 ATR
                    sl_source = "ob"
        else:
            obs = ob.get("bearish", [])
            if obs:
                best_ob = min(obs, key=lambda x: abs(x["high"] - entry))
                if best_ob["high"] > entry:
                    sl = round(best_ob["high"] + 0.5 * atr, 5)
                    sl_source = "ob"

    # Se não achou OB adequado, usa ATR
    if sl is None and atr and atr > 0:
        if direction == "BUY":
            sl = round(entry - Config.ATR_SL_MULT * atr, 5)
        else:
            sl = round(entry + Config.ATR_SL_MULT * atr, 5)

    # ── TP: Liquidity Pool do H4 ou FVG ──────────────────────────
    if Config.USE_LIQUIDITY_FOR_TP and mtf:
        h4_sweep = mtf.get("h4", {}).get("sweep", {})
        if direction == "BUY" and h4_sweep.get("swing_high"):
            tp = round(h4_sweep["swing_high"], 5)
            tp_source = "liquidity"
        elif direction == "SELL" and h4_sweep.get("swing_low"):
            tp = round(h4_sweep["swing_low"], 5)
            tp_source = "liquidity"

    # Fallback para FVG do H1 se não achou liquidity H4
    if tp is None and Config.USE_FVG_FOR_TP:
        if direction == "BUY":
            fvgs = fvg.get("bullish", [])
            if fvgs:
                # Alvo no topo do FVG mais próximo acima do preço
                valid = [f for f in fvgs if f["top"] > entry]
                if valid:
                    tp = round(max(f["top"] for f in valid), 5)
                    tp_source = "fvg"
        else:
            fvgs = fvg.get("bearish", [])
            if fvgs:
                valid = [f for f in fvgs if f["bottom"] < entry]
                if valid:
                    tp = round(min(f["bottom"] for f in valid), 5)
                    tp_source = "fvg"

    # Fallback ATR
    if tp is None and atr and atr > 0:
        if direction == "BUY":
            tp = round(entry + Config.ATR_TP_MULT * atr, 5)
        else:
            tp = round(entry - Config.ATR_TP_MULT * atr, 5)

    # ── R:R dinâmico baseado em score SMC ────────────────────────
    smc_checks = sum(1 for nm, ok in [
        ("FVG", any(f.get("active") for f in (fvg.get("bullish" if direction=="BUY" else "bearish", [])))),
        ("OB", any(o.get("active") for o in (ob.get("bullish" if direction=="BUY" else "bearish", [])))),
        ("Sweep", sweep.get("bullish" if direction=="BUY" else "bearish", False)),
        ("MTF", mtf.get("aligned", False) if mtf else False),
    ] if ok)

    rr = Config.TP_SL_RATIO_BASE + (smc_checks * Config.TP_SL_RATIO_STEP)
    rr = min(rr, Config.MAX_TP_SL_RATIO)

    # Se TP foi definido por SMC, recalcula RR real
    if sl and tp and sl != entry:
        dist_sl = abs(entry - sl)
        dist_tp = abs(tp - entry)
        rr_real = round(dist_tp / dist_sl, 2) if dist_sl > 0 else rr
        # Se o SMC deu um RR melhor que o dinâmico, usa o SMC
        if rr_real > rr:
            rr = rr_real
        else:
            # Se o dinâmico é maior, ajusta TP para bater o RR dinâmico
            tp = round(entry + rr * dist_sl, 5) if direction == "BUY" else round(entry - rr * dist_sl, 5)
            tp_source = "rr_dynamic"

    return sl, tp, rr, sl_source, tp_source

def is_weekend():
    return datetime.utcnow().weekday() >= 5

def scan(bot):
    # ── Verificações globais ─────────────────────────────────────
    if bot.is_paused():
        return

    # NOVO: Verifica limite de trades por banca antes de tudo
    from utils import get_dynamic_max_trades
    max_trades = get_dynamic_max_trades(bot.balance)
    if len(bot.active_trades) >= max_trades:
        return

    if is_high_impact_news_window(minutes_before=15, minutes_after=30):
        return
    if is_weekend():
        return

    symbols = list(Config.FXGOLD_ASSETS.keys())
    random.shuffle(symbols)  # evita viés para o mesmo par toda vez

    for sym in symbols:
        # Verificações de segurança
        safe, reason = _is_safe_to_trade(bot, sym)
        if not safe:
            if reason and "Cooldown" not in reason:  # não loga cooldown toda hora
                log(f"[SAFETY] {sym}: {reason}")
            continue

        if any(t["symbol"] == sym for t in bot.active_trades + bot.pending_trades):
            continue

        mtf = get_multi_timeframe(sym)
        if not mtf or not mtf["h1"]:
            continue

        res = mtf["h1"]
        if res.get("cenario") == "NEUTRO":
            continue

        direction = "BUY" if res["cenario"] == "ALTA" else "SELL"
        sc, tot_c, checks, passed, min_sc = calc_confluence(res, direction, mtf)
        if not passed:
            continue

        entry = res["price"]
        atr = res.get("atr", 0)

        # ── SL/TP com SMC ────────────────────────────────────────────
        sl, tp, rr, sl_src, tp_src = _get_smc_sl_tp(entry, direction, res, mtf, atr)

        if not sl or not tp:
            log(f"[SMC] {sym}: SL/TP inválido, descartado")
            continue

        sl_pct = round((abs(entry - sl) / entry) * 100, 2) if entry else 0
        tp_pct = round((abs(tp - entry) / entry) * 100, 2) if entry else 0

        # ── NOVO: Alavancagem dinâmica ───────────────────────────────
        from utils import get_dynamic_leverage
        eff_lev = get_dynamic_leverage(bot.balance)

        # Turtle Position Sizing com CAP de risco
        suggested_lot, suggested_risk_usd, suggested_risk_pct = calc_lot_for_risk(
            sym, entry, sl, bot.balance,
            risk_pct=Config.ATR_RISK_PCT,
            atr=atr,
            atr_mult=Config.ATR_MULT_FOR_RISK
        )

        min_lot_margin = calc_margin(sym, entry, eff_lev, Config.MIN_LOT)

        dist_sl = abs(entry - sl)
        cs_val = contract_size_for(sym)
        risk_001_lot = dist_sl * cs_val * 0.01
        risk_pct_001 = (risk_001_lot / bot.balance) * 100 if bot.balance > 0 else 0

        # Filtro de correlação
        est_risk_usd = suggested_risk_usd
        if is_jpy_pair(sym):
            est_risk_usd = est_risk_usd / 150.0
        ok_corr, msg_corr = bot.check_correlation_exposure(sym, est_risk_usd)
        if not ok_corr:
            log(f"[CORR] {sym}: {msg_corr} — sinal descartado")
            continue

        # Validação de segurança: RR mínimo 1:1.5
        if rr < 1.5:
            log(f"[RR] {sym}: R:R {rr} muito baixo, descartado")
            continue

        pend = {
            "pending_id": bot.next_pending_id(),
            "symbol": sym,
            "name": Config.FXGOLD_ASSETS.get(sym, sym),
            "dir": direction,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "rr": rr,
            "score": sc,
            "max_score": tot_c,
            "checks": [{"name": nm, "ok": ok} for nm, ok in checks],
            "min_lot_margin": round(min_lot_margin, 2),
            "risk_001_lot": round(risk_001_lot, 2),
            "risk_pct_001": round(risk_pct_001, 2),
            "suggested_lot": suggested_lot,
            "suggested_risk_usd": suggested_risk_usd,
            "suggested_risk_pct": suggested_risk_pct,
            "created_at": datetime.now().strftime("%d/%m %H:%M"),
            "created_ts": time.time(),   # timestamp Unix para controle de expiração
            "atr": atr,
            "mtf_aligned": mtf.get("aligned", False),
            "h4_cenario": mtf.get("h4_cenario", "NEUTRO"),
            "sl_source": sl_src,
            "tp_source": tp_src,
        }
        bot.add_pending(pend)
        break
