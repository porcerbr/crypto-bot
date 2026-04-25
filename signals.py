# signals.py
import time
from datetime import datetime
from config import Config
from utils import log, fmt, all_syms, mkt_open, asset_cat, asset_name, max_leverage_for
from analysis import get_analysis, calc_confluence, cbar, calc_premium_rr, detect_reversal, get_reversal_analysis, calc_reversal_conf
from risk import get_sl_tp_pct, commission_for
from db import save_state

def scan(bot):
    if bot.is_paused(): return
    if len(bot.active_trades) >= Config.MAX_TRADES: return
    universe = all_syms() if bot.mode == "TUDO" else list(Config.MARKET_CATEGORIES[bot.mode]["assets"].keys())
    # ── Filtro de Sessão ─────────────────────────
    from session_filter import is_trading_session_open
    if not is_trading_session_open():
        return  # sai silenciosamente se fora do horário

    # ── Filtro de Notícias ───────────────────────
    from news_filter import is_high_impact_news_near
    if is_high_impact_news_near():
        log("⏸️ Sessão pausada — evento de alto impacto próximo.")
        return
    for s in universe:
        cat = asset_cat(s)
        if not mkt_open(cat): continue
        if any(t["symbol"] == s for t in bot.active_trades): continue
        if any(t["symbol"] == s for t in bot.pending_trades): continue
        if time.time() - bot.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
        # Verificar correlação
        if check_correlation(bot, s):
            continue
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
                bot.send(
                    f"⚠️ <b>RADAR – {s}</b> ({res['name']})\n"
                    f"{cl_lbl} | TF: <code>{bot.timeframe}</code>\n\n"
                    f"Tendência de <b>{cen}</b> detectada\n"
                    f"Aguardando gatilho de <b>{dl}</b>\n\n"
                    f"🎯 Gatilho: <code>{fmt(gatilho)}</code>\n"
                    f"📍 Atual: <code>{fmt(price)}</code> ({dist:.2f}%)\n"
                    f"🛡 SL: <code>-{sl_pct}%</code> | 🎯 TP: <code>+{tp_pct}%</code>\n"
                    f"RSI: <code>{res['rsi']:.1f}</code> | ADX: <code>{res['adx']:.1f}</code>"
                )
                bot.radar_list[s] = time.time()
            continue

        if time.time() - bot.gatilho_list.get(s, 0) > Config.GATILHO_COOLDOWN:
            dl = "COMPRAR (BUY) 🟢" if dir_s == "BUY" else "VENDER (SELL) 🔴"
            bot.send(
                f"🔔 <b>GATILHO ATINGIDO – {s}</b> ({res['name']})\n"
                f"{cl_lbl} | TF: <code>{bot.timeframe}</code>\n\n"
                f"✅ Preço chegou no nível de entrada!\n\n"
                f"▶️ <b>AÇÃO: {dl}</b>\n\n"
                f"💰 Entrada: <code>{fmt(price)}</code>\n"
                f"🛡 SL: <code>{fmt(sl_est)}</code> ({-sl_pct}%)\n"
                f"🎯 TP: <code>{fmt(tp_est)}</code> (+{tp_pct}%)\n\n"
                f"⏳ <i>Verificando confluência…</i>"
            )
            bot.gatilho_list[s] = time.time()

        sc, tot_c, checks, passed, min_sc = calc_confluence(res, dir_s)
        bar = cbar(sc, tot_c)
        conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)
        if not passed:
            falhou = [nm for nm, ok in checks if not ok]
            bot.send(
                f"⚡ <b>CONFLUÊNCIA INSUF. – {s}</b>\n\n"
                f"Gatilho atingido mas bot NÃO entrou.\n"
                f"Score: <code>{sc}/{tot_c}</code> [{bar}] (min: {min_sc})\n\n"
                f"<b>Filtros que falharam:</b>\n" + "\n".join(f"   ❌ {nm}" for nm in falhou)
            )
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
            "created_at": time.time(),
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
            if not passed:
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
        sc, tc, ch, dir_s, sinais = cands[0]
        bar = cbar(sc, tc)
        conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in ch)

        rr_ratio, rr_label, premium_score, premium_reasons = calc_premium_rr(res, dir_s, sc, tc)
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
            "pending_id": bot.pending_counter, "symbol": s, "name": res["name"],
            "entry": price, "tp": tp, "sl": sl, "dir": dir_s,
            "peak": price, "atr": atr, "tipo": "CONTRA-TENDÊNCIA ⚡",
            "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
            "created_at": time.time(),
            "session_alerted": True, "conf_txt": conf_txt, "sc": sc, "tc": tc,
            "bar": bar, "sl_pct": sl_pct, "tp_pct": tp_pct, "sinais": sinais,
            "rr_ratio": rr_ratio, "rr_label": rr_label,
            "premium_score": premium_score, "premium_reasons": premium_reasons,
        }
        bot.pending_trades.append(pending_trade)
        bot.send_pending_notification(pending_trade)
        bot.reversal_list[s] = time.time(); save_state(bot)

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
