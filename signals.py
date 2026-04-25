# signals.py
import time
from datetime import datetime
from config import Config
from utils import log, fmt, all_syms, asset_cat, asset_name, max_leverage, get_sl_tp_pct
from analysis import get_analysis

def calc_confluence(res, direction):
    checks = []
    if direction == "BUY":
        checks = [
            ("Preço > EMA200", res["price"] > res["ema200"]),
            ("EMA9 > EMA21", res["ema9"] > res["ema21"]),
            ("MACD bullish", res["macd_bull"]),
            ("RSI < 65", res["rsi"] < 65),
            ("ADX > 20", res["adx"] > 20),
            ("Próximo à banda inferior", res["price"] < res["lower"] * 1.02),
            ("Fechamento > Abertura", res.get("candle_bull", True)),
        ]
    else:
        checks = [
            ("Preço < EMA200", res["price"] < res["ema200"]),
            ("EMA9 < EMA21", res["ema9"] < res["ema21"]),
            ("MACD bearish", res["macd_bear"]),
            ("RSI > 35", res["rsi"] > 35),
            ("ADX > 20", res["adx"] > 20),
            ("Próximo à banda superior", res["price"] > res["upper"] * 0.98),
            ("Fechamento < Abertura", res.get("candle_bear", True)),
        ]
    score = sum(1 for _, ok in checks if ok)
    return score, len(checks), checks, score >= Config.MIN_CONFLUENCE, Config.MIN_CONFLUENCE

def scan(bot):
    if bot.is_paused() or len(bot.active_trades) >= Config.MAX_TRADES:
        return
    universe = all_syms() if bot.mode == "TUDO" else list(Config.MARKET_CATEGORIES[bot.mode]["assets"].keys())
    for symbol in universe:
        if any(t["symbol"] == symbol for t in bot.active_trades + bot.pending_trades):
            continue
        if time.time() - bot.asset_cooldown.get(symbol, 0) < Config.ASSET_COOLDOWN:
            continue
        res = get_analysis(symbol, bot.timeframe)
        if not res or res["cenario"] == "NEUTRO":
            continue

        direction = "BUY" if res["cenario"] == "ALTA" else "SELL"
        sc, tot_c, checks, passed, min_sc = calc_confluence(res, direction)
        if not passed:
            continue

        # Calcular SL e TP com RR dinâmico baseado na confluência
        eff_lev = min(bot.leverage, max_leverage(symbol))
        base_sl, base_tp = get_sl_tp_pct(eff_lev)
        rr = Config.TP_SL_RATIO + 0.2 * (sc - min_sc)
        sl_pct, tp_pct = get_sl_tp_pct(eff_lev, rr)
        entry = res["price"]
        if direction == "BUY":
            sl = round(entry * (1 - sl_pct/100), 5)
            tp = round(entry * (1 + tp_pct/100), 5)
        else:
            sl = round(entry * (1 + sl_pct/100), 5)
            tp = round(entry * (1 - tp_pct/100), 5)

        pend = {
            "pending_id": bot.next_pending_id(),
            "symbol": symbol,
            "name": res["name"],
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
            "created_at": datetime.now().strftime("%d/%m %H:%M"),
        }
        bot.add_pending(pend)
        # Só envia o primeiro sinal para não floodar
        break
