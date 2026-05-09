"""
signals.py — motor de sinais simplificado para Forex/Ouro.

Estratégia: trend following com pullback, usando somente o necessário:
- EMA50 + EMA200: direção e filtro de tendência.
- RSI14: momentum e evita entrada em extremo.
- ATR14: stop, alvo e filtro de volatilidade.
- ADX14: força mínima da tendência.

O bot continua sendo sinalizador: não envia ordens reais para corretora.
"""

import random
import time
from datetime import datetime

from analysis import get_multi_timeframe
from config import Config
from news_filter import is_high_impact_news_window
from risk import calc_lot_for_risk, calc_margin
from utils import (
    get_allowed_symbols,
    get_dynamic_cooldown,
    get_kill_zone,
    is_good_session,
    is_jpy_pair,
    is_symbol_allowed,
    is_weekend_gap_risk,
    log,
)

_SNAPSHOT_TTL = 600  # 10 minutos
_snapshot_cache: list[dict] = []
_snapshot_ts = 0.0


def _cfg(name: str, default):
    return getattr(Config, name, default)


def _ema50(res: dict) -> float:
    """Compatibilidade: se uma fonte antiga ainda não trouxer EMA50, usa EMA21."""
    return float(res.get("ema50", res.get("ema21", 0)) or 0)


def _trend_direction(res: dict) -> str:
    price = float(res.get("price", 0) or 0)
    ema50 = _ema50(res)
    ema200 = float(res.get("ema200", 0) or 0)
    if price > ema200 and ema50 > ema200:
        return "BUY"
    if price < ema200 and ema50 < ema200:
        return "SELL"
    return "NEUTRO"


def _mtf_ok(direction: str, mtf: dict | None) -> bool:
    if not mtf:
        return False

    h4 = mtf.get("h4") or {}
    h4_dir = _trend_direction(h4) if h4 else "NEUTRO"
    daily_bias = str(mtf.get("daily_bias", "NEUTRO")).upper()
    opposite_daily = "BAIXA" if direction == "BUY" else "ALTA"

    # O H4 precisa confirmar; o diário apenas não pode estar contra.
    return h4_dir == direction and daily_bias != opposite_daily


def _market_regime(res: dict, mtf: dict | None = None) -> str:
    direction = _trend_direction(res)
    adx = float(res.get("adx", 0) or 0)
    if direction == "NEUTRO":
        return "wait"
    if adx < float(_cfg("ADX_MIN_TREND", 18)):
        return "weak_trend"
    if not _mtf_ok(direction, mtf):
        return "mixed_mtf"
    return "trend"


def _setup_for_regime(regime: str, direction: str) -> str:
    if regime == "trend" and direction in ("BUY", "SELL"):
        return "ema_pullback"
    return "wait"


def _rsi_ok(direction: str, rsi: float) -> bool:
    if direction == "BUY":
        return float(_cfg("RSI_BUY_MIN", 52)) <= rsi <= float(_cfg("RSI_BUY_MAX", 66))
    return float(_cfg("RSI_SELL_MIN", 34)) <= rsi <= float(_cfg("RSI_SELL_MAX", 48))


def _atr_ok(price: float, atr: float) -> bool:
    if price <= 0 or atr <= 0:
        return False
    atr_pct = atr / price * 100
    return float(_cfg("ATR_MIN_PCT", 0.02)) <= atr_pct <= float(_cfg("ATR_MAX_PCT", 1.50))


def _pullback_ok(direction: str, price: float, ema50: float, atr: float) -> bool:
    if price <= 0 or ema50 <= 0 or atr <= 0:
        return False
    max_dist = float(_cfg("PULLBACK_ATR_MAX", 1.4)) * atr
    if direction == "BUY":
        # Compra só se o preço estiver acima/perto da EMA50, sem estar esticado demais.
        return ema50 - 0.25 * atr <= price <= ema50 + max_dist
    # Venda só se o preço estiver abaixo/perto da EMA50, sem estar esticado demais.
    return ema50 - max_dist <= price <= ema50 + 0.25 * atr


def calc_confluence(res: dict, direction: str, mtf: dict | None = None):
    """
    Score simples e auditável. Retorna:
    score, max_score, checks, passed, min_score, meta
    """
    checks: list[tuple[str, bool]] = []
    weighted: list[tuple[str, bool, int]] = []

    def add(name: str, ok: bool, weight: int):
        checks.append((name, bool(ok)))
        weighted.append((name, bool(ok), int(weight)))

    price = float(res.get("price", 0) or 0)
    ema50 = _ema50(res)
    ema200 = float(res.get("ema200", 0) or 0)
    rsi = float(res.get("rsi", 50) or 50)
    atr = float(res.get("atr", 0) or 0)
    adx = float(res.get("adx", 0) or 0)

    trend_dir = _trend_direction(res)
    trend_ok = trend_dir == direction
    mtf_ok = _mtf_ok(direction, mtf)
    rsi_ok = _rsi_ok(direction, rsi)
    atr_ok = _atr_ok(price, atr)
    pullback_ok = _pullback_ok(direction, price, ema50, atr)
    adx_ok = adx >= float(_cfg("ADX_MIN_TREND", 18))

    if direction == "BUY":
        add("Preço acima da EMA200", price > ema200, 2)
        add("EMA50 acima da EMA200", ema50 > ema200, 2)
        add("Preço acima da EMA50", price > ema50, 1)
    else:
        add("Preço abaixo da EMA200", price < ema200, 2)
        add("EMA50 abaixo da EMA200", ema50 < ema200, 2)
        add("Preço abaixo da EMA50", price < ema50, 1)

    add("H4/D1 não estão contra", mtf_ok, 2)
    add("RSI em zona operacional", rsi_ok, 2)
    add("Pullback próximo da EMA50", pullback_ok, 1)
    add("ATR saudável", atr_ok, 1)
    add("ADX confirma tendência", adx_ok, 1)

    score = sum(weight for _, ok, weight in weighted if ok)
    total = sum(weight for _, _, weight in weighted)
    min_score = int(_cfg("SIMPLE_MIN_SCORE", 9))

    regime = _market_regime(res, mtf)
    setup_type = _setup_for_regime(regime, direction)

    # Hard filters: evita sinais bons no placar mas ruins na estrutura principal.
    hard_ok = trend_ok and mtf_ok and rsi_ok and atr_ok and pullback_ok and adx_ok
    passed = bool(score >= min_score and hard_ok)
    meta = {"regime": regime, "setup_type": setup_type}
    return score, total, checks, passed, min_score, meta


def _is_safe_to_trade(bot, symbol: str):
    """Filtros operacionais que não são indicadores."""
    if not is_symbol_allowed(symbol):
        return False, f"Ativo fora da lista monitorada. Monitorados: {', '.join(get_allowed_symbols())}"

    if is_weekend_gap_risk():
        return False, "Proteção de fim de semana/gap ativa"

    cooldown = int(get_dynamic_cooldown(None))
    last = max(
        float(getattr(bot, "asset_cooldown", {}).get(symbol, 0) or 0),
        float(getattr(bot, "signal_cooldown", {}).get(symbol, 0) or 0),
    )
    if time.time() - last < cooldown:
        return False, f"Cooldown ativo ({cooldown // 60}min)"

    if getattr(Config, "SESSION_HARD_BLOCK", False) and not is_good_session(symbol):
        return False, "Fora da sessão principal"

    return True, ""


def _select_signal(mtf: dict):
    h1 = mtf.get("h1")
    if not h1:
        return None

    candidates = []
    for direction in ("BUY", "SELL"):
        sc, total, checks, passed, min_sc, meta = calc_confluence(h1, direction, mtf)
        if passed:
            candidates.append((sc, direction, total, checks, min_sc, meta))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    sc, direction, total, checks, min_sc, meta = candidates[0]
    return {
        "direction": direction,
        "score": sc,
        "total": total,
        "checks": checks,
        "min_score": min_sc,
        "meta": meta,
    }


def _get_atr_sl_tp(entry: float, direction: str, atr: float):
    sl_mult = float(_cfg("ATR_SL_MULT", 1.5))
    tp_mult = float(_cfg("ATR_TP_MULT", 3.0))
    if direction == "BUY":
        sl = round(entry - sl_mult * atr, 5)
        tp = round(entry + tp_mult * atr, 5)
    else:
        sl = round(entry + sl_mult * atr, 5)
        tp = round(entry - tp_mult * atr, 5)
    rr = round(tp_mult / sl_mult, 2) if sl_mult > 0 else 0
    return sl, tp, rr


def _pips(symbol: str, distance: float) -> float:
    pip = 0.01 if is_jpy_pair(symbol) or symbol == "XAUUSD" else 0.0001
    return round(abs(distance) / pip, 1)


def scan(bot):
    if bot.is_paused() or datetime.utcnow().weekday() >= 5:
        return

    symbols = list(get_allowed_symbols())
    try:
        ranking = {item["symbol"]: item.get("best_score", 0) for item in get_confluence_snapshot()}
        symbols.sort(key=lambda s: ranking.get(s, 0), reverse=True)
    except Exception:
        random.shuffle(symbols)

    max_signals = max(1, int(_cfg("MAX_SYMBOLS_PER_REFRESH", 3)))
    executed = 0

    for sym in symbols:
        safe, reason = _is_safe_to_trade(bot, sym)
        if not safe:
            if reason and "Cooldown" not in reason:
                log(f"[SAFETY] {sym}: {reason}")
            continue

        if any(t.get("symbol") == sym for t in bot.active_trades + bot.pending_trades):
            continue

        mtf = get_multi_timeframe(sym)
        selected = _select_signal(mtf)
        if not selected:
            continue

        h1 = mtf["h1"]
        direction = selected["direction"]
        price = float(h1["price"])
        atr = float(h1["atr"])

        if is_high_impact_news_window(minutes_before=15, minutes_after=30, symbol=sym):
            if getattr(Config, "NEWS_HARD_BLOCK", False):
                log(f"[NEWS] {sym}: notícia de alto impacto — sinal bloqueado")
                continue

        sl, tp, rr = _get_atr_sl_tp(price, direction, atr)
        min_rr = float(_cfg("MIN_RR", 1.8))
        if rr < min_rr:
            log(f"[RR] {sym}: R:R {rr} abaixo do mínimo {min_rr}")
            continue

        sl_pips = _pips(sym, price - sl)
        tp_pips = _pips(sym, tp - price)
        sl_pct = abs(price - sl) / price * 100 if price else 0
        tp_pct = abs(tp - price) / price * 100 if price else 0
        quality_10 = max(1, min(10, round(selected["score"] / selected["total"] * 10)))

        suggested_lot, risk_usd, risk_pct_real = calc_lot_for_risk(
            sym,
            price,
            sl,
            max(1.0, float(getattr(bot, "balance", 0.0) or 0.0)),
            risk_pct=float(_cfg("RISK_PERCENT_PER_TRADE", 1.0)),
            atr=atr,
            atr_mult=float(_cfg("ATR_MULT_FOR_RISK", 2.0)),
        )
        suggested_lot = max(Config.MIN_LOT, round(float(suggested_lot or Config.MIN_LOT), 2))
        leverage = int(getattr(bot, "get_current_leverage", lambda: Config.DEFAULT_LEVERAGE)())
        min_lot_margin = calc_margin(sym, price, leverage, Config.MIN_LOT)

        pend = {
            "pending_id": bot.next_pending_id(),
            "symbol": sym,
            "name": Config.FXGOLD_ASSETS.get(sym, sym),
            "dir": direction,
            "entry": price,
            "sl": sl,
            "tp": tp,
            "sl_pct": round(sl_pct, 3),
            "tp_pct": round(tp_pct, 3),
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "rr": rr,
            "score": selected["score"],
            "max_score": selected["total"],
            "score_total": selected["total"],
            "checks": [{"name": nm, "ok": ok} for nm, ok in selected["checks"]],
            "min_lot_margin": round(float(min_lot_margin), 2),
            "risk_001_lot": round(float(risk_usd), 2),
            "risk_pct_001": round(float(risk_pct_real), 2),
            "suggested_lot": suggested_lot,
            "suggested_risk_usd": round(float(risk_usd), 2),
            "suggested_risk_pct": round(float(risk_pct_real), 2),
            "created_at": datetime.now().strftime("%d/%m %H:%M"),
            "created_ts": time.time(),
            "atr": atr,
            "mtf_aligned": _mtf_ok(direction, mtf),
            "h4_cenario": mtf.get("h4_cenario", "NEUTRO"),
            "daily_bias": mtf.get("daily_bias", "NEUTRO"),
            "kill_zone": get_kill_zone(sym),
            "ote_active": False,
            "sl_source": "atr",
            "tp_source": "atr",
            "market_regime": selected["meta"].get("regime", "trend"),
            "setup_type": selected["meta"].get("setup_type", "ema_pullback"),
            "ai_reason": "Sem IA: sinal validado por EMA50/EMA200, RSI, ATR e ADX.",
            "ai_approved": True,
            "ai_confidence": quality_10,
        }

        if bot.execute_signal(pend):
            executed += 1
            log(f"[SIGNAL] {sym} {direction} score={selected['score']}/{selected['total']} rr={rr}")
            if executed >= max_signals:
                break


def get_confluence_snapshot() -> list[dict]:
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

            buy_sc, buy_total, buy_checks, buy_passed, _, buy_meta = calc_confluence(h1, "BUY", mtf)
            sell_sc, sell_total, sell_checks, sell_passed, _, sell_meta = calc_confluence(h1, "SELL", mtf)

            best_dir = "BUY" if buy_sc >= sell_sc else "SELL"
            best_score = max(buy_sc, sell_sc)
            best_total = buy_total if best_dir == "BUY" else sell_total

            results.append({
                "symbol": sym,
                "buy_score": buy_sc,
                "sell_score": sell_sc,
                "best_dir": best_dir,
                "best_score": best_score,
                "total": best_total,
                "rsi": round(float(h1.get("rsi", 0) or 0), 1),
                "adx": round(float(h1.get("adx", 0) or 0), 1),
                "atr": round(float(h1.get("atr", 0) or 0), 5),
                "cenario": h1.get("cenario", "NEUTRO"),
                "h4_aligned": _mtf_ok(best_dir, mtf),
                "market_regime": (buy_meta if best_dir == "BUY" else sell_meta).get("regime", "wait"),
                "buy_setup": buy_meta.get("setup_type", "wait"),
                "sell_setup": sell_meta.get("setup_type", "wait"),
                "buy_checks": buy_checks,
                "sell_checks": sell_checks,
                "buy_passed": buy_passed,
                "sell_passed": sell_passed,
            })
        except Exception as e:
            log(f"[SNAPSHOT] Erro em {sym}: {e}")

    results.sort(key=lambda x: x["best_score"], reverse=True)
    _snapshot_cache = results
    _snapshot_ts = time.time()
    return results


def check_near_signals(bot) -> None:
    min_score = int(_cfg("SIMPLE_MIN_SCORE", 9))
    near_threshold = max(1, min_score - int(_cfg("PRE_SIGNAL_GAP", 2)))

    if not hasattr(bot, "_near_signal_cooldown"):
        bot._near_signal_cooldown = {}

    allowed_symbols = set(get_allowed_symbols())
    now = time.time()

    for item in get_confluence_snapshot():
        sym = item["symbol"]
        if sym not in allowed_symbols:
            continue

        score = int(item.get("best_score", 0) or 0)
        total = int(item.get("total", 10) or 10)
        direction = item.get("best_dir", "—")
        if score < near_threshold or score >= min_score:
            continue

        key = f"{sym}|{direction}"
        if now - bot._near_signal_cooldown.get(key, 0) < int(_cfg("PRE_SIGNAL_COOLDOWN", 1800)):
            continue

        checks = item["buy_checks"] if direction == "BUY" else item["sell_checks"]
        missing = [name for name, ok in checks if not ok][:3]
        bars = "🟢" * score + "⚪" * max(0, total - score)
        msg = (
            f"📊 QUASE SINAL — {sym}\n"
            f"——————————————\n"
            f"Direção: {direction} | Score: {score}/{total}\n"
            f"{bars}\n"
            f"RSI: {item['rsi']} | ADX: {item['adx']}\n"
            f"H4/D1: {'✅ OK' if item['h4_aligned'] else '❌ Contra'}\n\n"
            f"❌ Falta confirmar:\n" +
            "\n".join(f"  • {m}" for m in missing) +
            f"\n\nFaltam {min_score - score} ponto(s) para virar sinal."
        )
        bot.send(msg)
        bot._near_signal_cooldown[key] = now
        log(f"[NEAR] {sym} {direction} {score}/{total}")
