import time
import random
from datetime import datetime
from config import Config
from utils import (log, fmt, max_leverage, get_sl_tp_atr, is_jpy_pair,
                   is_good_session, get_kill_zone, is_price_in_ote,
                   get_allowed_symbols, load_strategy_settings)
from analysis import get_multi_timeframe
from risk import calc_margin, contract_size_for, calc_lot_for_risk
from news_filter import is_high_impact_news_window

# Cache do snapshot de confluência
_SNAPSHOT_TTL = 600  # 10 minutos
_snapshot_cache = []
_snapshot_ts = 0.0


def _is_safe_to_trade(bot, symbol):
    """
    Verificações de segurança consolidadas.
    Retorna (True, "") se seguro, ou (False, "motivo") se bloqueado.
    """
    from utils import (
        get_dynamic_max_trades, is_symbol_allowed, is_weekend_gap_risk,
        get_allowed_symbols, get_dynamic_cooldown
    )

    # 1. Verifica se ativo está habilitado na seleção do bot
    if not is_symbol_allowed(symbol, bot.balance):
        allowed = get_allowed_symbols(bot.balance)
        return False, f"Ativo bloqueado. Permitidos: {', '.join(allowed)}"

    # 2. Proteção de fim de semana / gap
    if is_weekend_gap_risk():
        return False, "Proteção de fim de semana/gap ativa"

    # 3. Cooldown dinâmico
    cooldown = get_dynamic_cooldown(bot.balance)
    if time.time() - bot.asset_cooldown.get(symbol, 0) < cooldown:
        return False, f"Cooldown ativo ({cooldown//60}min)"

    # 4. Filtro de sessão — só opera na janela de liquidez do par
    if not is_good_session(symbol):
        return False, "Fora da sessão principal"

    # 5. Horas a evitar definidas pelo Opus (aprendizado mensal)
    from ai_validator import load_ai_params
    avoid_hours = load_ai_params().get("avoid_hours_utc", [])
    if avoid_hours and datetime.utcnow().hour in avoid_hours:
        return False, f"Hora bloqueada pelo Opus ({datetime.utcnow().hour}h UTC)"

    return True, ""




def _market_regime(res: dict, mtf: dict | None = None) -> str:
    """Classifica o mercado para adaptar o tipo de setup."""
    h1_adx = float(res.get("adx", 0) or 0)
    aligned = bool(mtf.get("aligned", False)) if mtf else False
    daily_bias = (mtf.get("daily_bias", "NEUTRO") if mtf else "NEUTRO")
    h4 = mtf.get("h4") if mtf else None
    h4_adx = float(h4.get("adx", 0) or 0) if h4 else 0

    if h1_adx >= Config.REGIME_ADX_TRENDING and aligned and daily_bias != "NEUTRO":
        return "trend"
    if h1_adx <= Config.REGIME_ADX_RANGING:
        return "range"
    if 18 < h1_adx < Config.REGIME_ADX_TRENDING:
        return "transition"
    if h4_adx >= Config.REGIME_ADX_STRONG and daily_bias != "NEUTRO":
        return "trend"
    return "neutral"


def _setup_for_regime(regime: str, direction: str) -> str:
    if regime == "trend":
        return "pullback"
    if regime == "range":
        return "reversal"
    if regime == "transition":
        return "breakout"
    return "wait"


def calc_confluence(res, direction, mtf=None):
    """
    Confluência com pesos e lógica por regime.
    Retorna: score, max_score, checks, passed, min_score, meta
    """
    regime = _market_regime(res, mtf)
    setup_type = _setup_for_regime(regime, direction)
    checks = []
    weighted = []
    price = res["price"]

    def add(name: str, ok: bool, weight: int = 1):
        checks.append((name, bool(ok)))
        weighted.append((name, bool(ok), int(weight)))

    fvg = res.get("fvg", {}) or {}
    ob = res.get("ob", {}) or {}
    sweep = res.get("sweep", {}) or {}
    h4 = mtf.get("h4", {}) if mtf else {}
    daily_bias = mtf.get("daily_bias", "NEUTRO") if mtf else "NEUTRO"
    aligned = bool(mtf.get("aligned", False)) if mtf else False

    if regime in ("trend", "transition", "neutral"):
        if direction == "BUY":
            add("Preço > EMA200", price > res["ema200"], Config.CONFLUENCE_WEIGHTS.get("ema200", 2))
            add("EMA9 > EMA21", res["ema9"] > res["ema21"], Config.CONFLUENCE_WEIGHTS.get("ema9_21", 1))
            add("MACD bullish", res["macd_bull"], Config.CONFLUENCE_WEIGHTS.get("macd", 1))
            add("RSI favorável", 40 < res["rsi"] < 68, Config.CONFLUENCE_WEIGHTS.get("rsi", 1))
            add("ADX forte", res["adx"] >= Config.REGIME_ADX_TRENDING, Config.CONFLUENCE_WEIGHTS.get("adx", 2))
            add("Preço na zona baixa", price < res["lower"] * 1.01, Config.CONFLUENCE_WEIGHTS.get("bands", 1))
            add("Candle de força", res.get("candle_bull", True), Config.CONFLUENCE_WEIGHTS.get("candle", 1))
            add("FVG ativo", any(f.get("active") for f in fvg.get("bullish", [])), Config.CONFLUENCE_WEIGHTS.get("fvg", 3))
            add("OB ativo", any(o.get("active") for o in ob.get("bullish", [])), Config.CONFLUENCE_WEIGHTS.get("ob", 3))
            add("Sweep de liquidez", sweep.get("bullish", False), Config.CONFLUENCE_WEIGHTS.get("sweep", 2))
            add("Estrutura limpa", price > sweep.get("swing_low", 0), Config.CONFLUENCE_WEIGHTS.get("structure", 1))
            add("H4 alinhado", aligned, Config.CONFLUENCE_WEIGHTS.get("mtf_aligned", 2))
            add("H4 > EMA200", h4.get("price", 0) > h4.get("ema200", float('inf')), Config.CONFLUENCE_WEIGHTS.get("mtf_ema200", 1))
            add("Daily Bias ALTA", daily_bias == "ALTA", 2)
        else:
            add("Preço < EMA200", price < res["ema200"], Config.CONFLUENCE_WEIGHTS.get("ema200", 2))
            add("EMA9 < EMA21", res["ema9"] < res["ema21"], Config.CONFLUENCE_WEIGHTS.get("ema9_21", 1))
            add("MACD bearish", res["macd_bear"], Config.CONFLUENCE_WEIGHTS.get("macd", 1))
            add("RSI favorável", 32 < res["rsi"] < 60, Config.CONFLUENCE_WEIGHTS.get("rsi", 1))
            add("ADX forte", res["adx"] >= Config.REGIME_ADX_TRENDING, Config.CONFLUENCE_WEIGHTS.get("adx", 2))
            add("Preço na zona alta", price > res["upper"] * 0.99, Config.CONFLUENCE_WEIGHTS.get("bands", 1))
            add("Candle de força", res.get("candle_bear", True), Config.CONFLUENCE_WEIGHTS.get("candle", 1))
            add("FVG ativo", any(f.get("active") for f in fvg.get("bearish", [])), Config.CONFLUENCE_WEIGHTS.get("fvg", 3))
            add("OB ativo", any(o.get("active") for o in ob.get("bearish", [])), Config.CONFLUENCE_WEIGHTS.get("ob", 3))
            add("Sweep de liquidez", sweep.get("bearish", False), Config.CONFLUENCE_WEIGHTS.get("sweep", 2))
            add("Estrutura limpa", price < sweep.get("swing_high", float('inf')), Config.CONFLUENCE_WEIGHTS.get("structure", 1))
            add("H4 alinhado", aligned, Config.CONFLUENCE_WEIGHTS.get("mtf_aligned", 2))
            add("H4 < EMA200", h4.get("price", float('inf')) < h4.get("ema200", 0), Config.CONFLUENCE_WEIGHTS.get("mtf_ema200", 1))
            add("Daily Bias BAIXA", daily_bias == "BAIXA", 2)

        sym = res.get("symbol", "")
        kill_zone = get_kill_zone(sym)
        add(f"Kill Zone ({kill_zone or 'fora'})", kill_zone is not None, 1)

        sh = sweep.get("swing_high")
        sl_sw = sweep.get("swing_low")
        ote_ok = is_price_in_ote(price, sh, sl_sw, direction) if sh and sl_sw else False
        add("OTE Fibonacci (62-79%)", ote_ok, 2)

    elif regime == "range":
        if direction == "BUY":
            add("RSI sobrevenda", res["rsi"] <= 40, 2)
            add("Preço abaixo da média", price <= res["ema21"], 1)
            add("Banda inferior tocada", price <= res["lower"] * 1.01, 2)
            add("Sweep de fundo", sweep.get("bullish", False), 3)
            add("FVG/OB de reversão", any(f.get("active") for f in fvg.get("bullish", [])) or any(o.get("active") for o in ob.get("bullish", [])), 3)
            add("Candle de reversão", res.get("candle_bull", False), 1)
            add("Daily Bias ALTA", daily_bias in ("ALTA", "NEUTRO"), 1)
        else:
            add("RSI sobrecompra", res["rsi"] >= 60, 2)
            add("Preço acima da média", price >= res["ema21"], 1)
            add("Banda superior tocada", price >= res["upper"] * 0.99, 2)
            add("Sweep de topo", sweep.get("bearish", False), 3)
            add("FVG/OB de reversão", any(f.get("active") for f in fvg.get("bearish", [])) or any(o.get("active") for o in ob.get("bearish", [])), 3)
            add("Candle de reversão", res.get("candle_bear", False), 1)
            add("Daily Bias BAIXA", daily_bias in ("BAIXA", "NEUTRO"), 1)
        add("H4 não oposto", daily_bias != ("BAIXA" if direction == "BUY" else "ALTA"), 2)
        add("Kill Zone", get_kill_zone(res.get("symbol", "")) is not None, 1)

    score = sum(weight for _, ok, weight in weighted if ok)
    total = sum(weight for _, _, weight in weighted)

    min_score = Config.REGIME_MIN_CONFLUENCE.get(regime, Config.MIN_CONFLUENCE)
    if setup_type in ("pullback", "reversal"):
        min_score = max(1, min_score - 1)
    if regime == "trend" and aligned:
        min_score = max(1, min_score - Config.PREMIUM_SETUP_BONUS)

    passed = score >= min_score
    meta = {"regime": regime, "setup_type": setup_type}
    return score, total, checks, passed, min_score, meta

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
                candidate = round(best_ob["low"] - 0.8 * atr, 5)
                if candidate < entry:   # SL DEVE estar abaixo da entrada no BUY
                    sl = candidate
                    sl_source = "ob"
        else:
            obs = ob.get("bearish", [])
            if obs:
                best_ob = min(obs, key=lambda x: abs(x["high"] - entry))
                candidate = round(best_ob["high"] + 0.8 * atr, 5)
                if candidate > entry:   # SL DEVE estar acima da entrada no SELL
                    sl = candidate
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
        if direction == "BUY":
            swing_high = h4_sweep.get("swing_high")
            # TP deve estar ACIMA da entrada e dentro de distância razoável (max MAX_TP_SL_RATIO * ATR_TP_MULT * atr)
            max_tp_dist = Config.MAX_TP_SL_RATIO * Config.ATR_TP_MULT * atr if atr > 0 else entry * 0.05
            if swing_high and swing_high > entry and (swing_high - entry) <= max_tp_dist:
                tp = round(swing_high, 5)
                tp_source = "liquidity"
        elif direction == "SELL":
            swing_low = h4_sweep.get("swing_low")
            max_tp_dist = Config.MAX_TP_SL_RATIO * Config.ATR_TP_MULT * atr if atr > 0 else entry * 0.05
            if swing_low and swing_low < entry and (entry - swing_low) <= max_tp_dist:
                tp = round(swing_low, 5)
                tp_source = "liquidity"

    # Fallback para FVG do H1 se não achou liquidity H4
    if tp is None and Config.USE_FVG_FOR_TP:
        if direction == "BUY":
            fvgs = fvg.get("bullish", [])
            if fvgs:
                # Alvo no topo do FVG mais próximo ACIMA do preço (min, não max)
                valid = [f for f in fvgs if f["top"] > entry]
                if valid:
                    tp = round(min(f["top"] for f in valid), 5)
                    tp_source = "fvg"
        else:
            fvgs = fvg.get("bearish", [])
            if fvgs:
                # Alvo no fundo do FVG mais próximo ABAIXO do preço (max, não min)
                valid = [f for f in fvgs if f["bottom"] < entry]
                if valid:
                    tp = round(max(f["bottom"] for f in valid), 5)
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

    # Se TP foi definido por SMC, recalcula RR real e valida
    if sl and tp and sl != entry:
        dist_sl = abs(entry - sl)
        dist_tp = abs(tp - entry)
        rr_real = round(dist_tp / dist_sl, 2) if dist_sl > 0 else rr

        if rr_real > Config.MAX_TP_SL_RATIO:
            # Alvo SMC absurdamente longe — recalcula TP com RR máximo permitido
            tp = round(entry + Config.MAX_TP_SL_RATIO * dist_sl, 5) if direction == "BUY" \
                 else round(entry - Config.MAX_TP_SL_RATIO * dist_sl, 5)
            rr = Config.MAX_TP_SL_RATIO
            tp_source = "rr_capped"
        elif rr_real > rr:
            # SMC deu RR melhor que o dinâmico, mas dentro do limite — aceita
            rr = rr_real
        else:
            # Dinâmico é maior — ajusta TP para bater o RR dinâmico
            tp = round(entry + rr * dist_sl, 5) if direction == "BUY" \
                 else round(entry - rr * dist_sl, 5)
            tp_source = "rr_dynamic"

    return sl, tp, rr, sl_source, tp_source

def is_weekend():
    return datetime.utcnow().weekday() >= 5


def scan(bot):
    # ── Verificações globais ─────────────────────────────────────
    if bot.is_paused():
        return

    weekend = is_weekend()
    if weekend:
        return

    symbols = list(get_allowed_symbols(bot.balance))
    random.shuffle(symbols)

    for sym in symbols:
        safe, reason = _is_safe_to_trade(bot, sym)
        if not safe:
            if reason and "Cooldown" not in reason:
                log(f"[SAFETY] {sym}: {reason}")
            continue

        mtf = get_multi_timeframe(sym)
        if not mtf or not mtf["h1"]:
            continue

        res = mtf["h1"]
        if res.get("cenario") == "NEUTRO":
            continue

        direction = res.get("dir") or res.get("direction") or ("BUY" if res["cenario"] == "ALTA" else "SELL")
        sc, tot_c, checks, passed, min_sc, meta = calc_confluence(res, direction, mtf)
        if not passed:
            continue

        entry = res["price"]
        atr = res.get("atr", 0)

        sl, tp, rr, sl_src, tp_src = _get_smc_sl_tp(entry, direction, res, mtf, atr)
        if not sl or not tp:
            log(f"[SMC] {sym}: SL/TP inválido, descartado")
            continue

        # ── Validação de sanidade dos SL/TP ──────────────────────────
        if direction == "BUY":
            if sl >= entry:
                log(f"[SLTP] {sym}: SL ({sl:.5f}) >= entrada ({entry:.5f}) — descartado")
                continue
            if tp <= entry:
                log(f"[SLTP] {sym}: TP ({tp:.5f}) <= entrada ({entry:.5f}) — descartado")
                continue
        else:
            if sl <= entry:
                log(f"[SLTP] {sym}: SL ({sl:.5f}) <= entrada ({entry:.5f}) — descartado")
                continue
            if tp >= entry:
                log(f"[SLTP] {sym}: TP ({tp:.5f}) >= entrada ({entry:.5f}) — descartado")
                continue

        # Distância máxima razoável: 10% do preço
        max_dist = entry * 0.10
        if abs(tp - entry) > max_dist or abs(sl - entry) > max_dist:
            log(f"[SLTP] {sym}: SL/TP fora dos limites razoáveis (>10% do preço) — entry={entry:.5f}, sl={sl:.5f}, tp={tp:.5f}")
            continue

        sl_pct = round((abs(entry - sl) / entry) * 100, 2) if entry else 0
        tp_pct = round((abs(tp - entry) / entry) * 100, 2) if entry else 0

        if is_jpy_pair(sym):
            pip_factor = 0.01
        elif sym == "XAUUSD":
            pip_factor = 0.01
        else:
            pip_factor = 0.0001
        sl_pips = round(abs(entry - sl) / pip_factor)
        tp_pips = round(abs(tp  - entry) / pip_factor)

        from utils import get_dynamic_leverage
        eff_lev = get_dynamic_leverage(bot.balance)

        # Carrega a estratégia antes de usar qualquer parâmetro dela
        strategy = load_strategy_settings()

        suggested_lot, suggested_risk_usd, suggested_risk_pct = calc_lot_for_risk(
            sym, entry, sl, bot.balance,
            risk_pct=float(strategy.get("risk_pct", Config.ATR_RISK_PCT)),
            atr=atr,
            atr_mult=Config.ATR_MULT_FOR_RISK
        )

        min_lot_margin = calc_margin(sym, entry, eff_lev, Config.MIN_LOT)
        dist_sl = abs(entry - sl)
        cs_val  = contract_size_for(sym)

        if is_jpy_pair(sym) and entry > 0:
            risk_001_lot = (dist_sl * cs_val * 0.01) / entry
        else:
            risk_001_lot = dist_sl * cs_val * 0.01
        risk_pct_001 = (risk_001_lot / bot.balance) * 100 if bot.balance > 0 else 0

        est_risk_usd = suggested_risk_usd
        ok_corr, msg_corr = bot.check_correlation_exposure(sym, est_risk_usd)
        if not ok_corr:
            log(f"[CORR] {sym}: {msg_corr} — sinal descartado")
            continue

        from ai_validator import load_ai_params, validate_signal
        ai_params  = load_ai_params()
        min_rr     = max(float(ai_params.get("min_rr", 1.5)), float(strategy.get("min_rr", 1.8)))

        base_conf = max(int(ai_params.get("min_confluence", Config.MIN_CONFLUENCE)), int(strategy.get("min_confluence", Config.MIN_CONFLUENCE)))
        bias      = ai_params.get("strategy_bias", "balanced")
        regime    = meta.get("regime", ai_params.get("live_regime", "neutral"))
        setup_type = meta.get("setup_type", "wait")
        regime_base = Config.REGIME_MIN_CONFLUENCE.get(regime, base_conf)

        if bias == "conservative":
            bias_adj = 1
        elif bias == "aggressive":
            bias_adj = -1
        else:
            bias_adj = 0

        live_conf = ai_params.get("live_confluence", regime_base)
        effective_min_conf = max(regime_base, live_conf + bias_adj)

        news_window = is_high_impact_news_window(minutes_before=15, minutes_after=30, symbol=sym)
        if news_window:
            effective_min_conf = max(effective_min_conf - 1, 1)

        if sc < effective_min_conf:
            log(f"[CONF] {sym}: score {sc} < mínimo {effective_min_conf} (regime={regime}, setup={setup_type}, bias={bias}), descartado")
            continue

        min_rr_regime = Config.REGIME_MIN_RR.get(regime, min_rr)
        effective_min_rr = max(min_rr, min_rr_regime)
        if rr < effective_min_rr:
            log(f"[RR] {sym}: R:R {rr} abaixo do mínimo {effective_min_rr}, descartado")
            continue

        check_map = {name: ok for name, ok in checks}

        if regime in ("trend", "transition"):
            has_fvg = check_map.get("FVG ativo", False)
            has_ob  = check_map.get("OB ativo", False)
            has_h4  = check_map.get("H4 alinhado", False)
            has_daily = check_map.get("Daily Bias ALTA" if direction == "BUY" else "Daily Bias BAIXA", False)
            # Para regimes tendenciais, dois pilares confirmados já bastam.
            quality = (has_fvg or has_ob) and has_h4 and (has_daily or sc >= effective_min_conf + 1)
        else:
            sweep_ok = check_map.get("Sweep de fundo" if direction == "BUY" else "Sweep de topo", False)
            band_ok  = check_map.get("Banda inferior tocada" if direction == "BUY" else "Banda superior tocada", False)
            rsi_ok   = check_map.get("RSI sobrevenda" if direction == "BUY" else "RSI sobrecompra", False)
            # Em range, um sweep + qualquer 1 confirmação adicional já é suficiente.
            quality  = sweep_ok and (band_ok or rsi_ok)

        if not quality:
            log(f"[SETUP] {sym} {direction}: setup {regime}/{setup_type} não atingiu a qualidade mínima")
            continue

        if sym in ai_params.get("blocked_pairs", []):
            log(f"[AI] {sym} bloqueado por aprendizado — WR histórico muito baixo")
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
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
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
            "created_ts": time.time(),
            "atr": atr,
            "mtf_aligned": mtf.get("aligned", False),
            "h4_cenario": mtf.get("h4_cenario", "NEUTRO"),
            "daily_bias": mtf.get("daily_bias", "NEUTRO"),
            "kill_zone": get_kill_zone(sym),
            "ote_active": check_map.get("OTE Fibonacci (62-79%)", False),
            "sl_source": sl_src,
            "tp_source": tp_src,
            "market_regime": regime,
            "setup_type": setup_type,
        }

        # ── IA: pontua o sinal (NÃO bloqueia — apenas informa) ──
        _, ai_reason = validate_signal(pend, mtf, bot)

        # Extrai score numérico do texto retornado pela IA (ex: "7/10: ...")
        ai_confidence = 0
        try:
            import re as _re
            m = _re.search(r'(\d+)/10', ai_reason)
            if m:
                ai_confidence = int(m.group(1))
        except Exception:
            pass

        pend["ai_reason"]     = ai_reason
        pend["ai_approved"]   = True
        pend["ai_confidence"] = ai_confidence

        score_ratio = sc / max(1, tot_c)
        base_quality = max(1, min(10, round(score_ratio * 10)))
        if ai_confidence > 0:
            pend["signal_quality"] = max(1, min(10, round((base_quality * 0.7) + (ai_confidence * 0.3))))
        else:
            pend["signal_quality"] = base_quality

        # Executa sinal automaticamente — sem confirmação manual
        ok = bot.execute_signal(pend)
        if ok:
            log(f"[SIGNAL] {sym} {direction} executado automaticamente (IA conf={ai_confidence}/10)")
        # Não dá break — continua varrendo todos os símbolos
def get_confluence_snapshot() -> list[dict]:
    """
    Varre todos os pares e retorna o score de confluência atual.
    Resultado é cacheado por 10 minutos para não sobrecarregar o loop.
    """
    global _snapshot_cache, _snapshot_ts

    # Proteção extra contra reload parcial / estado incompleto do módulo
    if "_snapshot_cache" not in globals():
        _snapshot_cache = []
    if "_snapshot_ts" not in globals():
        _snapshot_ts = 0.0

    if time.time() - _snapshot_ts < _SNAPSHOT_TTL and _snapshot_cache:
        return _snapshot_cache

    results = []
    for sym in Config.FXGOLD_ASSETS:
        try:
            mtf = get_multi_timeframe(sym)
            h1  = mtf.get("h1")
            if not h1:
                continue

            buy_sc,  buy_tot,  buy_checks,  _, _, buy_meta = calc_confluence(h1, "BUY",  mtf)
            sell_sc, sell_tot, sell_checks, _, _, sell_meta = calc_confluence(h1, "SELL", mtf)

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
                "market_regime": buy_meta.get("regime", "neutral"),
                "buy_setup":   buy_meta.get("setup_type", "wait"),
                "sell_setup":  sell_meta.get("setup_type", "wait"),
                "buy_checks":  buy_checks,
                "sell_checks": sell_checks,
            })
        except Exception as e:
            log(f"[SNAPSHOT] Erro em {sym}: {e}")
            continue

    results.sort(key=lambda x: x["best_score"], reverse=True)
    _snapshot_cache = results
    _snapshot_ts    = time.time()
    return results


def check_near_signals(bot) -> None:
    """
    Verifica se algum par PERMITIDO está com score próximo do mínimo.
    Só alerta pares que o bot pode realmente operar com o saldo atual.
    """
    from ai_validator import load_ai_params
    from utils import get_allowed_symbols

    ai_params      = load_ai_params()
    effective_conf = ai_params.get("live_confluence", Config.MIN_CONFLUENCE)
    NEAR_THRESHOLD = effective_conf - 2

    if not hasattr(bot, "_near_signal_cooldown"):
        bot._near_signal_cooldown = {}

    # Só pares liberados pelo nível de capital atual
    allowed_symbols = get_allowed_symbols(bot.balance)
    now             = time.time()
    snapshot        = get_confluence_snapshot()

    for item in snapshot:
        sym   = item["symbol"]
        score = item["best_score"]
        total = item["total"]
        direction = item.get("best_dir") or item.get("direction") or item.get("dir") or "—"

        # Ignora pares bloqueados pelo SAFETY
        if sym not in allowed_symbols:
            continue

        if score < NEAR_THRESHOLD or score >= effective_conf:
            continue

        last_alert = bot._near_signal_cooldown.get(sym, 0)
        if now - last_alert < 7200:
            continue

        checks  = item["buy_checks"] if direction == "BUY" else item["sell_checks"]
        missing = [name for name, ok in checks if not ok][:3]

        bars = "🟢" * score + "⚪" * (total - score)
        msg  = (
            f"📊 QUASE SINAL — {sym}\n"
            f"——————————————\n"
            f"Direção: {direction} | Score: {score}/{total}\n"
            f"{bars}\n"
            f"RSI: {item['rsi']} | ADX: {item['adx']}\n"
            f"H4: {'✅ Alinhado' if item['h4_aligned'] else '❌ Desalinhado'}\n\n"
            f"❌ Falta confirmar:\n" +
            "\n".join(f"  • {m}" for m in missing) +
            f"\n\nFaltam {effective_conf - score} check(s) para virar sinal."
        )
        bot.send(msg)
        bot._near_signal_cooldown[sym] = now
        log(f"[NEAR] {sym} {direction} {score}/{total} — alerta enviado")
