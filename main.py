# -*- coding: utf-8 -*-
import os
import time
import requests
import json
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ========================================
# CONFIGURAÇÕES
# ========================================
class Config:
    BOT_TOKEN     = os.getenv("TELEGRAM_TOKEN", "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID       = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TIMEZONE   = timezone(timedelta(hours=-3))

    FOREX_ASSETS  = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS = ["BTC-USD", "ETH-USD", "SOL-USD"]

    TP_PERCENT    = 1.0    # Take Profit %
    SL_PERCENT    = 0.50   # Stop Loss %
    TIMEFRAME     = "15m"

    NEWS_INTERVAL = 7200   # Envia notícias a cada 2 horas (segundos)
    SCAN_INTERVAL = 30     # Analisa o mercado a cada 30 s


def log(msg):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ========================================
# NOTÍCIAS VIA RSS (SEM API KEY)
# ========================================

# Feeds RSS de mercado financeiro e cripto — todos gratuitos, sem cadastro
RSS_FEEDS = [
    ("Investing.com BR",  "https://br.investing.com/rss/news.rss"),
    ("CoinDesk",          "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Reuters Markets",   "https://feeds.reuters.com/reuters/businessNews"),
    ("MarketWatch",       "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("Cointelegraph",     "https://cointelegraph.com/rss"),
]

def _parse_rss(url, source_name, max_results=3):
    """Faz o parse de um feed RSS e retorna lista de artigos."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}
    r = requests.get(url, headers=headers, timeout=8)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    articles = []
    # Suporte a RSS 2.0 e Atom
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in items[:max_results]:
        title = (
            item.findtext("title") or
            item.findtext("{http://www.w3.org/2005/Atom}title") or ""
        ).strip()
        link = (
            item.findtext("link") or
            item.findtext("{http://www.w3.org/2005/Atom}link") or ""
        ).strip()
        if title and link:
            articles.append({"title": title, "url": link, "source": source_name})
    return articles


def get_news(max_results=5):
    """
    Busca notícias em múltiplos feeds RSS sem nenhuma chave de API.
    Tenta cada feed em ordem e para quando tiver resultados suficientes.
    """
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
    """Índice de Medo e Ganância (Alternative.me, gratuito)."""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6)
        data = r.json()["data"][0]
        value = data["value"]
        label = data["value_classification"]
        return f"{value} – {label}"
    except:
        return "N/D"


def build_news_message():
    """Monta o bloco HTML de notícias para o Telegram."""
    articles = get_news()
    fg = get_fear_greed()

    if not articles:
        return (
            "📰 <b>NOTÍCIAS DO MERCADO</b>\n\n"
            "Não foi possível obter notícias agora.\n"
            f"😱 <b>Fear & Greed Index:</b> {fg}"
        )

    lines = ["📰 <b>NOTÍCIAS RELEVANTES DO MERCADO</b>\n"]
    for i, a in enumerate(articles, 1):
        title = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{title}</a> <i>({a['source']})</i>")

    lines.append(f"\n😱 <b>Fear &amp; Greed Index (Cripto):</b> {fg}")
    lines.append(f"\n🕐 Atualizado às {datetime.now(Config.BR_TIMEZONE).strftime('%H:%M')} (Brasília)")
    return "\n".join(lines)


# ========================================
# MOTOR DE ANÁLISE
# ========================================
def get_analysis(symbol):
    import yfinance as yf

    # Ajuste de símbolo para yfinance
    if "-" not in symbol:
        yf_symbol = f"{symbol}=X"
    else:
        yf_symbol = symbol

    try:
        df = yf.Ticker(yf_symbol).history(period="5d", interval=Config.TIMEFRAME)
        if len(df) < 200:
            return None

        closes = df["Close"]
        highs  = df["High"]
        lows   = df["Low"]

        # EMA 200 – tendência macro
        ema200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]

        # Bandas de Bollinger 20,2
        sma20      = closes.rolling(20).mean().iloc[-1]
        std20      = closes.rolling(20).std().iloc[-1]
        upper_band = sma20 + std20 * 2
        lower_band = sma20 - std20 * 2

        # EMA 9 e 21 (média simples dos últimos N fechamentos – rápido e funcional)
        ema9  = closes.tail(9).mean()
        ema21 = closes.tail(21).mean()

        # RSI 14
        delta = closes.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs        = gain / loss
        cur_rsi   = (100 - 100 / (1 + rs)).iloc[-1]

        # ATR 14 – volatilidade real
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        cur_price   = closes.iloc[-1]
        trigger_buy  = highs.tail(5).max()
        trigger_sell = lows.tail(5).min()

        cenario = "NEUTRO"
        if cur_price > ema200 and ema9 > ema21:
            cenario = "ALTA"
        elif cur_price < ema200 and ema9 < ema21:
            cenario = "BAIXA"

        return {
            "symbol": symbol, "price": cur_price,
            "cenario": cenario, "rsi": cur_rsi, "atr": atr,
            "ema200": ema200, "upper": upper_band, "lower": lower_band,
            "t_buy": trigger_buy, "t_sell": trigger_sell,
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}")
        return None


# ========================================
# BOT PRINCIPAL
# ========================================
class TradingBot:
    def __init__(self):
        self.mode         = "CRYPTO"
        self.wins         = 0
        self.losses       = 0
        self.active_trades = []
        self.last_id      = 0
        self.radar_list   = {}
        self.last_news_ts = 0   # controle do envio automático de notícias

    # ------ Telegram helpers ------
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
            log(f"[SEND] Erro: {e}")

    def build_menu(self):
        markup = {"inline_keyboard": [
            [{"text": f"📍 Mercado: {self.mode}", "callback_data": "ignore"}],
            [{"text": "📈 FOREX",   "callback_data": "set_fx"},
             {"text": "₿ CRIPTO",  "callback_data": "set_crypto"}],
            [{"text": "📰 NOTÍCIAS", "callback_data": "news"},
             {"text": "🔄 ATUALIZAR", "callback_data": "refresh"}],
        ]}
        total    = self.wins + self.losses
        winrate  = (self.wins / total * 100) if total > 0 else 0
        fg       = get_fear_greed()
        msg = (
            f"<b>🎛 BOT SNIPER – ESTRATÉGIA CURINGA</b>\n"
            f"Placar: <code>{self.wins}W – {self.losses}L</code> ({winrate:.1f}%)\n"
            f"Modo: <b>{self.mode}</b>  |  Timeframe: <code>{Config.TIMEFRAME}</code>\n"
            f"Gestão: 2x1  (TP {Config.TP_PERCENT}%  |  SL {Config.SL_PERCENT}%)\n"
            f"😱 Fear &amp; Greed: <b>{fg}</b>"
        )
        self.send(msg, markup)

    # ------ Notícias ------
    def send_news(self):
        log("📰 Enviando notícias...")
        msg = build_news_message()
        self.send(msg, disable_preview=True)
        self.last_news_ts = time.time()

    def maybe_send_news(self):
        """Envia notícias automaticamente no intervalo configurado."""
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL:
            self.send_news()

    # ------ Scan de mercado ------
    def scan(self):
        log(f"🔎 Varrendo {self.mode}...")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS

        for s in universe:
            if any(t["symbol"] == s for t in self.active_trades):
                continue

            res = get_analysis(s)
            if not res or res["cenario"] == "NEUTRO":
                continue

            price = res["price"]
            atr   = res.get("atr", 0)

            # RADAR – alerta antes do rompimento
            last_alert = self.radar_list.get(s, 0)
            if time.time() - last_alert > 1800:
                gatilho = res["t_buy"] if res["cenario"] == "ALTA" else res["t_sell"]
                self.send(
                    f"⚠️ <b>RADAR SNIPER: {s}</b>\n"
                    f"Tendência macro de <b>{res['cenario']}</b> (EMA 200 confirmada).\n"
                    f"Aguardando rompimento em <code>{gatilho:.5f}</code>.\n"
                    f"📊 ATR(14): <code>{atr:.5f}</code>  |  RSI: <code>{res['rsi']:.1f}</code>"
                )
                self.radar_list[s] = time.time()

            # GATILHO – sinal de entrada
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

            if pode_comprar or pode_vender:
                dir_label  = "BUY 🟢" if pode_comprar else "SELL 🔴"
                dir_simple = "BUY"    if pode_comprar else "SELL"

                mult = 1 + Config.TP_PERCENT / 100 if dir_simple == "BUY" else 1 - Config.TP_PERCENT / 100
                tp   = price * mult
                sl_m = 1 - Config.SL_PERCENT / 100 if dir_simple == "BUY" else 1 + Config.SL_PERCENT / 100
                sl   = price * sl_m

                self.send(
                    f"🎯 <b>SINAL CONFIRMADO (ROMPIMENTO)</b>\n\n"
                    f"Ativo: <b>{s}</b>\n"
                    f"Ação: {dir_label}\n"
                    f"Entrada: <code>{price:.5f}</code>\n"
                    f"📊 ATR(14): <code>{atr:.5f}</code>  |  RSI: <code>{res['rsi']:.1f}</code>\n"
                    f"──────────────────\n"
                    f"🎯 Take Profit: <code>{tp:.5f}</code>\n"
                    f"🛡 Stop Loss:   <code>{sl:.5f}</code>"
                )
                self.active_trades.append({
                    "symbol": s, "entry": price, "tp": tp, "sl": sl, "dir": dir_simple
                })
                self.radar_list[s] = time.time()

    # ------ Monitor de trades abertos ------
    def monitor_trades(self):
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"])
            if not res:
                continue
            cur = res["price"]

            is_win  = (t["dir"] == "BUY"  and cur >= t["tp"]) or (t["dir"] == "SELL" and cur <= t["tp"])
            is_loss = (t["dir"] == "BUY"  and cur <= t["sl"]) or (t["dir"] == "SELL" and cur >= t["sl"])

            if is_win or is_loss:
                status = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                if is_win:  self.wins   += 1
                else:       self.losses += 1

                pnl_pct = (cur - t["entry"]) / t["entry"] * 100
                if t["dir"] == "SELL":
                    pnl_pct = -pnl_pct

                self.send(
                    f"🏁 <b>OPERAÇÃO ENCERRADA</b>\n"
                    f"Ativo: {t['symbol']}  |  {t['dir']}\n"
                    f"Resultado: <b>{status}</b>\n\n"
                    f"Entrada: <code>{t['entry']:.5f}</code>\n"
                    f"Saída:   <code>{cur:.5f}</code>\n"
                    f"P&amp;L: <code>{pnl_pct:+.2f}%</code>"
                )
                self.active_trades.remove(t)
                self.build_menu()


# ========================================
# INICIALIZAÇÃO
# ========================================
def main():
    log("🔌 Iniciando Bot Sniper – Estratégia Curinga...")
    requests.get(
        f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook",
        timeout=8
    )
    bot = TradingBot()
    bot.build_menu()
    bot.send_news()   # Envia notícias logo ao iniciar

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

                    # Comandos via texto
                    if "message" in u:
                        text = u["message"].get("text", "").strip().lower()
                        if text in ("/noticias", "/news", "notícias"):
                            bot.send_news()
                        elif text == "/menu":
                            bot.build_menu()

                    # Botões inline
                    if "callback_query" in u:
                        data = u["callback_query"]["data"]
                        cid  = u["callback_query"]["id"]
                        # Responde o callback para remover o "carregando"
                        requests.post(
                            f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery",
                            json={"callback_query_id": cid},
                            timeout=5,
                        )
                        if data == "set_fx":
                            bot.mode = "FOREX"
                        elif data == "set_crypto":
                            bot.mode = "CRYPTO"
                        elif data == "news":
                            bot.send_news()
                        # "refresh" e "ignore" apenas recarregam o menu
                        bot.build_menu()

            bot.maybe_send_news()
            bot.scan()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)

        except Exception as e:
            log(f"Erro no loop principal: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
