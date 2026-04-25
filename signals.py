# signals.py
import time, requests
from datetime import datetime
from config import Config
from utils import log, fmt, all_syms, mkt_open, asset_cat, asset_name, max_leverage_for
from analysis import get_analysis, calc_confluence, cbar, calc_premium_rr, detect_reversal, get_reversal_analysis, calc_reversal_conf
from risk import get_sl_tp_pct, commission_for
from db import save_state
from session_filter import is_trading_session_open
from news_filter import is_high_impact_news_near

# -------------------------------------------------------------------
# Funções de inteligência de mercado (embutidas para evitar imports)
# -------------------------------------------------------------------
def analyze_sentiment(texts):
    """Análise de sentimento via Hugging Face FinBERT (opcional)."""
    if not Config.HF_API_TOKEN or not texts:
        return 0, []
    try:
        headers = {"Authorization": f"Bearer {Config.HF_API_TOKEN}"}
        payload = {"inputs": texts}
        resp = requests.post(
            "https://api-inference.huggingface.co/models/ProsusAI/finbert",
            headers=headers, json=payload, timeout=10
        )
        if resp.status_code != 200:
            log(f"[SENTIMENT] Erro API: {resp.status_code}")
            return 0, []
        results = resp.json()
        scores, reasons = [], []
        for i, res in enumerate(results):
            if not res:
                continue
            pos = next((d["score"] for d in res if d["label"] == "positive"), 0)
            neg = next((d["score"] for d in res if d["label"] == "negative"), 0)
            s = pos - neg
            scores.append(s)
            if abs(s) > 0.5 and i < len(texts):
                reasons.append((texts[i][:100], round(s, 2)))
        avg = sum(scores) / len(scores) if scores else 0
        return avg, reasons[:3]
    except Exception as e:
        log(f"[SENTIMENT] Erro: {e}")
        return 0, []

def get_whale_alerts(symbols=None):
    """Coleta alertas de baleias (Whale Alert API)."""
    if not Config.WHALE_ALERT_API_KEY:
        return []
    try:
        url = f"https://api.whale-alert.io/v1/transactions?api_key={Config.WHALE_ALERT_API_KEY}&min_value=500000&limit=50"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            log(f"[WHALE] Erro API: {resp.status_code}")
            return []
        data = resp.json()
        whales = []
        for tx in data.get("transactions", []):
            symbol = tx.get("symbol", "")
            if not symbol:
                continue
            whales.append({
                "symbol": symbol,
                "amount_usd": tx.get("amount_usd", 0),
                "from_owner": tx.get("from", {}).get("owner_type", "unknown"),
                "to_owner": tx.get("to", {}).get("owner_type", "unknown"),
            })
        log(f"[WHALE] {len(whales)} alertas carregados")
        return [w for w in whales if symbols is None or w["symbol"] in symbols]
    except Exception as e:
        log(f"[WHALE] Erro: {e}")
        return []

def whale_signal_for(symbol):
    """Calcula pressão compradora/vendedora das baleias para um símbolo."""
    alerts = get_whale_alerts([symbol])
    if not alerts:
        return 0, []
    score = 0
    reasons = []
    for a in alerts:
        if "exchange" in a["to_owner"].lower():
            score -= 1
            reasons.append(f"${a['amount_usd']:,.0f} → exchange")
        elif "exchange" in a["from_owner"].lower():
            score += 1
            reasons.append(f"${a['amount_usd']:,.0f} ← exchange")
    if reasons:
        score = max(-1, min(1, score / len(reasons)))
    return score, reasons[:3]

# -------------------------------------------------------------------
# Função de correlação
# -------------------------------------------------------------------
def check_correlation(bot, symbol):
    correlations = {
        "EURUSD": ["GBPUSD", "USDCHF", "AUDUSD"],
        "GBPUSD": ["EURUSD", "NZDUSD"],
        "USDJPY": ["USDCAD"],
        "BTCUSD": ["ETHUSD", "SOLUSD"]
    }
    active_symbols = [tr['symbol'] for tr in bot.active_trades]
    if symbol in correlations:
        for related in correlations[symbol]:
            if related in active_symbols:
                return True
    return False

# -------------------------------------------------------------------
# Scanner principal
# -------------------------------------------------------------------
def scan(bot):
    if bot.is_paused(): return
    if len(bot.active_trades) >= Config.MAX_TRADES: return
    universe = all_syms() if bot.mode == "TUDO" else list(Config.MARKET_CATEGORIES[bot.mode]["assets"].keys())
    if not is_trading_session_open(): return
    if is_high_impact_news_near(): return

    for s in universe:
        cat = asset_cat(s)
        if not mkt_open(cat): continue
        if any(t["symbol"] == s for t in bot.active_trades): continue
        if any(t["symbol"] == s for t in bot.pending_trades): continue
        if time.time() - bot.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
        if check_correlation(bot, s): continue

        res = bot.trend_cache.get(s, {}).get("data") or get_analysis(s, bot.timeframe)
        if not res: continue
        if s not in bot.trend_cache:
            rev = detect_reversal(res)
            bot.trend_cache[s] = {"data": res, "reversal": {"has": rev[0], "dir": rev[1], "strength": rev[2], "reasons": rev[3]}, "ts": time.time()}
        if res["cenario"] == "NEUTRO": continue

        price = res["price"]; atr = res["atr"]; cen = res["cenario"]
        cl = asset_cat(s); cl_lbl = Config.MARKET_CATEGORIES.get(cl, {}).get("label", cl)
        eff_lev = min(bot.leverage, max_leverage_for(s))
        sl_pct, tp_pct = get_sl_tp_pct(eff_lev)

        if cen == "ALTA":
            gatilho = res["t_buy"]; dir_s = "BUY"
            sl_est = round(price * (1 - sl_pct/100), 5)
            tp_est = round(price * (1 + tp_pct/100), 5)
            preco_ok = price >= gatilho and price < res["upper"] and res["rsi"] < 70
        else:
            gatilho = res["t_sell"]; dir_s = "SELL"
            sl_est = round(price * (1 + sl_pct/100), 5)
            tp_est = round(price * (1 - tp_pct/100), 5)
            preco_ok = price <= gatilho and price > res["lower"] and res["rsi"] > 30

        if not preco_ok:
            if time.time() - bot.radar_list.get(s, 0) > Config.RADAR_COOLDOWN:
                dist = abs(price - gatilho) / price * 100
                dl = "COMPRA" if dir_s == "BUY" else "VENDA"
                bot.send(f"⚠️ RADAR – {s} ({res['name']})\n{cl_lbl} | TF: {bot.timeframe}\nTendência de {cen}\nAguardando {dl}\nGatilho: {fmt(gatilho)} | Atual: {fmt(price)} ({dist:.2f}%)\nRSI: {res['rsi']:.1f} | ADX: {res['adx']:.1f}")
                bot.radar_list[s] = time.time()
            continue

        if time.time() - bot.gatilho_list.get(s, 0) > Config.GATILHO_COOLDOWN:
            dl = "COMPRAR (BUY)" if dir_s == "BUY" else "VENDER (SELL)"
            bot.send(f"🔔 GATILHO ATINGIDO – {s} ({res['name']})\n{cl_lbl} | TF: {bot.timeframe}\nAção: {dl}\nEntrada: {fmt(price)}\nSL: {fmt(sl_est)} ({-sl_pct}%)\nTP: {fmt(tp_est)} (+{tp_pct}%)\nVerificando confluência…")
            bot.gatilho_list[s] = time.time()

        sc, tot_c, checks, passed, min_sc = calc_confluence(res, dir_s)

        # ========== INTELIGÊNCIA DE MERCADO ==========
        whale_score, whale_reasons = 0, []
        sentiment_score, sentiment_reasons = 0, []
        if asset_cat(s) == "CRYPTO":
            whale_score, whale_reasons = whale_signal_for(s)
        if bot.news_cache and isinstance(bot.news_cache, dict) and bot.news_cache.get("articles"):
            headlines = [a["title"] for a in bot.news_cache["articles"][:10]]
            sentiment_score, sentiment_reasons = analyze_sentiment(headlines)

        intel_bonus = 0
        if abs(sentiment_score) > 0.5:
            if (dir_s == "BUY" and sentiment_score > 0) or (dir_s == "SELL" and sentiment_score < 0):
                intel_bonus += 1
            else:
                intel_bonus -= 1
        if abs(whale_score) > 0.5:
            if (dir_s == "BUY" and whale_score > 0) or (dir_s == "SELL" and whale_score < 0):
                intel_bonus += 1
            else:
                intel_bonus -= 1
        sc = max(0, sc + intel_bonus)
        # ==============================================

        bar = cbar(sc, tot_c)
        conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)
        if not passed:
            falhou = [nm for nm, ok in checks if not ok]
            bot.send(f"⚡ CONFLUÊNCIA INSUF. – {s}\nScore: {sc}/{tot_c} [{bar}] (min: {min_sc})\nFalhas:\n" + "\n".join(f"   ❌ {nm}" for nm in falhou))
            continue

        rr_ratio, rr_label, premium_score, premium_reasons = calc_premium_rr(res, dir_s, sc, tot_c)
        sl_pct, tp_pct = get_sl_tp_pct(eff_lev, rr_ratio=rr_ratio)
        if dir_s == "BUY":
            sl_est = round(price * (1 - sl_pct/100), 5)
            tp_est = round(price * (1 + tp_pct/100), 5)
        else:
            sl_est = round(price * (1 + sl_pct/100), 5)
            tp_est = round(price * (1 - tp_pct/100), 5)

        bot.pending_counter += 1
        bot.last_pending_id = bot.pending_counter
        pending_trade = {
            "pending_id": bot.pending_counter,
            "symbol": s, "name": res["name"], "entry": price,
            "tp": tp_est, "sl": sl_est, "dir": dir_s,
            "peak": price, "atr": atr,
            "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
            "session_alerted": True,
            "conf_txt": conf_txt, "sc": sc, "tot_c": tot_c, "bar": bar,
            "sl_pct": sl_pct, "tp_pct": tp_pct,
            "rr_ratio": rr_ratio, "rr_label": rr_label,
            "premium_score": premium_score, "premium_reasons": premium_reasons,
        }
        bot.pending_trades.append(pending_trade)
        bot.send_pending_notification(pending_trade)
        bot.radar_list[s] = bot.gatilho_list[s] = time.time()
        save_state(bot)

# -------------------------------------------------------------------
# Scanner de reversões (Forex)
# -------------------------------------------------------------------
def scan_reversal_forex(bot):
    if bot.is_paused(): return
    if not mkt_open("FOREX"): return
    if len(bot.active_trades) >= Config.MAX_TRADES: return
    for s in Config.MARKET_CATEGORIES["FOREX"]["assets"].keys():
        if any(t["symbol"] == s for t in bot.active_trades): continue
        if any(t["symbol"] == s for t in bot.pending_trades): continue
        if time.time() - bot.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
        if time.time() - bot.reversal_list.get(s, 0) < Config.REVERSAL_COOLDOWN: continue

        res = get_reversal_analysis(s, bot.timeframe)
        if not res: continue
        price = res["price"]; atr = res["atr"]
        eff_lev = min(bot.leverage, max_leverage_for(s))
        sl_pct, tp_pct = get_sl_tp_pct(eff_lev)

        cands = []
        for d in (["SELL"] if res["signal_sell_ct"] else []) + (["BUY"] if res["signal_buy_ct"] else []):
            sc, tot_c, checks, passed, min_sc = calc_reversal_conf(res, d)
            strong_anchor = (d == "SELL" and res.get("trend_up")) or (d == "BUY" and res.get("trend_down"))
            extreme = (d == "SELL" and res["rsi_overbought"] and res["near_upper"]) or (d == "BUY" and res["rsi_oversold"] and res["near_lower"])
            rejection = (d == "SELL" and (res["div_bear"] or res["macd_div_bear"] or res["pat_bear"] or res["wick_bear"])) or (d == "BUY" and (res["div_bull"] or res["macd_div_bull"] or res["pat_bull"] or res["wick_bull"]))
            if not passed: continue
            sinais = []
            if d == "SELL":
                if res["rsi_overbought"]: sinais.append(f"RSI {res['rsi']:.0f} sobrecomprado")
                if res["near_upper"]: sinais.append("BB Superior atingida")
                if res["div_bear"]: sinais.append("RSI divergência bearish")
                if res["macd_div_bear"]: sinais.append("MACD divergência bearish")
                if res["wick_bear"]: sinais.append("Wick de rejeição")
                if res["pat_bear"] and res["pat_name"]: sinais.append(res["pat_name"])
            else:
                if res["rsi_oversold"]: sinais.append(f"RSI {res['rsi']:.0f} sobrevendido")
                if res["near_lower"]: sinais.append("BB Inferior atingida")
                if res["div_bull"]: sinais.append("RSI divergência bullish")
                if res["macd_div_bull"]: sinais.append("MACD divergência bullish")
                if res["wick_bull"]: sinais.append("Wick de rejeição")
                if res["pat_bull"] and res["pat_name"]: sinais.append(res["pat_name"])
            cands.append((sc, tot_c, checks, d, sinais))
        if not cands: continue
        cands.sort(key=lambda x: x[0], reverse=True)
        sc, tot_c, checks, dir_s, sinais = cands[0]
        bar = cbar(sc, tot_c)
        conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)

        rr_ratio, rr_label, premium_score, premium_reasons = calc_premium_rr(res, dir_s, sc, tot_c)
        sl_pct, tp_pct = get_sl_tp_pct(eff_lev, rr_ratio=rr_ratio)

        if dir_s == "BUY":
            sl = round(price * (1 - sl_pct/100), 5)
            tp = round(price * (1 + tp_pct/100), 5)
        else:
            sl = round(price * (1 + sl_pct/100), 5)
            tp = round(price * (1 - tp_pct/100), 5)
        dl = "COMPRAR (BUY) 🟢" if dir_s == "BUY" else "VENDER (SELL) 🔴"
        bot.pending_counter += 1
        bot.last_pending_id = bot.pending_counter
        pending_trade = {
            "pending_id": bot.pending_counter,
            "symbol": s, "name": res["name"],
            "entry": price, "tp": tp, "sl": sl, "dir": dir_s,
            "peak": price, "atr": atr, "tipo": "CONTRA-TENDÊNCIA ⚡",
            "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
            "session_alerted": True, "conf_txt": conf_txt, "sc": sc, "tot_c": tot_c,
            "bar": bar, "sl_pct": sl_pct, "tp_pct": tp_pct, "sinais": sinais,
            "rr_ratio": rr_ratio, "rr_label": rr_label,
            "premium_score": premium_score, "premium_reasons": premium_reasons,
        }
        bot.pending_trades.append(pending_trade)
        bot.send_pending_notification(pending_trade)
        bot.reversal_list[s] = time.time(); save_state(bot)
