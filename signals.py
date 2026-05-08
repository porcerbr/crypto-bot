from __future__ import annotations

import random
import time
from datetime import datetime

from analysis import get_multi_timeframe
from config import Config
from news_filter import is_high_impact_news_window
from cot_filter import get_cot_bias
from risk import calc_lot_for_risk
from utils import (
    fmt,
    get_allowed_symbols,
    get_kill_zone,
    get_sl_tp_atr,
    is_good_session,
    is_jpy_pair,
    is_price_in_ote,
    is_weekend_gap_risk,
    load_strategy_settings,
    log,
)

_SNAPSHOT_TTL = 300
_snapshot_cache: list[dict] = []
_snapshot_ts = 0.0


def is_weekend() -> bool:
    return datetime.utcnow().weekday() >= 5


def _is_safe_to_trade(bot, symbol: str):
    """Bloqueios mínimos; o resto vira preferência, não veto."""
    from utils import get_dynamic_cooldown, is_symbol_allowed

    if not is_symbol_allowed(symbol):
        return False, f"Ativo fora da lista monitorada"

    if is_weekend_gap_risk():
        return False, "Proteção de fim de semana/gap ativa"

    cooldown = get_dynamic_cooldown(None)
    if time.time() < float(bot.asset_cooldown.get(symbol, 0) or 0):
        return False, f"Cooldown ativo ({cooldown // 60}min)"

    if getattr(Config, "SESSION_HARD_BLOCK", False) and not is_good_session(symbol):
        return False, "Fora da sessão principal"

    if getattr(Config, "NEWS_HARD_BLOCK", False) and is_high_impact_news_window(minutes_before=15, minutes_after=30, symbol=symbol):
        return False, "Janela de notícia de alto impacto"

    return True, ""


def _market_regime(res: dict, mtf: dict | None = None) -> str:
    adx = float(res.get("adx", 0) or 0)
    aligned = bool(mtf.get("aligned", False)) if mtf else False
    h4 = mtf.get("h4") if mtf else None
    h4_adx = float(h4.get("adx", 0) or 0) if h4 else 0

    if adx >= Config.REGIME_ADX_TRENDING and aligned:
        return "trend"
    if adx <= Config.REGIME_ADX_RANGING:
        return "range"
    if h4_adx >= Config.REGIME_ADX_STRONG:
        return "trend"
    return "transition"


def _setup_for_regime(regime: str) -> str:
    return {
        "trend": "pullback",
        "range": "reversal",
        "transition": "breakout",
    }.get(regime, "wait")


def _trend_checks(res: dict, mtf: dict | None, direction: str):
    price = float(res.get("price", 0) or 0)
    ema200 = float(res.get("ema200", 0) or 0)
    ema21 = float(res.get("ema21", 0) or 0)
    rsi = float(res.get("rsi", 50) or 50)
    adx = float(res.get("adx", 0) or 0)
    macd_bull = bool(res.get("macd_bull", False))
    macd_bear = bool(res.get("macd_bear", False))
    cenario = str(res.get("cenario", "NEUTRO"))
    aligned = bool(mtf.get("aligned", False)) if mtf else False

    checks: list[tuple[str, bool, int]] = []

    if direction == "BUY":
        checks.extend([
            ("Preço > EMA200", price > ema200, 2),
            ("EMA21 acima EMA200", ema21 > ema200, 1),
            ("MACD bullish", macd_bull, 2),
            ("RSI saudável", 45 <= rsi <= 68, 1),
            ("ADX forte", adx >= Config.REGIME_ADX_TRENDING, 2),
            ("H4 alinhado", aligned or cenario == "ALTA", 2),
        ])
    else:
        checks.extend([
            ("Preço < EMA200", price < ema200, 2),
            ("EMA21 abaixo EMA200", ema21 < ema200, 1),
            ("MACD bearish", macd_bear, 2),
            ("RSI saudável", 32 <= rsi <= 55, 1),
            ("ADX forte", adx >= Config.REGIME_ADX_TRENDING, 2),
            ("H4 alinhado", aligned or cenario == "BAIXA", 2),
        ])
    return checks


def calc_confluence(res, direction, mtf=None):
    """Score enxuto: apenas tendência, momentum, força e alinhamento H4."""
    regime = _market_regime(res, mtf)
    setup_type = _setup_for_regime(regime)
    checks = _trend_checks(res, mtf, direction)
    score = sum(weight for _, ok, weight in checks if ok)
    total = sum(weight for _, _, weight in checks)

    min_score = int(Config.REGIME_MIN_CONFLUENCE.get(regime, Config.MIN_CONFLUENCE))
    if regime == "trend" and bool(mtf.get("aligned", False) if mtf else False):
        min_score = max(1, min_score - 1)

    passed = score >= min_score
    meta = {"regime": regime, "setup_type": setup_type}
    return score, total, [(n, ok) for n, ok, _ in checks], passed, min_score, meta


def _recent_pair_wr(bot, symbol: str, direction: str | None = None, lookback: int | None = None):
    lookback = int(lookback or getattr(Config, "PAIR_PERFORMANCE_LOOKBACK", 12))
    history = list(getattr(bot, "history", []) or [])
    filtered = [h for h in history if h.get("symbol") == symbol and (direction is None or h.get("dir") == direction)]
    if len(filtered) < max(5, lookback):
        return None
    sample = filtered[-lookback:]
    wins = sum(1 for h in sample if h.get("result") == "WIN")
    return wins / max(1, len(sample))


def _compute_trade_levels(symbol: str, direction: str, res: dict, mtf: dict):
    entry = float(res.get("price", 0) or 0)
    atr = float(res.get("atr", 0) or 0)
    sl, tp, rr, *_ = get_sl_tp_atr(entry, atr, direction, atr_sl_mult=float(Config.ATR_SL_MULT), atr_tp_mult=float(Config.ATR_TP_MULT))
    sl_pips = abs(entry - sl) / (0.01 if is_jpy_pair(symbol) or symbol == "XAUUSD" else 0.0001)
    tp_pips = abs(tp - entry) / (0.01 if is_jpy_pair(symbol) or symbol == "XAUUSD" else 0.0001)
    rr = round(tp_pips / max(sl_pips, 1e-9), 2)
    return sl, tp, rr, atr


def is_weekend():
    return datetime.utcnow().weekday() >= 5


def scan(bot):
    if bot.is_paused() or is_weekend():
        return

    symbols = list(get_allowed_symbols())
    try:
        ranking = {item["symbol"]: item.get("best_score", 0) for item in get_confluence_snapshot()}
        symbols.sort(key=lambda s: ranking.get(s, 0), reverse=True)
    except Exception:
        random.shuffle(symbols)

    executed = 0
    max_signals = max(1, int(getattr(Config, "MAX_SYMBOLS_PER_REFRESH", 4)))
    strategy = load_strategy_settings()
    min_rr = float(strategy.get("min_rr", Config.REGIME_MIN_RR.get("trend", 1.8)))

    for sym in symbols:
        safe, reason = _is_safe_to_trade(bot, sym)
        if not safe:
            if reason and "Cooldown" not in reason:
                log(f"[SAFETY] {sym}: {reason}")
            continue

        if any(t.get("symbol") == sym for t in bot.active_trades + bot.pending_trades):
            continue

        mtf = get_multi_timeframe(sym)
        h1 = mtf.get("h1")
        if not h1:
            continue

        if getattr(Config, "USE_COT_FILTER", False):
            try:
                cot_bias = get_cot_bias(sym)
                if cot_bias != "NEUTRAL":
                    direction_guess = "BUY" if h1.get("price", 0) > h1.get("ema200", 0) else "SELL"
                    if cot_bias != ("BULLISH" if direction_guess == "BUY" else "BEARISH"):
                        continue
            except Exception:
                pass

        recent_wr = _recent_pair_wr(bot, sym)
        if recent_wr is not None and recent_wr < float(getattr(Config, "MIN_RECENT_PAIR_WR", 0.40)):
            continue

        buy_sc, buy_tot, buy_checks, buy_passed, buy_min, buy_meta = calc_confluence(h1, "BUY", mtf)
        sell_sc, sell_tot, sell_checks, sell_passed, sell_min, sell_meta = calc_confluence(h1, "SELL", mtf)

        direction = "BUY" if buy_sc >= sell_sc else "SELL"
        sc = max(buy_sc, sell_sc)
        tot_c = buy_tot if direction == "BUY" else sell_tot
        checks = buy_checks if direction == "BUY" else sell_checks
        passed = buy_passed if direction == "BUY" else sell_passed
        min_sc = buy_min if direction == "BUY" else sell_min
        meta = buy_meta if direction == "BUY" else sell_meta

        if not passed:
            continue

        entry = float(h1.get("price", 0) or 0)
        sl, tp, rr, atr = _compute_trade_levels(sym, direction, h1, mtf)
        if rr < max(min_rr, float(Config.REGIME_MIN_RR.get(meta["regime"], min_rr))):
            continue

        if entry <= 0 or atr <= 0:
            continue

        sl_pct = abs(entry - sl) / entry * 100 if entry else 0
        tp_pct = abs(tp - entry) / entry * 100 if entry else 0
        pf = 0.01 if is_jpy_pair(sym) or sym == "XAUUSD" else 0.0001
        sl_pips = abs(entry - sl) / pf
        tp_pips = abs(tp - entry) / pf

        pend = {
            "pending_id": bot.next_pending_id(),
            "symbol": sym,
            "name": Config.FXGOLD_ASSETS.get(sym, sym),
            "dir": direction,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sl_pct": round(sl_pct, 2),
            "tp_pct": round(tp_pct, 2),
            "sl_pips": round(sl_pips, 1),
            "tp_pips": round(tp_pips, 1),
            "rr": rr,
            "score": sc,
            "max_score": tot_c,
            "checks": [{"name": n, "ok": ok} for n, ok in checks],
            "min_lot_margin": 0.0,
            "risk_001_lot": 0.0,
            "risk_pct_001": 0.0,
            "suggested_lot": Config.MIN_LOT,
            "suggested_risk_usd": 0.0,
            "suggested_risk_pct": 0.0,
            "created_at": datetime.utcnow().strftime("%d/%m %H:%M"),
            "created_ts": time.time(),
            "atr": atr,
            "mtf_aligned": bool(mtf.get("aligned", False)),
            "h4_cenario": mtf.get("h4_cenario", "NEUTRO"),
            "daily_bias": mtf.get("daily_bias", "NEUTRO"),
            "kill_zone": get_kill_zone(sym),
            "ote_active": is_price_in_ote(h1),
            "market_regime": meta.get("regime", "transition"),
            "setup_type": meta.get("setup_type", "wait"),
            "sl_source": "atr",
            "tp_source": "atr",
        }

        ok = bot.execute_signal(pend)
        if ok:
            executed += 1
            log(f"[SIGNAL] {sym} {direction} executado | score {sc}/{tot_c} | RR 1:{rr}")
            if executed >= max_signals:
                break


def get_confluence_snapshot() -> list[dict]:
    global _snapshot_cache, _snapshot_ts
    if time.time() - _snapshot_ts < _SNAPSHOT_TTL and _snapshot_cache:
        return _snapshot_cache

    results: list[dict] = []
    for sym in Config.FXGOLD_ASSETS:
        try:
            mtf = get_multi_timeframe(sym)
            h1 = mtf.get("h1")
            if not h1:
                continue
            buy_sc, buy_tot, buy_checks, _, _, buy_meta = calc_confluence(h1, "BUY", mtf)
            sell_sc, sell_tot, sell_checks, _, _, sell_meta = calc_confluence(h1, "SELL", mtf)
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
                "h4_aligned": bool(mtf.get("aligned", False)),
                "market_regime": buy_meta.get("regime", "transition"),
                "buy_setup": buy_meta.get("setup_type", "wait"),
                "sell_setup": sell_meta.get("setup_type", "wait"),
                "buy_checks": buy_checks,
                "sell_checks": sell_checks,
            })
        except Exception as e:
            log(f"[SNAPSHOT] {sym}: {e}")

    results.sort(key=lambda x: x["best_score"], reverse=True)
    _snapshot_cache = results
    _snapshot_ts = time.time()
    return results


def check_near_signals(bot) -> None:
    strategy = load_strategy_settings()
    effective_conf = int(strategy.get("min_confluence", Config.MIN_CONFLUENCE))
    near_threshold = max(1, effective_conf - 2)

    if not hasattr(bot, "_near_signal_cooldown"):
        bot._near_signal_cooldown = {}

    now = time.time()
    allowed_symbols = set(get_allowed_symbols())
    for item in get_confluence_snapshot():
        sym = item["symbol"]
        if sym not in allowed_symbols:
            continue
        score = int(item["best_score"])
        total = int(item["total"])
        if score < near_threshold or score >= effective_conf:
            continue
        if now - bot._near_signal_cooldown.get(sym, 0) < 7200:
            continue

        direction = item.get("best_dir", "—")
        checks = item["buy_checks"] if direction == "BUY" else item["sell_checks"]
        missing = [name for name, ok in checks if not ok][:3]
        bars = "🟢" * score + "⚪" * max(0, total - score)
        bot.send(
            f"📊 QUASE SINAL — {sym}\n"
            f"Direção: {direction} | Score: {score}/{total}\n"
            f"{bars}\n"
            f"RSI: {item['rsi']} | ADX: {item['adx']}\n"
            f"H4: {'✅' if item['h4_aligned'] else '❌'}\n\n"
            f"Faltando:\n" + "\n".join(f"• {m}" for m in missing)
        )
        bot._near_signal_cooldown[sym] = now
        log(f"[NEAR] {sym} {direction} {score}/{total}")
