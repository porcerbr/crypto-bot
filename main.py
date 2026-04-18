# -*- coding: utf-8 -*-
"""
BOT SNIPER – ESTRATÉGIA CURINGA (v3.0)
Melhorias: EMA real, persistência, MACD, Volume, Trailing Stop,
           horário de mercado, /status, /placar, nível de confiança.
"""
import os, time, json, math, requests, pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ========================================
# CONFIGURAÇÕES
# ========================================
class Config:
    BOT_TOKEN      = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TIMEZONE    = timezone(timedelta(hours=-3))

    FOREX_ASSETS   = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS  = ["BTC-USD", "ETH-USD", "SOL-USD"]

    TP_PERCENT     = 1.0    # Take Profit %
    SL_PERCENT     = 0.50   # Stop Loss %
    TIMEFRAME      = "15m"

    NEWS_INTERVAL  = 7200   # Notícias automáticas a cada 2 h
    SCAN_INTERVAL  = 30     # Scan a cada 30 s

    STATE_FILE     = "bot_state.json"   # Persistência local

    # Horário de liquidez FOREX (UTC): 07h–17h (Londres + NY abertas)
    FOREX_OPEN_UTC  = 7
    FOREX_CLOSE_UTC = 17

    # Mínimo de confluências para disparar sinal (de 5 possíveis)
    MIN_CONFLUENCE  = 3


def log(msg):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ========================================
# PERSISTÊNCIA (JSON)
# ========================================
def save_state(bot):
    data = {
        "wins":          bot.wins,
        "losses":        bot.losses,
        "active_trades": bot.active_trades,
        "radar_list":    bot.radar_list,
        "history":       bot.history,
    }
    try:
        with open(Config.STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"[STATE] Erro ao salvar: {e}")


def load_state(bot):
    if not os.path.exists(Config.STATE_FILE):
        return
    try:
        with open(Config.STATE_FILE) as f:
            data = json.load(f)
        bot.wins          = data.get("wins", 0)
        bot.losses        = data.get("losses", 0)
        bot.active_trades = data.get("active_trades", [])
        bot.radar_list    = data.get("radar_list", {})
        bot.history       = data.get("history", [])
        log(f"[STATE] Restaurado: {bot.wins}W / {bot.losses}L | {len(bot.active_trades)} trade(s) ativo(s)")
    except Exception as e:
        log(f"[STATE] Erro ao carregar: {e}")


# ========================================
# NOTÍCIAS VIA RSS (SEM API KEY)
# ========================================
RSS_FEEDS = [
    ("Investing.com BR", "https://br.investing.com/rss/news.rss"),
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Reuters Markets",  "https://feeds.reuters.com/reuters/businessNews"),
    ("MarketWatch",      "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("Cointelegraph",    "https://cointelegraph.com/rss"),
]

def _parse_rss(url, source_name, max_results=3):
    headers  = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}
    r        = requests.get(url, headers=headers, timeout=8)
    r.raise_for_status()
    root     = ET.fromstring(r.content)
    items    = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    articles = []
    for item in items[:max_results]:
        title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link  = (item.findtext("link")  or item.findtext("{http://www.w3.org/2005/Atom}link")  or "").strip()
        if title and link:
            articles.append({"title": title, "url": link, "source": source_name})
    return articles

def get_news(max_results=5):
    articles = []
    for source_name, url in RSS_FEEDS:
        if len(articles) >= max_results:
            break
        try:
            fetched = _parse_rss(url, source_name, max_results=2)
            articles.extend(fetched)
            log(f"[RSS] {source_name}: {len(fetched)} notícia(s)")
        except Exception as e:
            log(f"[RSS] {source_name} falhou: {e}")
    return articles[:max_results]

def get_fear_greed():
    try:
        r    = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6)
        data = r.json()["data"][0]
        return f"{data['value']} – {data['value_classification']}"
    except:
        return "N/D"

def build_news_message():
    articles = get_news()
    fg       = get_fear_greed()
    if not articles:
        return (
            "📰 <b>NOTÍCIAS DO MERCADO</b>\n\n"
            "Nenhum feed disponível no momento.\n"
            f"😱 <b>Fear &amp; Greed:</b> {fg}"
        )
    lines = ["📰 <b>NOTÍCIAS RELEVANTES DO MERCADO</b>\n"]
    for i, a in enumerate(articles, 1):
        title = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{title}</a> <i>({a['source']})</i>")
    lines.append(f"\n😱 <b>Fear &amp; Greed (Cripto):</b> {fg}")
    lines.append(f"🕐 {datetime.now(Config.BR_TIMEZONE).strftime('%H:%M')} (Brasília)")
    return "\n".join(lines)


# ========================================
# HORÁRIO DE MERCADO
# ========================================
def forex_market_open():
    """Retorna True se estiver dentro do horário de liquidez FOREX (UTC)."""
    hour_utc = datetime.now(timezone.utc).hour
    return Config.FOREX_OPEN_UTC <= hour_utc < Config.FOREX_CLOSE_UTC


# ========================================
# MOTOR DE ANÁLISE
# ========================================
def get_analysis(symbol):
    import yfinance as yf

    yf_symbol = f"{symbol}=X" if "-" not in symbol else symbol

    try:
        df = yf.Ticker(yf_symbol).history(period="5d", interval=Config.TIMEFRAME)
        if len(df) < 200:
            return None

        closes = df["Close"]
        highs  = df["High"]
        lows   = df["Low"]
        volume = df["Volume"]

        # ── EMA verdadeira (ewm) ──────────────────────────────
        ema9   = closes.ewm(span=9,   adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21,  adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]

        # ── Bandas de Bollinger 20,2 ──────────────────────────
        sma20      = closes.rolling(20).mean().iloc[-1]
        std20      = closes.rolling(20).std().iloc[-1]
        upper_band = sma20 + std20 * 2
        lower_band = sma20 - std20 * 2

        # ── RSI 14 ───────────────────────────────────────────
        delta   = closes.diff()
        gain    = delta.where(delta > 0, 0).rolling(14).mean()
        loss    = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs      = gain / loss
        cur_rsi = (100 - 100 / (1 + rs)).iloc[-1]

        # ── MACD (12, 26, 9) ─────────────────────────────────
        ema12       = closes.ewm(span=12, adjust=False).mean()
        ema26       = closes.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist   = macd_line - signal_line
        macd_bull   = macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2]
        macd_bear   = macd_hist.iloc[-1] < 0 and macd_hist.iloc[-1] < macd_hist.iloc[-2]

        # ── Volume (acima da média de 20 períodos) ────────────
        vol_avg = volume.rolling(20).mean().iloc[-1]
        vol_cur = volume.iloc[-1]
        vol_ok  = bool(vol_cur > vol_avg) if vol_avg > 0 else False
        vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 0

        # ── ATR 14 ───────────────────────────────────────────
        tr  = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        cur_price    = closes.iloc[-1]
        trigger_buy  = highs.tail(5).max()
        trigger_sell = lows.tail(5).min()

        # ── Cenário base ─────────────────────────────────────
        cenario = "NEUTRO"
        if cur_price > ema200 and ema9 > ema21:
            cenario = "ALTA"
        elif cur_price < ema200 and ema9 < ema21:
            cenario = "BAIXA"

        return {
            "symbol": symbol, "price": cur_price, "cenario": cenario,
            "rsi": cur_rsi, "atr": atr,
            "ema9": ema9, "ema21": ema21, "ema200": ema200,
            "upper": upper_band, "lower": lower_band,
            "macd_bull": macd_bull, "macd_bear": macd_bear,
            "vol_ok": vol_ok, "vol_ratio": vol_ratio,
            "t_buy": trigger_buy, "t_sell": trigger_sell,
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}")
        return None


def calc_confluence(res, direcao):
    """Conta confluências. Retorna (score, total, lista de checks)."""
    if direcao == "BUY":
        checks = [
            ("EMA 200",    res["price"] > res["ema200"]),
            ("EMA 9 > 21", res["ema9"]  > res["ema21"]),
            ("MACD Alta",  res["macd_bull"]),
            ("Volume",     res["vol_ok"]),
            ("RSI < 65",   res["rsi"] < 65),
        ]
    else:
        checks = [
            ("EMA 200",    res["price"] < res["ema200"]),
            ("EMA 9 < 21", res["ema9"]  < res["ema21"]),
            ("MACD Baixa", res["macd_bear"]),
            ("Volume",     res["vol_ok"]),
            ("RSI > 35",   res["rsi"] > 35),
        ]
    score = sum(1 for _, ok in checks if ok)
    return score, len(checks), checks


def confluence_bar(score, total):
    filled = math.floor(score / total * 5)
    return "█" * filled + "░" * (5 - filled)


# ========================================
# BOT PRINCIPAL
# ========================================
class TradingBot:
    def __init__(self):
        self.mode          = "CRYPTO"
        self.wins          = 0
        self.losses        = 0
        self.active_trades = []
        self.radar_list    = {}
        self.history       = []
        self.last_id       = 0
        self.last_news_ts  = 0

    # ── Telegram ──────────────────────────────────────────────
    def send(self, text, markup=None, disable_preview=False):
        url     = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": Config.CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if markup:
            payload["reply_markup"] = json.dumps(markup)
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            log(f"[SEND] {e}")

    # ── Menu ──────────────────────────────────────────────────
    def build_menu(self):
        markup = {"inline_keyboard": [
            [{"text": f"📍 Mercado: {self.mode}", "callback_data": "ignore"}],
            [{"text": "📈 FOREX",     "callback_data": "set_fx"},
             {"text": "₿ CRIPTO",    "callback_data": "set_crypto"}],
            [{"text": "📊 Status",    "callback_data": "status"},
             {"text": "🏆 Placar",    "callback_data": "placar"}],
            [{"text": "📰 Notícias",  "callback_data": "news"},
             {"text": "🔄 Atualizar", "callback_data": "refresh"}],
        ]}
        total        = self.wins + self.losses
        winrate      = (self.wins / total * 100) if total > 0 else 0
        fg           = get_fear_greed()
        forex_status = "🟢 Aberto" if forex_market_open() else "🔴 Fechado"
        msg = (
            f"<b>🎛 BOT SNIPER – ESTRATÉGIA CURINGA v3</b>\n"
            f"Placar: <code>{self.wins}W – {self.losses}L</code> ({winrate:.1f}%)\n"
            f"Modo: <b>{self.mode}</b>  |  TF: <code>{Config.TIMEFRAME}</code>\n"
            f"Gestão: 2x1  (TP {Config.TP_PERCENT}%  |  SL {Config.SL_PERCENT}%)\n"
            f"FOREX: {forex_status}\n"
            f"😱 Fear &amp; Greed: <b>{fg}</b>"
        )
        self.send(msg, markup)

    # ── Notícias ──────────────────────────────────────────────
    def send_news(self):
        log("📰 Enviando notícias...")
        self.send(build_news_message(), disable_preview=True)
        self.last_news_ts = time.time()

    def maybe_send_news(self):
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL:
            self.send_news()

    # ── /status ───────────────────────────────────────────────
    def send_status(self):
        if not self.active_trades:
            self.send("📊 <b>STATUS</b>\n\nNenhuma operação aberta no momento.")
            return
        lines = ["📊 <b>OPERAÇÕES ABERTAS</b>\n"]
        for t in self.active_trades:
            res = get_analysis(t["symbol"])
            cur = res["price"] if res else t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL":
                pnl = -pnl
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"{emoji} <b>{t['symbol']}</b> {t['dir']} | desde {t.get('opened_at','?')}\n"
                f"   Entrada: <code>{t['entry']:.5f}</code>  Atual: <code>{cur:.5f}</code>\n"
                f"   P&amp;L: <code>{pnl:+.2f}%</code>  "
                f"SL: <code>{t['sl']:.5f}</code>  TP: <code>{t['tp']:.5f}</code>"
            )
        self.send("\n".join(lines))

    # ── /placar ───────────────────────────────────────────────
    def send_placar(self):
        total   = self.wins + self.losses
        winrate = (self.wins / total * 100) if total > 0 else 0
        lines   = [
            "<b>🏆 PLACAR DETALHADO</b>\n",
            f"✅ Wins:    <code>{self.wins}</code>",
            f"❌ Losses:  <code>{self.losses}</code>",
            f"📊 Total:   <code>{total}</code>",
            f"🎯 Winrate: <code>{winrate:.1f}%</code>",
        ]
        if self.history:
            lines.append("\n<b>Últimas 5 operações:</b>")
            for h in self.history[-5:][::-1]:
                icon = "✅" if h["result"] == "WIN" else "❌"
                lines.append(
                    f"{icon} {h['symbol']} {h['dir']}  "
                    f"P&amp;L: <code>{h['pnl']:+.2f}%</code>  {h['closed_at']}"
                )
        self.send("\n".join(lines))

    # ── Scan ──────────────────────────────────────────────────
    def scan(self):
        if self.mode == "FOREX" and not forex_market_open():
            log("⏸ FOREX fora do horário de liquidez.")
            return

        log(f"🔎 Varrendo {self.mode}...")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS

        for s in universe:
            if any(t["symbol"] == s for t in self.active_trades):
                continue

            res = get_analysis(s)
            if not res or res["cenario"] == "NEUTRO":
                continue

            price = res["price"]

            # ── RADAR ─────────────────────────────────────────
            last_alert = self.radar_list.get(s, 0)
            if time.time() - last_alert > 1800:
                gatilho = res["t_buy"] if res["cenario"] == "ALTA" else res["t_sell"]
                macd_icon = "🟢" if res["macd_bull"] else ("🔴" if res["macd_bear"] else "⚪")
                self.send(
                    f"⚠️ <b>RADAR SNIPER: {s}</b>\n"
                    f"Tendência de <b>{res['cenario']}</b> (EMA 200 confirmada)\n"
                    f"Gatilho: <code>{gatilho:.5f}</code>  |  ATR: <code>{res['atr']:.5f}</code>\n"
                    f"RSI: <code>{res['rsi']:.1f}</code>  |  MACD: {macd_icon}"
                )
                self.radar_list[s] = time.time()

            # ── GATILHO ────────────────────────────────────────
            pode_comprar = (
                res["cenario"] == "ALTA"
                and price >= res["t_buy"]
                and price < res["upper"]
                and res["rsi"] < 70
            )
            pode_vender = (
                res["cenario"] == "BAIXA"
                and price <= res["t_sell"]
                and price > res["lower"]
                and res["rsi"] > 30
            )
            if not (pode_comprar or pode_vender):
                continue

            dir_simple = "BUY" if pode_comprar else "SELL"

            # ── CONFLUÊNCIA ────────────────────────────────────
            score, total_c, checks = calc_confluence(res, dir_simple)
            if score < Config.MIN_CONFLUENCE:
                log(f"[SINAL] {s} {dir_simple} ignorado – confluência {score}/{total_c}")
                continue

            bar       = confluence_bar(score, total_c)
            conf_txt  = "\n".join(f"   {'✅' if ok else '❌'} {name}" for name, ok in checks)
            vol_txt   = f"{res['vol_ratio']:.1f}x média" if res["vol_ratio"] > 0 else "N/D"

            mult = 1 + Config.TP_PERCENT / 100 if dir_simple == "BUY" else 1 - Config.TP_PERCENT / 100
            tp   = price * mult
            sl_m = 1 - Config.SL_PERCENT / 100 if dir_simple == "BUY" else 1 + Config.SL_PERCENT / 100
            sl   = price * sl_m

            dir_label = "BUY 🟢" if dir_simple == "BUY" else "SELL 🔴"

            self.send(
                f"🎯 <b>SINAL CONFIRMADO – {s}</b>\n\n"
                f"Ação: <b>{dir_label}</b>\n"
                f"Entrada: <code>{price:.5f}</code>\n"
                f"ATR(14): <code>{res['atr']:.5f}</code>  |  RSI: <code>{res['rsi']:.1f}</code>\n"
                f"Volume:  <code>{vol_txt}</code>\n"
                f"──────────────────────\n"
                f"🎯 Take Profit: <code>{tp:.5f}</code>\n"
                f"🛡 Stop Loss:   <code>{sl:.5f}</code>\n"
                f"──────────────────────\n"
                f"<b>Confluência: {score}/{total_c}  [{bar}]</b>\n"
                f"{conf_txt}"
            )

            self.active_trades.append({
                "symbol": s, "entry": price, "tp": tp, "sl": sl,
                "dir": dir_simple, "peak": price,
                "opened_at": datetime.now(Config.BR_TIMEZONE).strftime("%d/%m %H:%M"),
            })
            self.radar_list[s] = time.time()
            save_state(self)

    # ── Monitor + Trailing Stop ────────────────────────────────
    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"])
            if not res:
                continue
            cur = res["price"]

            # Trailing Stop
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl = cur * (1 - Config.SL_PERCENT / 100)
                if new_sl > t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL: {t['sl']:.5f} → {new_sl:.5f}")
                    t["sl"] = new_sl
                    changed = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl = cur * (1 + Config.SL_PERCENT / 100)
                if new_sl < t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL: {t['sl']:.5f} → {new_sl:.5f}")
                    t["sl"] = new_sl
                    changed = True

            # Encerramento
            is_win  = (t["dir"] == "BUY"  and cur >= t["tp"]) or (t["dir"] == "SELL" and cur <= t["tp"])
            is_loss = (t["dir"] == "BUY"  and cur <= t["sl"]) or (t["dir"] == "SELL" and cur >= t["sl"])

            if is_win or is_loss:
                status = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                if is_win:  self.wins   += 1
                else:       self.losses += 1

                pnl = (cur - t["entry"]) / t["entry"] * 100
                if t["dir"] == "SELL":
                    pnl = -pnl

                closed_at = datetime.now(Config.BR_TIMEZONE).strftime("%d/%m %H:%M")
                self.history.append({
                    "symbol": t["symbol"], "dir": t["dir"],
                    "result": "WIN" if is_win else "LOSS",
                    "pnl": round(pnl, 2), "closed_at": closed_at,
                })

                self.send(
                    f"🏁 <b>OPERAÇÃO ENCERRADA</b>\n"
                    f"Ativo: <b>{t['symbol']}</b>  |  {t['dir']}\n"
                    f"Resultado: <b>{status}</b>\n\n"
                    f"Entrada: <code>{t['entry']:.5f}</code>\n"
                    f"Saída:   <code>{cur:.5f}</code>\n"
                    f"P&amp;L:  <code>{pnl:+.2f}%</code>"
                )
                self.active_trades.remove(t)
                changed = True
                self.build_menu()

        if changed:
            save_state(self)


# ========================================
# LOOP PRINCIPAL
# ========================================
def main():
    log("🔌 Iniciando Bot Sniper v3 – Estratégia Curinga...")
    requests.get(
        f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook",
        timeout=8
    )
    bot = TradingBot()
    load_state(bot)   # Restaura estado salvo
    bot.build_menu()
    bot.send_news()

    while True:
        try:
            url = (
                f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                f"/getUpdates?offset={bot.last_id + 1}&timeout=5"
            )
            r = requests.get(url, timeout=12).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]

                    # Comandos de texto
                    if "message" in u:
                        text = u["message"].get("text", "").strip().lower()
                        if text in ("/noticias", "/news"):
                            bot.send_news()
                        elif text == "/status":
                            bot.send_status()
                        elif text in ("/placar", "/score"):
                            bot.send_placar()
                        elif text in ("/menu", "/start"):
                            bot.build_menu()

                    # Botões inline
                    if "callback_query" in u:
                        data = u["callback_query"]["data"]
                        cid  = u["callback_query"]["id"]
                        requests.post(
                            f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cid}, timeout=5,
                        )
                        if data == "set_fx":
                            bot.mode = "FOREX"
                        elif data == "set_crypto":
                            bot.mode = "CRYPTO"
                        elif data == "news":
                            bot.send_news(); continue
                        elif data == "status":
                            bot.send_status(); continue
                        elif data == "placar":
                            bot.send_placar(); continue
                        bot.build_menu()

            bot.maybe_send_news()
            bot.scan()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)

        except Exception as e:
            log(f"Erro no loop: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
