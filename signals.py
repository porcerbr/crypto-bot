import time
from datetime import datetime
from config import Config
from utils import log, fmt, max_leverage, get_sl_tp_atr, is_jpy_pair
from analysis import get_analysis
from risk import calc_margin, contract_size_for, calc_lot_for_risk
from news_filter import is_high_impact_news_window

def calc_confluence(res, direction):
    checks = []
    if direction == "BUY":
        checks = [
            ("Preço > EMA200", res["price"] > res["ema200"]),
            ("EMA9 > EMA21", res["ema9"] > res["ema21"]),
            ("MACD bullish", res["macd_bull"]),
            ("RSI entre 40-65", 40 < res["rsi"] < 65),
            ("ADX > 25", res["adx"] > 25),
            ("Preço perto da banda inferior", res["price"] < res["lower"] * 1.01),
            ("Candle de força (fech > abert)", res.get("candle_bull", True)),
        ]
    else:
        checks = [
            ("Preço < EMA200", res["price"] < res["ema200"]),
            ("EMA9 < EMA21", res["ema9"] < res["ema21"]),
            ("MACD bearish", res["macd_bear"]),
            ("RSI entre 35-60", 35 < res["rsi"] < 60),
            ("ADX > 25", res["adx"] > 25),
            ("Preço perto da banda superior", res["price"] > res["upper"] * 0.99),
            ("Candle de força (fech < abert)", res.get("candle_bear", True)),
        ]
    score = sum(1 for _, ok in checks if ok)
    passed = score >= Config.MIN_CONFLUENCE
    return score, len(checks), checks, passed, Config.MIN_CONFLUENCE

def is_weekend():
    return datetime.utcnow().weekday() >= 5

def scan(bot):
    if bot.is_paused() or len(bot.active_trades) >= Config.MAX_TRADES:
        return

    # ── FILTRO DE NOTÍCIAS ───────────────────────────────────────────
    if is_high_impact_news_window(minutes_before=15, minutes_after=30):
        return

    if is_weekend():
        return

    symbols = list(Config.FXGOLD_ASSETS.keys())

    for sym in symbols:
        if any(t["symbol"] == sym for t in bot.active_trades + bot.pending_trades):
            continue
        if time.time() - bot.asset_cooldown.get(sym, 0) < Config.ASSET_COOLDOWN:
            continue

        res = get_analysis(sym, Config.TIMEFRAME)
        if not res or res["cenario"] == "NEUTRO":
            continue

        direction = "BUY" if res["cenario"] == "ALTA" else "SELL"
        sc, tot_c, checks, passed, min_sc = calc_confluence(res, direction)
        if not passed:
            continue

        entry = res["price"]
        atr = res.get("atr", 0)

        # Alavancagem dinâmica (estimativa inicial)
        eff_lev = max_leverage(sym, Config.MIN_LOT)

        # SL/TP por ATR (preferencial) ou fallback por %
        if atr and atr > 0:
            sl, tp, sl_dist, tp_dist = get_sl_tp_atr(
                entry, atr, direction,
                Config.ATR_SL_MULT, Config.ATR_TP_MULT
            )
            sl_pct = round((sl_dist / entry) * 100, 2) if entry else 0
            tp_pct = round((tp_dist / entry) * 100, 2) if entry else 0
            rr = round(tp_dist / sl_dist, 2) if sl_dist else Config.TP_SL_RATIO
        else:
            from utils import get_sl_tp_pct
            sl_pct, tp_pct = get_sl_tp_pct(eff_lev)
            rr = Config.TP_SL_RATIO + 0.15 * (sc - min_sc)
            sl_pct, tp_pct = get_sl_tp_pct(eff_lev, rr)
            if direction == "BUY":
                sl = round(entry * (1 - sl_pct/100), 5)
                tp = round(entry * (1 + tp_pct/100), 5)
            else:
                sl = round(entry * (1 + sl_pct/100), 5)
                tp = round(entry * (1 - tp_pct/100), 5)

        # ── TURTLE POSITION SIZING ───────────────────────────────────
        suggested_lot, suggested_risk_usd, suggested_risk_pct = calc_lot_for_risk(
            sym, entry, sl, bot.balance,
            risk_pct=Config.ATR_RISK_PCT,
            atr=atr,
            atr_mult=Config.ATR_MULT_FOR_RISK
        )

        # Margem para lote mínimo (informativo)
        min_lot_margin = calc_margin(sym, entry, eff_lev, Config.MIN_LOT)

        # Risco do lote mínimo (informativo)
        dist_sl = abs(entry - sl)
        cs_val = contract_size_for(sym)
        risk_001_lot = dist_sl * cs_val * 0.01
        risk_pct_001 = (risk_001_lot / bot.balance) * 100 if bot.balance > 0 else 0

        # ── FILTRO DE CORRELAÇÃO (antes de criar pending) ────────────
        est_risk_usd = suggested_risk_usd
        if is_jpy_pair(sym):
            est_risk_usd = est_risk_usd / 150.0
        ok_corr, msg_corr = bot.check_correlation_exposure(sym, est_risk_usd)
        if not ok_corr:
            log(f"[CORR] {sym}: {msg_corr} — sinal descartado")
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
            "rr": round(rr, 2),
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
            "atr": atr,
        }
        bot.add_pending(pend)
        break
