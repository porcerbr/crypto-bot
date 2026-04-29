
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from analysis import get_multi_timeframe
from config import Config
from news_filter import is_high_impact_news_window
from risk import calc_lot_for_risk, calc_margin, contract_size_for
from utils import (
    get_allowed_symbols,
    get_dynamic_cooldown,
    get_dynamic_leverage,
    get_dynamic_max_trades,
    is_good_session,
    is_jpy_pair,
    is_symbol_allowed,
    is_weekend_gap_risk,
    log,
    pip_factor,
)


# =============================================================================
# SAFETY CHECK
# =============================================================================

def _is_safe_to_trade(bot, symbol: str) -> tuple[bool, str]:
    """Retorna (True, "") se seguro, ou (False, "motivo") se bloqueado."""
    if hasattr(bot, "is_risk_off") and bot.is_risk_off():
        return False, bot.risk_off_reason()

    max_trades = get_dynamic_max_trades(bot.balance)
    if len(bot.active_trades) >= max_trades:
        return False, f"Limite de {max_trades} trade(s) ativo(s)"

    if not is_symbol_allowed(symbol, bot.balance):
        allowed = get_allowed_symbols(bot.balance)
        return False, f"Ativo bloqueado. Permitidos: {', '.join(allowed)}"

    if is_weekend_gap_risk():
        return False, "Proteção de fim de semana/gap ativa"

    cooldown = get_dynamic_cooldown(bot.balance)
    last_loss_ts = bot.asset_cooldown.get(symbol, 0)
    if time.time() < last_loss_ts:
        return False, f"Cooldown ativo ({cooldown // 60}min)"

    if not is_good_session(symbol):
        return False, "Fora da sessão principal"

    from ai_validator import load_ai_params

    ai_params = load_ai_params()
    avoid_hours = ai_params.get("avoid_hours_utc", [])
    current_hour = datetime.now(timezone.utc).hour

    if avoid_hours and current_hour in avoid_hours:
        return False, f"Hora bloqueada pela IA ({current_hour}h UTC)"

    if symbol in ai_params.get("blocked_pairs", []):
        return False, "Par bloqueado pela IA (WR baixo)"

    return True, ""


# =============================================================================
# CONFLUÊNCIA
# =============================================================================

def _append(checks: list, name: str, ok: bool, weight: int):
    checks.append((name, bool(ok), int(weight)))


def _normalized_score(checks: list[tuple[str, bool, int]]) -> tuple[int, int]:
    total_weight = sum(max(1, int(w)) for _, _, w in checks) or 1
    weighted = sum(int(w) for _, ok, w in checks if ok)
    normalized = round((weighted / total_weight) * 10)
    return int(normalized), 10


def calc_confluence(res: dict, direction: str, mtf: dict = None) -> tuple[int, int, list, bool, int]:
    """
    Calcula score de confluência.
    Retorna (score_0_10, total_10, checks, passed, min_required).
    """
    direction = (direction or "BUY").upper()
    if direction not in {"BUY", "SELL"}:
        direction = "BUY"

    price = float(res.get("price", 0) or 0)
    ema200 = float(res.get("ema200", price) or price)
    ema9 = float(res.get("ema9", price) or price)
    ema21 = float(res.get("ema21", price) or price)
    rsi = float(res.get("rsi", 50) or 50)
    adx = float(res.get("adx", 0) or 0)
    lower = float(res.get("lower", price) or price)
    upper = float(res.get("upper", price) or price)

    weights = getattr(Config, "CONFLUENCE_WEIGHTS", {})
    checks: list[tuple[str, bool, int]] = []

    if direction == "BUY":
        _append(checks, "Preço > EMA200", price > ema200, weights.get("ema200", 2))
        _append(checks, "EMA9 > EMA21", ema9 > ema21, weights.get("ema9_21", 1))
        _append(checks, "MACD bullish", bool(res.get("macd_bull")), weights.get("macd", 1))
        _append(checks, "RSI entre 40-65", 40 < rsi < 65, weights.get("rsi", 1))
        _append(checks, "ADX > 25", adx > 25, weights.get("adx", 2))
        _append(checks, "Preço perto da banda inferior", price < lower * 1.01, weights.get("bands", 1))
        _append(checks, "Candle de força", bool(res.get("candle_bull", False)), weights.get("candle", 1))
    else:
        _append(checks, "Preço < EMA200", price < ema200, weights.get("ema200", 2))
        _append(checks, "EMA9 < EMA21", ema9 < ema21, weights.get("ema9_21", 1))
        _append(checks, "MACD bearish", bool(res.get("macd_bear")), weights.get("macd", 1))
        _append(checks, "RSI entre 35-60", 35 < rsi < 60, weights.get("rsi", 1))
        _append(checks, "ADX > 25", adx > 25, weights.get("adx", 2))
        _append(checks, "Preço perto da banda superior", price > upper * 0.99, weights.get("bands", 1))
        _append(checks, "Candle de força", bool(res.get("candle_bear", False)), weights.get("candle", 1))

    fvg = res.get("fvg", {}) or {}
    ob = res.get("ob", {}) or {}
    sweep = res.get("sweep", {}) or {}

    if direction == "BUY":
        fvg_active = any(f.get("active") for f in fvg.get("bullish", []))
        ob_active = any(o.get("active") for o in ob.get("bullish", []))
        swing_low = sweep.get("swing_low")
        structure_ok = swing_low is not None and price > float(swing_low)
        _append(checks, "FVG Bullish ativo", fvg_active, weights.get("fvg", 3))
        _append(checks, "Order Block Bullish", ob_active, weights.get("ob", 3))
        _append(checks, "Liquidity Sweep Bullish", bool(sweep.get("bullish")), weights.get("sweep", 2))
        _append(checks, "Estrutura intacta", structure_ok, weights.get("structure", 1))
    else:
        fvg_active = any(f.get("active") for f in fvg.get("bearish", []))
        ob_active = any(o.get("active") for o in ob.get("bearish", []))
        swing_high = sweep.get("swing_high")
        structure_ok = swing_high is not None and price < float(swing_high)
        _append(checks, "FVG Bearish ativo", fvg_active, weights.get("fvg", 3))
        _append(checks, "Order Block Bearish", ob_active, weights.get("ob", 3))
        _append(checks, "Liquidity Sweep Bearish", bool(sweep.get("bearish")), weights.get("sweep", 2))
        _append(checks, "Estrutura intacta", structure_ok, weights.get("structure", 1))

    if mtf:
        h4 = mtf.get("h4", {}) or {}
        aligned = bool(mtf.get("aligned", False))
        _append(checks, "MTF H4 alinhado", aligned, weights.get("mtf_aligned", 2))
        if h4:
            h4_price = float(h4.get("price", price) or price)
            h4_ema200 = float(h4.get("ema200", h4_price) or h4_price)
            if direction == "BUY":
                _append(checks, "H4 > EMA200", h4_price > h4_ema200, weights.get("mtf_ema200", 1))
            else:
                _append(checks, "H4 < EMA200", h4_price < h4_ema200, weights.get("mtf_ema200", 1))

    total_weight = sum(max(1, int(w)) for _, _, w in checks) or 1
    weighted = sum(int(w) for _, ok, w in checks if ok)
    score = round((weighted / total_weight) * 10)
    min_required = int(getattr(Config, "MIN_CONFLUENCE_WEIGHTED", 10))
    passed = weighted >= min_required and score >= int(getattr(Config, "MIN_CONFLUENCE", 6))
    return int(score), 10, [(name, ok) for name, ok, _ in checks], passed, min_required

# =============================================================================
# SMC SL/TP
# =============================================================================
# SMC SL/TP
# =============================================================================

def _get_smc_sl_tp(entry: float, direction: str, res: dict, mtf: dict, atr: float):
    """
    Retorna (sl, tp, rr, sl_source, tp_source).
    """
    direction = (direction or "BUY").upper()
    if direction not in {"BUY", "SELL"}:
        direction = "BUY"

    entry = float(entry or 0)
    atr = float(atr or 0)

    sl = None
    tp = None
    sl_source = "atr"
    tp_source = "atr"

    ob = res.get("ob", {}) or {}
    sweep = res.get("sweep", {}) or {}
    fvg = res.get("fvg", {}) or {}

    if getattr(Config, "USE_OB_FOR_SL", True):
        if direction == "BUY":
            obs = ob.get("bullish", [])
            if obs:
                best_ob = min(obs, key=lambda x: abs(float(x.get("low", entry)) - entry))
                ob_low = float(best_ob.get("low", entry))
                if ob_low < entry:
                    buffer = 0.5 * atr if atr > 0 else abs(entry - ob_low) * 0.1
                    sl = round(ob_low - buffer, 5)
                    sl_source = "ob"
        else:
            obs = ob.get("bearish", [])
            if obs:
                best_ob = min(obs, key=lambda x: abs(float(x.get("high", entry)) - entry))
                ob_high = float(best_ob.get("high", entry))
                if ob_high > entry:
                    buffer = 0.5 * atr if atr > 0 else abs(ob_high - entry) * 0.1
                    sl = round(ob_high + buffer, 5)
                    sl_source = "ob"

    if sl is None:
        if atr > 0:
            if direction == "BUY":
                sl = round(entry - getattr(Config, "ATR_SL_MULT", 1.5) * atr, 5)
            else:
                sl = round(entry + getattr(Config, "ATR_SL_MULT", 1.5) * atr, 5)
        else:
            sl = round(entry * (0.995 if direction == "BUY" else 1.005), 5)

    if getattr(Config, "USE_LIQUIDITY_FOR_TP", True) and mtf:
        h4_sweep = (mtf.get("h4") or {}).get("sweep", {}) or {}
        if direction == "BUY" and h4_sweep.get("swing_high"):
            tp = round(float(h4_sweep["swing_high"]), 5)
            tp_source = "liquidity"
        elif direction == "SELL" and h4_sweep.get("swing_low"):
            tp = round(float(h4_sweep["swing_low"]), 5)
            tp_source = "liquidity"

    if tp is None and getattr(Config, "USE_FVG_FOR_TP", True):
        if direction == "BUY":
            valid = [f for f in fvg.get("bullish", []) if float(f.get("top", entry)) > entry]
            if valid:
                tp = round(max(float(f["top"]) for f in valid), 5)
                tp_source = "fvg"
        else:
            valid = [f for f in fvg.get("bearish", []) if float(f.get("bottom", entry)) < entry]
            if valid:
                tp = round(min(float(f["bottom"]) for f in valid), 5)
                tp_source = "fvg"

    if tp is None:
        if atr > 0:
            if direction == "BUY":
                tp = round(entry + getattr(Config, "ATR_TP_MULT", 2.5) * atr, 5)
            else:
                tp = round(entry - getattr(Config, "ATR_TP_MULT", 2.5) * atr, 5)
        else:
            tp = round(entry * (1.01 if direction == "BUY" else 0.99), 5)

    side = "bullish" if direction == "BUY" else "bearish"
    smc_checks = sum(
        1
        for ok in [
            any(f.get("active") for f in fvg.get(side, [])),
            any(o.get("active") for o in ob.get(side, [])),
            bool(sweep.get(side)),
            bool(mtf.get("aligned") if mtf else False),
        ]
        if ok
    )

    rr_target = getattr(Config, "TP_SL_RATIO_BASE", 2.5) + (smc_checks * getattr(Config, "TP_SL_RATIO_STEP", 0.5))
    rr_target = min(rr_target, getattr(Config, "MAX_TP_SL_RATIO", 4.5))

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

    if rr_target > rr_real:
        if direction == "BUY":
            tp = round(entry + rr_target * dist_sl, 5)
        else:
            tp = round(entry - rr_target * dist_sl, 5)
        tp_source = "rr_dynamic"
        rr_real = rr_target

    return sl, tp, rr_real, sl_source, tp_source


# =============================================================================
# SCAN PRINCIPAL
# =============================================================================

def scan(bot):
    if bot.is_paused():
        return

    if hasattr(bot, "is_risk_off") and bot.is_risk_off():
        log(f"[RISK] {bot.risk_off_reason()}")
        return

    max_trades = get_dynamic_max_trades(bot.balance)
    if len(bot.active_trades) >= max_trades:
        return

    if is_high_impact_news_window(minutes_before=15, minutes_after=30):
        return

    if is_weekend_gap_risk():
        return

    symbols = list(Config.FXGOLD_ASSETS.keys())
    random.shuffle(symbols)

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

        atr_pct = float(res.get("atr_pct", 0) or 0)
        if atr_pct >= float(getattr(Config, "MAX_ATR_PCT", 1.5)):
            log(f"[VOL] {sym}: volatilidade extrema ({atr_pct:.2f}%)")
            continue

        direction = "BUY" if res["cenario"] == "ALTA" else "SELL"
        sc, tot_c, checks, passed, _ = calc_confluence(res, direction, mtf)
        if not passed:
            continue

        entry = float(res["price"])
        atr = float(res.get("atr", 0) or 0)

        sl, tp, rr, sl_src, tp_src = _get_smc_sl_tp(entry, direction, res, mtf, atr)
        if not sl or not tp:
            log(f"[SMC] {sym}: SL/TP inválido, descartado")
            continue

        sl_pct = round((abs(entry - sl) / entry) * 100, 2) if entry else 0
        tp_pct = round((abs(tp - entry) / entry) * 100, 2) if entry else 0

        pf = pip_factor(sym)
        sl_pips = round(abs(entry - sl) / pf)
        tp_pips = round(abs(tp - entry) / pf)

        eff_lev = get_dynamic_leverage(bot.balance)

        suggested_lot, suggested_risk_usd, suggested_risk_pct = calc_lot_for_risk(
            sym,
            entry,
            sl,
            bot.balance,
            risk_pct=getattr(Config, "ATR_RISK_PCT", 1.0),
            atr=atr,
            atr_mult=getattr(Config, "ATR_MULT_FOR_RISK", 2.0),
        )

        min_lot_margin = calc_margin(sym, entry, eff_lev, Config.MIN_LOT)
        dist_sl = abs(entry - sl)
        cs_val = contract_size_for(sym)
        risk_001_lot = dist_sl * cs_val * 0.01
        risk_pct_001 = (risk_001_lot / bot.balance) * 100 if bot.balance > 0 else 0

        est_risk_usd = suggested_risk_usd
        if is_jpy_pair(sym):
            usdjpy = bot._usdjpy_price or 150.0
            est_risk_usd = est_risk_usd / usdjpy

        ok_corr, msg_corr = bot.check_correlation_exposure(sym, est_risk_usd)
        if not ok_corr:
            log(f"[CORR] {sym}: {msg_corr} — sinal descartado")
            continue

        from ai_validator import load_ai_params, validate_signal

        ai_params = load_ai_params()
        min_rr = float(ai_params.get("min_rr", 1.5))
        base_conf = int(ai_params.get("min_confluence", Config.MIN_CONFLUENCE))
        bias = ai_params.get("strategy_bias", "balanced")

        bias_adj = {"conservative": +1, "aggressive": -1}.get(bias, 0)
        live_conf = int(ai_params.get("live_confluence", base_conf))
        effective_min_conf = max(6, min(9, live_conf + bias_adj))

        if sc < effective_min_conf:
            log(
                f"[CONF] {sym}: score {sc} < mínimo {effective_min_conf} "
                f"(base={base_conf}, bias={bias}, regime={ai_params.get('live_regime','?')})"
            )
            continue

        if rr < min_rr:
            log(f"[RR] {sym}: R:R {rr} abaixo do mínimo {min_rr}, descartado")
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
            "atr_pct": atr_pct,
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
            "adx": res.get("adx", 0),
            "mtf_aligned": mtf.get("aligned", False),
            "h4_cenario": mtf.get("h4_cenario", "NEUTRO"),
            "sl_source": sl_src,
            "tp_source": tp_src,
        }

        approved, ai_reason = validate_signal(pend, mtf, bot)
        if not approved:
            log(f"[AI] {sym} {direction} rejeitado: {ai_reason}")
            continue

        ai_confidence = 0
        try:
            if "(" in ai_reason and "/" in ai_reason:
                ai_confidence = int(ai_reason.split("(")[1].split("/")[0])
        except (ValueError, IndexError):
            pass

        pend["ai_reason"] = ai_reason
        pend["ai_approved"] = True
        pend["ai_confidence"] = ai_confidence

        bot.add_pending(pend)
        break


# =============================================================================
# SNAPSHOT DE CONFLUÊNCIA
# =============================================================================

_snapshot_cache: list = []
_snapshot_ts: float = 0.0
_SNAPSHOT_TTL: int = 600


def get_confluence_snapshot() -> list[dict]:
    """Varre todos os pares e retorna score de confluência atual. Cacheado 10min."""
    global _snapshot_cache, _snapshot_ts

    if time.time() - _snapshot_ts < _SNAPSHOT_TTL and _snapshot_cache:
        return _snapshot_cache

    results = []
    for sym in Config.FXGOLD_ASSETS:
        try:
            mtf = get_multi_timeframe(sym)
            h1 = mtf.get("h1")
            if not h1:
                continue

            buy_sc, buy_tot, buy_checks, _, _ = calc_confluence(h1, "BUY", mtf)
            sell_sc, sell_tot, sell_checks, _, _ = calc_confluence(h1, "SELL", mtf)

            best_dir = "BUY" if buy_sc >= sell_sc else "SELL"
            best_score = max(buy_sc, sell_sc)

            results.append({
                "symbol": sym,
                "buy_score": buy_sc,
                "sell_score": sell_sc,
                "best_dir": best_dir,
                "best_score": best_score,
                "total": buy_tot,
                "rsi": round(float(h1.get("rsi", 0) or 0), 1),
                "adx": round(float(h1.get("adx", 0) or 0), 1),
                "cenario": h1.get("cenario", "NEUTRO"),
                "h4_aligned": mtf.get("aligned", False),
                "buy_checks": [{"name": n, "ok": ok} for n, ok in buy_checks],
                "sell_checks": [{"name": n, "ok": ok} for n, ok in sell_checks],
            })
        except Exception as e:
            log(f"[SNAPSHOT] Erro em {sym}: {e}")

    results.sort(key=lambda x: x["best_score"], reverse=True)
    _snapshot_cache = results
    _snapshot_ts = time.time()
    return results


def check_near_signals(bot) -> None:
    """Alerta pares próximos do score mínimo (só os permitidos pelo tier)."""
    from ai_validator import load_ai_params

    ai_params = load_ai_params()
    effective_conf = int(ai_params.get("live_confluence", Config.MIN_CONFLUENCE))
    near_threshold = effective_conf - 2

    if not hasattr(bot, "_near_signal_cooldown"):
        bot._near_signal_cooldown = {}

    allowed_symbols = get_allowed_symbols(bot.balance)
    now = time.time()
    snapshot = get_confluence_snapshot()

    for item in snapshot:
        sym = item["symbol"]
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

        bars = "🟢" * score + "⚪" * max(0, total - score)
        msg = (
            f"📊 QUASE SINAL — {sym}\n"
            f"──────────────────\n"
            f"Direção: {direc} | Score: {score}/{total}\n"
            f"{bars}\n"
            f"RSI: {item['rsi']} | ADX: {item['adx']}\n"
            f"H4: {'✅ Alinhado' if item['h4_aligned'] else '❌ Desalinhado'}\n\n"
            f"❌ Falta confirmar:\n" +
            "\n".join(f"  • {m}" for m in missing) +
            f"\n\nFaltam {effective_conf - score} check(s) para virar sinal."
        )
        bot.send(msg)
        bot._near_signal_cooldown[sym] = now
        log(f"[NEAR] {sym} {direc} {score}/{total} — alerta enviado")
