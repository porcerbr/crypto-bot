# -*- coding: utf-8 -*-
"""
BOT SNIPER v7 — Multi-mercado + API HTTP + Dashboard PWA
═════════════════════════════════════════════════════════
NOVIDADES v7:
  • API HTTP embutida (Flask) servindo dashboard + JSON
  • HTML/PWA servido direto pelo próprio bot (1 único app)
  • NOVO: /api/trends → tendência em tempo real de TODOS os ativos
  • NOVO: /api/reversals → detecção de possíveis contra-tendências
  • Dashboard com 6 abas: Dash / Tendências / Reversões / Histórico / Trades / Config
"""
import os, time, json, math, threading, requests
import pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

# ══════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════
class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ      = timezone(timedelta(hours=-3))

    MARKET_CATEGORIES = {
        "FOREX": {
            "label": "📈 FOREX",
            "assets": {
                "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
                "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
                "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
                "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
                "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY",
            },
        },
        "CRYPTO": {
            "label": "₿ CRIPTO",
            "assets": {
                "BTC-USD":   "Bitcoin",   "ETH-USD":   "Ethereum",
                "SOL-USD":   "Solana",    "BNB-USD":   "BNB",
                "XRP-USD":   "XRP",       "ADA-USD":   "Cardano",
                "DOGE-USD":  "Dogecoin",  "AVAX-USD":  "Avalanche",
                "LINK-USD":  "Chainlink", "DOT-USD":   "Polkadot",
                "MATIC-USD": "Polygon",   "LTC-USD":   "Litecoin",
            },
        },
        "COMMODITIES": {
            "label": "🏅 COMMODITIES",
            "assets": {
                "GC=F": "Ouro",          "SI=F": "Prata",
                "CL=F": "Petróleo WTI",  "BZ=F": "Petróleo Brent",
                "NG=F": "Gás Natural",   "HG=F": "Cobre",
                "ZC=F": "Milho",         "ZW=F": "Trigo",
                "ZS=F": "Soja",          "PL=F": "Platina",
            },
        },
        "INDICES": {
            "label": "📊 ÍNDICES",
            "assets": {
                "ES=F":   "S&P 500",    "NQ=F":   "Nasdaq 100",
                "YM=F":   "Dow Jones",  "RTY=F":  "Russell 2000",
                "^GDAXI": "DAX",        "^FTSE":  "FTSE 100",
                "^N225":  "Nikkei",     "^BVSP":  "IBOVESPA",
                "^HSI":   "Hang Seng",  "^STOXX50E": "Euro Stoxx 50",
            },
        },
    }

    ATR_MULT_SL    = 1.5
    ATR_MULT_TP    = 3.0
    ATR_MULT_TRAIL = 1.2

    MAX_CONSECUTIVE_LOSSES = 2
    PAUSE_DURATION         = 3600

    ADX_MIN        = 22
    MAX_TRADES     = 3
    ASSET_COOLDOWN = 3600
    MIN_CONFLUENCE = 5

    RADAR_COOLDOWN   = 1800
    GATILHO_COOLDOWN = 300

    TIMEFRAMES = {
        "1m":  ("🔴 Agressivo",    "7d"),
        "5m":  ("🟠 Alto",         "5d"),
        "15m": ("🟡 Moderado",     "5d"),
        "30m": ("🟢 Conservador",  "5d"),
        "1h":  ("🔵 Seguro",       "60d"),
        "4h":  ("🟣 Muito Seguro", "60d"),
    }
    TIMEFRAME = "15m"

    FOREX_OPEN_UTC  = 7;  FOREX_CLOSE_UTC = 17
    COMM_OPEN_UTC   = 7;  COMM_CLOSE_UTC  = 21
    IDX_OPEN_UTC    = 7;  IDX_CLOSE_UTC   = 21

    NEWS_INTERVAL   = 7200
    SCAN_INTERVAL   = 30
    TRENDS_INTERVAL = 120   # atualiza cache de tendências a cada 2min
    STATE_FILE      = "bot_state.json"


def fmt(price: float) -> str:
    if price == 0: return "0"
    if price >= 1000: return f"{price:,.2f}"
    if price >= 10:   return f"{price:.4f}"
    if price >= 1:    return f"{price:.5f}"
    return f"{price:.6f}"


def log(msg):
    ts = datetime.now(Config.BR_TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ══════════════════════════════════════════════════════════════════
# HELPERS DE SÍMBOLO E MERCADO
# ══════════════════════════════════════════════════════════════════
def to_yf_symbol(symbol: str) -> str:
    if "-" in symbol: return symbol
    if symbol.startswith("^"): return symbol
    if symbol.endswith("=F"):  return symbol
    return f"{symbol}=X"

def asset_category(symbol: str) -> str:
    for cat, info in Config.MARKET_CATEGORIES.items():
        if symbol in info["assets"]:
            return cat
    return "CRYPTO"

def asset_name(symbol: str) -> str:
    for info in Config.MARKET_CATEGORIES.values():
        if symbol in info["assets"]:
            return info["assets"][symbol]
    return symbol

def volume_reliable(symbol: str) -> bool:
    return asset_category(symbol) not in ("INDICES",)

def all_symbols() -> list:
    syms = []
    for cat in Config.MARKET_CATEGORIES.values():
        syms.extend(cat["assets"].keys())
    return syms

def market_open(category: str) -> bool:
    now = datetime.now(timezone.utc)
    h, wd = now.hour, now.weekday()
    if category == "CRYPTO": return True
    if wd >= 5: return False
    if category == "FOREX":       return Config.FOREX_OPEN_UTC <= h < Config.FOREX_CLOSE_UTC
    if category == "COMMODITIES": return Config.COMM_OPEN_UTC  <= h < Config.COMM_CLOSE_UTC
    if category == "INDICES":     return Config.IDX_OPEN_UTC   <= h < Config.IDX_CLOSE_UTC
    return True


# ══════════════════════════════════════════════════════════════════
# PERSISTÊNCIA
# ══════════════════════════════════════════════════════════════════
def save_state(bot):
    data = {
        "mode": bot.mode, "timeframe": bot.timeframe,
        "wins": bot.wins, "losses": bot.losses,
        "consecutive_losses": bot.consecutive_losses,
        "paused_until": bot.paused_until,
        "active_trades": bot.active_trades,
        "radar_list": bot.radar_list,
        "gatilho_list": bot.gatilho_list,
        "asset_cooldown": bot.asset_cooldown,
        "history": bot.history,
    }
    try:
        with open(Config.STATE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"[STATE] Erro ao salvar: {e}")

def load_state(bot):
    if not os.path.exists(Config.STATE_FILE): return
    try:
        with open(Config.STATE_FILE) as f: data = json.load(f)
        bot.mode               = data.get("mode", "CRYPTO")
        bot.timeframe          = data.get("timeframe", Config.TIMEFRAME)
        bot.wins               = data.get("wins", 0)
        bot.losses             = data.get("losses", 0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until       = data.get("paused_until", 0)
        bot.active_trades      = data.get("active_trades", [])
        bot.radar_list         = data.get("radar_list", {})
        bot.gatilho_list       = data.get("gatilho_list", {})
        bot.asset_cooldown     = data.get("asset_cooldown", {})
        bot.history            = data.get("history", [])
        for t in bot.active_trades:
            t["session_alerted"] = False
        log(f"[STATE] {bot.wins}W/{bot.losses}L | {len(bot.active_trades)} trade(s) | Modo: {bot.mode} | TF: {bot.timeframe}")
        if bot.active_trades:
            lines = ["♻️ <b>BOT REINICIADO – TRADES ATIVOS</b>\n"]
            for t in bot.active_trades:
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                lines.append(
                    f"📌 <b>{t['symbol']}</b> {dl}\n"
                    f"   Entrada: <code>{fmt(t['entry'])}</code>\n"
                    f"   🎯 TP: <code>{fmt(t['tp'])}</code>  🛡 SL: <code>{fmt(t['sl'])}</code>"
                )
            bot._restore_msg = "\n".join(lines)
        else:
            bot._restore_msg = None
    except Exception as e:
        log(f"[STATE] Erro ao carregar: {e}")


# ══════════════════════════════════════════════════════════════════
# NOTÍCIAS / FEAR & GREED
# ══════════════════════════════════════════════════════════════════
RSS_FEEDS = [
    ("Investing.com BR", "https://br.investing.com/rss/news.rss"),
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Reuters Markets",  "https://feeds.reuters.com/reuters/businessNews"),
    ("MarketWatch",      "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("Cointelegraph",    "https://cointelegraph.com/rss"),
]

def _parse_rss(url, source_name, max_results=3):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}
    r = requests.get(url, headers=headers, timeout=8); r.raise_for_status()
    root = ET.fromstring(r.content)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for item in items[:max_results]:
        title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link  = (item.findtext("link")  or item.findtext("{http://www.w3.org/2005/Atom}link")  or "").strip()
        if title and link:
            out.append({"title": title, "url": link, "source": source_name})
    return out

def get_news(max_results=5):
    articles = []
    for name, url in RSS_FEEDS:
        if len(articles) >= max_results: break
        try: articles.extend(_parse_rss(url, name, 2))
        except Exception as e: log(f"[RSS] {name}: {e}")
    return articles[:max_results]

def get_fear_greed():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6).json()["data"][0]
        return f"{d['value']} – {d['value_classification']}"
    except: return "N/D"

def build_news_message():
    articles = get_news(); fg = get_fear_greed()
    if not articles:
        return f"📰 <b>NOTÍCIAS</b>\n\nSem feed.\n😱 <b>F&amp;G:</b> {fg}"
    lines = ["📰 <b>NOTÍCIAS RELEVANTES</b>\n"]
    for i, a in enumerate(articles, 1):
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{t}</a> <i>({a['source']})</i>")
    lines.append(f"\n😱 <b>Fear &amp; Greed:</b> {fg}")
    lines.append(f"🕐 {datetime.now(Config.BR_TZ).strftime('%H:%M')} (Brasília)")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# MOTOR DE ANÁLISE
# ══════════════════════════════════════════════════════════════════
def get_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf_symbol(symbol)
    period    = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]
    use_volume = volume_reliable(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 50: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]; volume = df["Volume"]
        ema9   = closes.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        sp200  = min(200, len(closes) - 1)
        ema200 = closes.ewm(span=sp200, adjust=False).mean().iloc[-1]
        w = min(20, len(closes) - 1)
        sma20 = closes.rolling(w).mean().iloc[-1]
        std20 = closes.rolling(w).std().iloc[-1]
        upper_band = sma20 + std20 * 2; lower_band = sma20 - std20 * 2
        delta = closes.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        cur_rsi = (100 - 100 / (1 + gain / loss)).iloc[-1]
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_sig  = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_sig
        macd_bull = macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2]
        macd_bear = macd_hist.iloc[-1] < 0 and macd_hist.iloc[-1] < macd_hist.iloc[-2]
        if use_volume and volume.sum() > 0:
            vol_avg   = volume.rolling(20).mean().iloc[-1]
            vol_cur   = volume.iloc[-1]
            vol_ok    = bool(vol_cur > vol_avg) if vol_avg > 0 else False
            vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 0
        else:
            vol_ok = True; vol_ratio = 0
        tr = pd.concat([highs - lows, (highs - closes.shift()).abs(), (lows - closes.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd > 0) & (hd > -ld), 0.0)
        mdm = (-ld).where((-ld > 0) & (-ld > hd), 0.0)
        atr_s = tr.ewm(alpha=1/14, adjust=False).mean()
        pdi = 100 * pdm.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        mdi = 100 * mdm.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        dx  = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-10)
        adx = dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1]

        cur_price    = closes.iloc[-1]
        trigger_buy  = highs.tail(5).max()
        trigger_sell = lows.tail(5).min()

        # Variação % últimos candles
        change_pct = ((closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100) if len(closes) >= 10 else 0

        cenario = "NEUTRO"
        if cur_price > ema200 and ema9 > ema21:   cenario = "ALTA"
        elif cur_price < ema200 and ema9 < ema21: cenario = "BAIXA"

        h1_bull = h1_bear = False
        sup_tf = "1h" if timeframe in ("1m","5m","15m","30m") else "1d"
        sup_per = "60d" if sup_tf == "1h" else "2y"
        try:
            dh = yf.Ticker(yf_symbol).history(period=sup_per, interval=sup_tf)
            if len(dh) >= 50:
                ch = dh["Close"]
                e21h  = ch.ewm(span=21, adjust=False).mean().iloc[-1]
                e200h = ch.ewm(span=min(200, len(ch)-1), adjust=False).mean().iloc[-1]
                ph    = ch.iloc[-1]
                h1_bull = ph > e21h and e21h > e200h
                h1_bear = ph < e21h and e21h < e200h
        except Exception as eh:
            log(f"[H-SUP] {symbol}: {eh}")

        return {
            "symbol": symbol, "name": asset_name(symbol),
            "price": float(cur_price), "cenario": cenario,
            "rsi": float(cur_rsi), "atr": float(atr), "adx": float(adx),
            "ema9": float(ema9), "ema21": float(ema21), "ema200": float(ema200),
            "upper": float(upper_band), "lower": float(lower_band),
            "macd_bull": bool(macd_bull), "macd_bear": bool(macd_bear),
            "macd_hist": float(macd_hist.iloc[-1]),
            "vol_ok": bool(vol_ok), "vol_ratio": float(vol_ratio),
            "t_buy": float(trigger_buy), "t_sell": float(trigger_sell),
            "h1_bull": bool(h1_bull), "h1_bear": bool(h1_bear),
            "change_pct": float(change_pct),
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}")
        return None


def calc_confluence(res, direcao):
    if direcao == "BUY":
        checks = [
            ("EMA 200 (preço acima)", res["price"] > res["ema200"]),
            ("EMA 9 acima da 21",     res["ema9"] > res["ema21"]),
            ("MACD em alta",          res["macd_bull"]),
            ("Volume / Liquidez OK",  res["vol_ok"]),
            ("RSI abaixo de 65",      res["rsi"] < 65),
            ("TF Superior em alta",   res["h1_bull"]),
            ("ADX força tendência",   res["adx"] > Config.ADX_MIN),
        ]
    else:
        checks = [
            ("EMA 200 (preço abaixo)", res["price"] < res["ema200"]),
            ("EMA 9 abaixo da 21",     res["ema9"] < res["ema21"]),
            ("MACD em queda",          res["macd_bear"]),
            ("Volume / Liquidez OK",   res["vol_ok"]),
            ("RSI acima de 35",        res["rsi"] > 35),
            ("TF Superior em queda",   res["h1_bear"]),
            ("ADX força tendência",    res["adx"] > Config.ADX_MIN),
        ]
    score = sum(1 for _, ok in checks if ok)
    return score, len(checks), checks

def confluence_bar(score, total):
    filled = math.floor(score / total * 5)
    return "█" * filled + "░" * (5 - filled)


# ══════════════════════════════════════════════════════════════════
# DETECÇÃO DE REVERSÃO / CONTRA-TENDÊNCIA
# ══════════════════════════════════════════════════════════════════
def detect_reversal(res):
    """
    Detecta possível contra-tendência.
    Retorna: (tem_reversao:bool, direção_reversa:str, força:int 0-100, motivos:list)
    Critérios: RSI extremo + divergência MACD + toque em banda de Bollinger
    """
    if not res: return (False, None, 0, [])

    motivos = []
    forca = 0
    direcao_rev = None

    rsi = res["rsi"]
    price = res["price"]
    cenario = res["cenario"]

    # ── Reversão de ALTA para BAIXA (sobrecomprado) ──
    if cenario == "ALTA" or res["ema9"] > res["ema21"]:
        if rsi >= 70:
            motivos.append(f"RSI sobrecomprado ({rsi:.1f})")
            forca += 30
            direcao_rev = "SELL"
        if rsi >= 75:
            forca += 15
            motivos.append("RSI em zona extrema")
        if price >= res["upper"]:
            motivos.append("Preço tocou banda superior")
            forca += 25
            direcao_rev = "SELL"
        if res["macd_hist"] < 0 and res["ema9"] > res["ema21"]:
            motivos.append("Divergência MACD baixista")
            forca += 20
            direcao_rev = "SELL"
        if res["adx"] < 20 and cenario == "ALTA":
            motivos.append(f"ADX enfraquecendo ({res['adx']:.1f})")
            forca += 10

    # ── Reversão de BAIXA para ALTA (sobrevendido) ──
    if cenario == "BAIXA" or res["ema9"] < res["ema21"]:
        if rsi <= 30:
            motivos.append(f"RSI sobrevendido ({rsi:.1f})")
            forca += 30
            direcao_rev = "BUY"
        if rsi <= 25:
            forca += 15
            motivos.append("RSI em zona extrema")
        if price <= res["lower"]:
            motivos.append("Preço tocou banda inferior")
            forca += 25
            direcao_rev = "BUY"
        if res["macd_hist"] > 0 and res["ema9"] < res["ema21"]:
            motivos.append("Divergência MACD altista")
            forca += 20
            direcao_rev = "BUY"
        if res["adx"] < 20 and cenario == "BAIXA":
            motivos.append(f"ADX enfraquecendo ({res['adx']:.1f})")
            forca += 10

    forca = min(forca, 100)
    tem_reversao = forca >= 40 and direcao_rev is not None
    return (tem_reversao, direcao_rev, forca, motivos)


# ══════════════════════════════════════════════════════════════════
# BOT
# ══════════════════════════════════════════════════════════════════
class TradingBot:
    def __init__(self):
        self.mode = "CRYPTO"; self.timeframe = Config.TIMEFRAME
        self.wins = 0; self.losses = 0; self.consecutive_losses = 0
        self.paused_until = 0
        self.active_trades = []
        self.radar_list = {}; self.gatilho_list = {}
        self.asset_cooldown = {}
        self.history = []
        self.last_id = 0; self.last_news_ts = 0
        self._restore_msg = None
        # Cache de análise para tendências/reversões
        self.trend_cache = {}  # {symbol: {data, ts}}
        self.last_trends_update = 0

    def send(self, text, markup=None, disable_preview=False):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": disable_preview}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=8)
        except Exception as e: log(f"[SEND] {e}")

    def build_menu(self):
        tf_label = Config.TIMEFRAMES.get(self.timeframe, ("?",""))[0]
        mode_label = Config.MARKET_CATEGORIES[self.mode]["label"] if self.mode != "TUDO" else "🌍 TUDO"
        markup = {"inline_keyboard": [
            [{"text": f"📍 Mercado: {mode_label}", "callback_data": "ignore"}],
            [{"text": "📈 FOREX", "callback_data": "set_FOREX"}, {"text": "₿ CRIPTO", "callback_data": "set_CRYPTO"}],
            [{"text": "🏅 COMM.", "callback_data": "set_COMMODITIES"}, {"text": "📊 ÍNDICES", "callback_data": "set_INDICES"}],
            [{"text": "🌍 TUDO", "callback_data": "set_TUDO"}],
            [{"text": f"⏱ TF: {self.timeframe} {tf_label}", "callback_data": "tf_menu"}],
            [{"text": "📊 Status", "callback_data": "status"}, {"text": "🏆 Placar", "callback_data": "placar"}],
            [{"text": "📰 Notícias", "callback_data": "news"}, {"text": "🔄 Atualizar", "callback_data": "refresh"}],
        ]}
        total = self.wins + self.losses
        winrate = (self.wins / total * 100) if total > 0 else 0
        cb_txt = ""
        if self.is_paused():
            mins = int((self.paused_until - time.time()) / 60)
            cb_txt = f"\n⛔ CB – retoma em {mins}min"
        self.send(
            f"<b>🎛 BOT SNIPER v7</b>\n"
            f"Placar: <code>{self.wins}W – {self.losses}L</code> ({winrate:.1f}%)\n"
            f"Modo: <b>{mode_label}</b> | TF: <code>{self.timeframe}</code>{cb_txt}",
            markup
        )

    def build_tf_menu(self):
        rows = []
        for tf, (label, _) in Config.TIMEFRAMES.items():
            active = " ✅" if tf == self.timeframe else ""
            rows.append([{"text": f"{tf} {label}{active}", "callback_data": f"set_tf_{tf}"}])
        rows.append([{"text": "« Voltar", "callback_data": "main_menu"}])
        self.send("⏱ <b>SELECIONE TIMEFRAME</b>", {"inline_keyboard": rows})

    def set_timeframe(self, tf):
        if tf not in Config.TIMEFRAMES: return
        old = self.timeframe; self.timeframe = tf
        save_state(self); log(f"[TF] {old} → {tf}")
        self.send(f"✅ TF: <b>{old}</b> → <b>{tf}</b>")

    def set_mode(self, mode):
        valid = list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]
        if mode not in valid: return
        self.mode = mode
        save_state(self); log(f"[MODE] → {mode}")
        self.send(f"✅ Modo: <b>{mode}</b>")

    def send_news(self):
        self.send(build_news_message(), disable_preview=True)
        self.last_news_ts = time.time()

    def maybe_send_news(self):
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL:
            self.send_news()

    def send_status(self):
        lines = ["📊 <b>OPERAÇÕES ABERTAS</b>\n"]
        if not self.active_trades:
            lines.append("Sem operações."); self.send("\n".join(lines)); return
        for t in self.active_trades:
            res = get_analysis(t["symbol"], self.timeframe)
            cur = res["price"] if res else t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL": pnl = -pnl
            em = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"{em} <b>{t['symbol']}</b> {t['dir']} | P&amp;L: <code>{pnl:+.2f}%</code>")
        self.send("\n".join(lines))

    def send_placar(self):
        total = self.wins + self.losses
        wr = (self.wins / total * 100) if total > 0 else 0
        self.send(f"🏆 <b>PLACAR</b>\nW/L: <code>{self.wins}/{self.losses}</code> ({wr:.1f}%)")

    def is_paused(self): return time.time() < self.paused_until

    def reset_pause(self):
        self.paused_until = 0; self.consecutive_losses = 0
        save_state(self); self.send("✅ Circuit Breaker resetado.")

    # ── Atualiza cache de tendências de TODOS os ativos ──
    def update_trends_cache(self):
        now = time.time()
        if now - self.last_trends_update < Config.TRENDS_INTERVAL:
            return
        log("📡 Atualizando cache de tendências...")
        for s in all_symbols():
            try:
                res = get_analysis(s, self.timeframe)
                if res:
                    reversal = detect_reversal(res)
                    self.trend_cache[s] = {
                        "data": res,
                        "reversal": {
                            "has": reversal[0],
                            "dir": reversal[1],
                            "strength": reversal[2],
                            "reasons": reversal[3],
                        },
                        "ts": now,
                    }
            except Exception as e:
                log(f"[TRENDS] {s}: {e}")
        self.last_trends_update = now
        log(f"📡 Cache atualizado: {len(self.trend_cache)} ativos")

    def scan(self):
        if self.is_paused(): return
        if len(self.active_trades) >= Config.MAX_TRADES: return
        universe = all_symbols() if self.mode == "TUDO" else list(Config.MARKET_CATEGORIES[self.mode]["assets"].keys())
        log(f"🔎 Scan {self.mode} ({len(universe)} ativos, TF {self.timeframe})")
        for s in universe:
            cat = asset_category(s)
            if not market_open(cat): continue
            if any(t["symbol"] == s for t in self.active_trades): continue
            cd_rem = Config.ASSET_COOLDOWN - (time.time() - self.asset_cooldown.get(s, 0))
            if cd_rem > 0: continue

            res = self.trend_cache.get(s, {}).get("data") or get_analysis(s, self.timeframe)
            if not res or res["cenario"] == "NEUTRO": continue

            price = res["price"]; atr = res["atr"]; cenario = res["cenario"]
            if cenario == "ALTA":
                gatilho = res["t_buy"]
                sl_est = gatilho - Config.ATR_MULT_SL * atr
                tp_est = gatilho + Config.ATR_MULT_TP * atr
                dir_simple = "BUY"
                preco_ok = price >= gatilho and price < res["upper"] and res["rsi"] < 70
            else:
                gatilho = res["t_sell"]
                sl_est = gatilho + Config.ATR_MULT_SL * atr
                tp_est = gatilho - Config.ATR_MULT_TP * atr
                dir_simple = "SELL"
                preco_ok = price <= gatilho and price > res["lower"] and res["rsi"] > 30

            if not preco_ok: continue

            score, total_c, checks = calc_confluence(res, dir_simple)
            if score < Config.MIN_CONFLUENCE: continue

            if dir_simple == "BUY":
                sl = price - Config.ATR_MULT_SL * atr
                tp = price + Config.ATR_MULT_TP * atr
            else:
                sl = price + Config.ATR_MULT_SL * atr
                tp = price - Config.ATR_MULT_TP * atr

            sl_pct = abs(price - sl) / price * 100
            tp_pct = abs(tp - price) / price * 100
            dl = "COMPRAR 🟢" if dir_simple == "BUY" else "VENDER 🔴"
            self.send(
                f"🎯 <b>SINAL – {s}</b>\n"
                f"<b>{dl}</b>\n"
                f"💰 <code>{fmt(price)}</code>\n"
                f"🛡 SL <code>{fmt(sl)}</code> ({-sl_pct:.2f}%)\n"
                f"🎯 TP <code>{fmt(tp)}</code> ({tp_pct:+.2f}%)\n"
                f"Confluência: {score}/{total_c}"
            )
            self.active_trades.append({
                "symbol": s, "name": res["name"], "entry": price,
                "tp": tp, "sl": sl, "dir": dir_simple,
                "peak": price, "atr": atr,
                "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "session_alerted": True,
            })
            save_state(self)

    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res: continue
            cur = res["price"]; atr = res["atr"]
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl = cur - Config.ATR_MULT_TRAIL * atr
                if new_sl > t["sl"]: t["sl"] = new_sl; changed = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl = cur + Config.ATR_MULT_TRAIL * atr
                if new_sl < t["sl"]: t["sl"] = new_sl; changed = True
            is_win  = ((t["dir"]=="BUY" and cur>=t["tp"]) or (t["dir"]=="SELL" and cur<=t["tp"]))
            is_loss = ((t["dir"]=="BUY" and cur<=t["sl"]) or (t["dir"]=="SELL" and cur>=t["sl"]))
            if is_win or is_loss:
                pnl = (cur - t["entry"]) / t["entry"] * 100
                if t["dir"] == "SELL": pnl = -pnl
                if is_win:
                    self.wins += 1; self.consecutive_losses = 0
                else:
                    self.losses += 1; self.consecutive_losses += 1
                    self.asset_cooldown[t["symbol"]] = time.time()
                self.history.append({
                    "symbol": t["symbol"], "dir": t["dir"],
                    "result": "WIN" if is_win else "LOSS",
                    "pnl": round(pnl, 2),
                    "closed_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                })
                status = "✅ WIN" if is_win else "❌ LOSS"
                self.send(f"🏁 {t['symbol']} {status} | P&amp;L <code>{pnl:+.2f}%</code>")
                self.active_trades.remove(t); changed = True
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    self.send(f"⛔ Circuit Breaker – pausa {Config.PAUSE_DURATION//60}min")
        if changed: save_state(self)


# ══════════════════════════════════════════════════════════════════
# HTML DASHBOARD (embutido)
# ══════════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<meta name="theme-color" content="#080b12"/>
<title>Sniper Bot v7</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{--bg:#080b12;--bg2:#0e1420;--bg3:#141b2b;--border:#1e2d45;--text:#c8d8f0;--muted:#4a6080;
--green:#00e676;--green2:#00c853;--red:#ff1744;--red2:#d50000;--gold:#ffc400;--blue:#2979ff;--cyan:#00b0ff;--purple:#aa00ff;
--mono:'Space Mono',monospace;--sans:'DM Sans',sans-serif;--radius:12px;--nav-h:62px;--safe-bot:env(safe-area-inset-bottom,0px)}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:var(--sans)}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:9999;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.08) 2px,rgba(0,0,0,.08) 4px)}
#app{display:flex;flex-direction:column;height:100%;max-width:480px;margin:0 auto;position:relative}
#header{padding:12px 16px 10px;background:linear-gradient(135deg,var(--bg2) 0%,#0a1020 100%);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{width:34px;height:34px;border-radius:8px;background:linear-gradient(135deg,var(--green),var(--cyan));display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#000;font-family:var(--mono)}
.logo-text{font-size:16px;font-weight:600}
.logo-sub{font-size:9px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase;margin-top:1px}
.header-right{display:flex;align-items:center;gap:8px}
.refresh-btn{width:32px;height:32px;border-radius:8px;border:1px solid var(--border);background:var(--bg3);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:14px}
.live-dot{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--muted);text-transform:uppercase}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
#pages{flex:1;overflow:hidden;position:relative}
.page{position:absolute;inset:0;overflow-y:auto;padding:14px 14px calc(var(--nav-h) + var(--safe-bot) + 12px);display:none}
.page.active{display:block}
.page::-webkit-scrollbar{width:3px}.page::-webkit-scrollbar-thumb{background:var(--border)}
#nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:480px;background:var(--bg2);border-top:1px solid var(--border);display:flex;height:var(--nav-h);padding-bottom:var(--safe-bot);z-index:100;overflow-x:auto}
.nav-item{flex:1;min-width:72px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;cursor:pointer;font-size:9px;color:var(--muted);text-transform:uppercase;border:none;background:none;padding:0}
.nav-item .nav-icon{font-size:18px}
.nav-item.active{color:var(--green)}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-bottom:10px;position:relative;overflow:hidden}
.card-title{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:10px;display:flex;align-items:center;gap:6px}
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.stat-card{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:12px}
.stat-label{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.stat-val{font-size:24px;font-weight:700;font-family:var(--mono);line-height:1}
.stat-sub{font-size:10px;color:var(--muted);margin-top:4px}
.green{color:var(--green)}.red{color:var(--red)}.gold{color:var(--gold)}.cyan{color:var(--cyan)}.purple{color:var(--purple)}
.mkt-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.mkt-item{background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:8px 10px;display:flex;align-items:center;justify-content:space-between}
.mkt-name{font-size:11px}
.mkt-status{font-size:8px;padding:2px 6px;border-radius:20px;font-family:var(--mono);text-transform:uppercase}
.mkt-open{background:rgba(0,230,118,.12);color:var(--green)}
.mkt-closed{background:rgba(255,23,68,.08);color:var(--red)}
.trade-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-bottom:8px}
.trade-card.buy-card{border-left:3px solid var(--green)}
.trade-card.sell-card{border-left:3px solid var(--red)}
.trade-top{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px}
.trade-sym{font-size:16px;font-weight:700;font-family:var(--mono)}
.trade-name{font-size:10px;color:var(--muted);margin-top:2px}
.trade-dir{font-size:10px;font-weight:600;font-family:var(--mono);padding:4px 9px;border-radius:20px}
.dir-buy{background:rgba(0,230,118,.15);color:var(--green)}
.dir-sell{background:rgba(255,23,68,.12);color:var(--red)}
.trade-levels{display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;margin-bottom:8px}
.level-box{background:var(--bg3);border-radius:8px;padding:7px;text-align:center}
.level-label{font-size:8px;text-transform:uppercase;color:var(--muted);margin-bottom:3px}
.level-val{font-size:11px;font-family:var(--mono);font-weight:700}
.pnl-bar{height:4px;border-radius:2px;background:var(--bg3);margin-top:8px;overflow:hidden}
.pnl-fill{height:100%;transition:width .5s}
.pnl-positive .pnl-fill{background:linear-gradient(90deg,var(--green2),var(--green))}
.pnl-negative .pnl-fill{background:linear-gradient(90deg,var(--red2),var(--red))}
.trade-footer{display:flex;align-items:center;justify-content:space-between;margin-top:8px}
.pnl-badge{font-size:14px;font-weight:700;font-family:var(--mono)}
.trade-time{font-size:10px;color:var(--muted)}
.hist-item{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)}
.hist-item:last-child{border-bottom:none}
.hist-icon{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0}
.hist-win .hist-icon{background:rgba(0,230,118,.12)}
.hist-loss .hist-icon{background:rgba(255,23,68,.1)}
.hist-info{flex:1}
.hist-sym{font-size:13px;font-weight:600;font-family:var(--mono)}
.hist-meta{font-size:10px;color:var(--muted);margin-top:2px}
.hist-pnl{font-size:14px;font-weight:700;font-family:var(--mono)}
.cfg-section{margin-bottom:18px}
.cfg-label{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
.btn-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.btn-grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}
.cfg-btn{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:10px 6px;cursor:pointer;font-size:11px;font-family:var(--sans);color:var(--text);text-align:center;line-height:1.3}
.cfg-btn.active-cfg{background:rgba(0,230,118,.12);border-color:var(--green);color:var(--green)}
.cfg-btn.active-tf{background:rgba(0,176,255,.12);border-color:var(--cyan);color:var(--cyan)}
.cfg-btn-icon{font-size:16px;display:block;margin-bottom:3px}
.action-btn{width:100%;padding:14px;border-radius:12px;border:none;cursor:pointer;font-size:13px;font-weight:600;margin-bottom:8px;font-family:var(--sans)}
.btn-danger{background:rgba(255,23,68,.15);color:var(--red);border:1px solid rgba(255,23,68,.3)}
.btn-primary{background:rgba(0,230,118,.15);color:var(--green);border:1px solid rgba(0,230,118,.3)}
.cb-banner{background:rgba(255,23,68,.08);border:1px solid rgba(255,23,68,.25);border-radius:10px;padding:10px 14px;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}
.cb-text{font-size:11px;color:var(--red)}
.cb-mins{font-size:18px;font-weight:700;font-family:var(--mono);color:var(--red)}
.empty{text-align:center;padding:36px 20px;color:var(--muted)}
.empty-icon{font-size:36px;margin-bottom:10px;display:block}
.empty-text{font-size:12px}
.error-bar{background:rgba(255,23,68,.08);border:1px solid rgba(255,23,68,.2);border-radius:8px;padding:10px 14px;margin-bottom:10px;font-size:11px;color:var(--red);display:none}
.timestamp{font-size:9px;color:var(--muted);text-align:center;padding:6px 0}
.divider{height:1px;background:var(--border);margin:14px 0}

/* TRENDS */
.trend-filter{display:flex;gap:6px;margin-bottom:10px;overflow-x:auto;padding-bottom:4px}
.trend-filter::-webkit-scrollbar{display:none}
.filter-chip{flex-shrink:0;padding:7px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:20px;font-size:11px;cursor:pointer;white-space:nowrap}
.filter-chip.active{background:rgba(0,230,118,.12);border-color:var(--green);color:var(--green)}
.trend-row{display:flex;align-items:center;gap:10px;padding:12px;background:var(--bg2);border:1px solid var(--border);border-radius:10px;margin-bottom:6px;border-left:3px solid var(--muted)}
.trend-row.trend-alta{border-left-color:var(--green)}
.trend-row.trend-baixa{border-left-color:var(--red)}
.trend-row.trend-neutro{border-left-color:var(--muted)}
.trend-left{flex:1;min-width:0}
.trend-sym-line{display:flex;align-items:center;gap:8px}
.trend-sym{font-size:13px;font-weight:700;font-family:var(--mono)}
.trend-badge{font-size:8px;padding:2px 7px;border-radius:10px;font-family:var(--mono);text-transform:uppercase;font-weight:700}
.badge-alta{background:rgba(0,230,118,.15);color:var(--green)}
.badge-baixa{background:rgba(255,23,68,.12);color:var(--red)}
.badge-neutro{background:rgba(74,96,128,.2);color:var(--muted)}
.trend-name{font-size:10px;color:var(--muted);margin-top:2px}
.trend-right{text-align:right;flex-shrink:0}
.trend-price{font-size:12px;font-family:var(--mono);font-weight:600}
.trend-change{font-size:10px;font-family:var(--mono);margin-top:2px}
.trend-meta{display:flex;gap:10px;margin-top:5px;font-size:9px;color:var(--muted);font-family:var(--mono)}

/* REVERSAL */
.rev-card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:8px;border-left:3px solid var(--gold)}
.rev-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.rev-sym{font-size:14px;font-weight:700;font-family:var(--mono)}
.rev-arrow{font-size:12px;font-family:var(--mono);padding:4px 9px;border-radius:20px;font-weight:700}
.rev-to-buy{background:rgba(0,230,118,.15);color:var(--green)}
.rev-to-sell{background:rgba(255,23,68,.12);color:var(--red)}
.rev-strength{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.rev-bar{flex:1;height:6px;background:var(--bg3);border-radius:3px;overflow:hidden}
.rev-bar-fill{height:100%;background:linear-gradient(90deg,var(--gold),var(--red));transition:width .4s}
.rev-pct{font-size:11px;font-family:var(--mono);font-weight:700;color:var(--gold);min-width:38px;text-align:right}
.rev-reasons{font-size:11px;color:var(--muted);line-height:1.7}
.rev-reasons div{padding:3px 0}
</style>
</head>
<body>
<div id="app">
<div id="header">
<div class="logo"><div class="logo-icon">S</div><div><div class="logo-text">Sniper Bot</div><div class="logo-sub">v7 All-in-One</div></div></div>
<div class="header-right"><div class="live-dot"><div class="dot"></div>LIVE</div><div class="refresh-btn" onclick="refresh()">↻</div></div>
</div>

<div id="pages">

<!-- DASH -->
<div class="page active" id="page-dash">
<div id="error-bar" class="error-bar">⚠ Erro ao conectar à API</div>
<div id="cb-banner" class="cb-banner" style="display:none">
<div><div style="font-weight:600;color:var(--red)">⛔ CIRCUIT BREAKER</div><div class="cb-text">Bot pausado</div></div>
<div class="cb-mins" id="cb-mins">--min</div>
</div>
<div class="stats-grid">
<div class="stat-card"><div class="stat-label">Wins</div><div class="stat-val green" id="s-wins">--</div><div class="stat-sub" id="s-winrate">--</div></div>
<div class="stat-card"><div class="stat-label">Losses</div><div class="stat-val red" id="s-losses">--</div><div class="stat-sub" id="s-consec">--</div></div>
</div>
<div class="card">
<div class="card-title">⚙ Configuração</div>
<div style="display:flex;gap:8px">
<div style="flex:1;background:var(--bg3);border-radius:8px;padding:10px;text-align:center"><div class="stat-label">Mercado</div><div style="font-size:14px;font-weight:700;margin-top:3px" id="s-mode">--</div></div>
<div style="flex:1;background:var(--bg3);border-radius:8px;padding:10px;text-align:center"><div class="stat-label">TF</div><div style="font-size:14px;font-weight:700;font-family:var(--mono);margin-top:3px" id="s-tf">--</div></div>
<div style="flex:1;background:var(--bg3);border-radius:8px;padding:10px;text-align:center"><div class="stat-label">Trades</div><div style="font-size:14px;font-weight:700;font-family:var(--mono);margin-top:3px" id="s-ntrades">--</div></div>
</div>
</div>
<div class="card-title" style="margin:12px 0 6px">📊 Trades Abertos</div>
<div id="trades-list"><div class="empty"><span class="empty-icon">📭</span><div class="empty-text">Nenhum trade</div></div></div>
<div class="card" style="margin-top:10px">
<div class="card-title">🌐 Mercados</div>
<div class="mkt-grid" id="mkt-grid"></div>
</div>
<div class="timestamp" id="last-update">...</div>
</div>

<!-- TENDÊNCIAS -->
<div class="page" id="page-trends">
<div class="card-title" style="margin-bottom:8px">📡 Tendência em Tempo Real</div>
<div class="trend-filter" id="trend-filter">
<div class="filter-chip active" data-f="ALL">Todos</div>
<div class="filter-chip" data-f="ALTA">🟢 Alta</div>
<div class="filter-chip" data-f="BAIXA">🔴 Baixa</div>
<div class="filter-chip" data-f="NEUTRO">⚪ Neutro</div>
<div class="filter-chip" data-f="FOREX">📈 Forex</div>
<div class="filter-chip" data-f="CRYPTO">₿ Cripto</div>
<div class="filter-chip" data-f="COMMODITIES">🏅 Comm.</div>
<div class="filter-chip" data-f="INDICES">📊 Índ.</div>
</div>
<div id="trends-list"><div class="empty"><span class="empty-icon">📡</span><div class="empty-text">Carregando...</div></div></div>
</div>

<!-- REVERSÕES -->
<div class="page" id="page-reversals">
<div class="card-title" style="margin-bottom:8px">🔄 Contra-Tendências Detectadas</div>
<div style="font-size:11px;color:var(--muted);margin-bottom:10px;line-height:1.6">
Ativos mostrando sinais de possível reversão de tendência. Força ≥ 40%.
</div>
<div id="reversals-list"><div class="empty"><span class="empty-icon">🔄</span><div class="empty-text">Carregando...</div></div></div>
</div>

<!-- HIST -->
<div class="page" id="page-signals">
<div class="card-title" style="margin-bottom:8px">📜 Histórico</div>
<div id="hist-list"><div class="empty"><span class="empty-icon">📜</span><div class="empty-text">Sem histórico</div></div></div>
</div>

<!-- TRADES -->
<div class="page" id="page-trades">
<div class="card-title" style="margin-bottom:8px">💼 Operações Abertas</div>
<div id="trades-detail"><div class="empty"><span class="empty-icon">💼</span><div class="empty-text">Sem operações</div></div></div>
</div>

<!-- CONFIG -->
<div class="page" id="page-config">
<div class="cfg-section">
<div class="cfg-label">Mercado</div>
<div class="btn-grid">
<button class="cfg-btn" data-mode="FOREX" onclick="setMode('FOREX')"><span class="cfg-btn-icon">📈</span>FOREX</button>
<button class="cfg-btn" data-mode="CRYPTO" onclick="setMode('CRYPTO')"><span class="cfg-btn-icon">₿</span>CRIPTO</button>
<button class="cfg-btn" data-mode="COMMODITIES" onclick="setMode('COMMODITIES')"><span class="cfg-btn-icon">🏅</span>COMM.</button>
<button class="cfg-btn" data-mode="INDICES" onclick="setMode('INDICES')"><span class="cfg-btn-icon">📊</span>ÍND.</button>
</div>
<button class="cfg-btn" style="width:100%;margin-top:6px" data-mode="TUDO" onclick="setMode('TUDO')"><span class="cfg-btn-icon" style="display:inline;margin-right:5px">🌍</span>TUDO (42)</button>
</div>
<div class="cfg-section">
<div class="cfg-label">Timeframe</div>
<div class="btn-grid-3">
<button class="cfg-btn" data-tf="1m" onclick="setTf('1m')"><span style="display:block;color:var(--red);font-size:14px">●</span>1m</button>
<button class="cfg-btn" data-tf="5m" onclick="setTf('5m')"><span style="display:block;color:orange;font-size:14px">●</span>5m</button>
<button class="cfg-btn" data-tf="15m" onclick="setTf('15m')"><span style="display:block;color:var(--gold);font-size:14px">●</span>15m</button>
<button class="cfg-btn" data-tf="30m" onclick="setTf('30m')"><span style="display:block;color:var(--green);font-size:14px">●</span>30m</button>
<button class="cfg-btn" data-tf="1h" onclick="setTf('1h')"><span style="display:block;color:var(--cyan);font-size:14px">●</span>1h</button>
<button class="cfg-btn" data-tf="4h" onclick="setTf('4h')"><span style="display:block;color:var(--blue);font-size:14px">●</span>4h</button>
</div>
</div>
<div class="divider"></div>
<button class="action-btn btn-danger" onclick="resetPausa()">⛔ Resetar CB</button>
<button class="action-btn btn-primary" onclick="refresh()">↻ Atualizar</button>
<div class="card" style="background:var(--bg3)">
<div class="card-title">⚙ Parâmetros</div>
<div style="font-size:11px;line-height:1.9;font-family:var(--mono);color:var(--muted)">
<div>SL: <span id="p-sl" style="color:var(--red)">--</span>×ATR</div>
<div>TP: <span id="p-tp" style="color:var(--green)">--</span>×ATR</div>
<div>Max Trades: <span id="p-mt" style="color:var(--cyan)">--</span></div>
<div>Min Confluência: <span id="p-mc" style="color:var(--gold)">--</span>/7</div>
</div>
</div>
</div>
</div>

<nav id="nav">
<button class="nav-item active" onclick="goTo('dash',this)"><span class="nav-icon">⬡</span>Dash</button>
<button class="nav-item" onclick="goTo('trends',this)"><span class="nav-icon">📡</span>Trends</button>
<button class="nav-item" onclick="goTo('reversals',this)"><span class="nav-icon">🔄</span>Revers.</button>
<button class="nav-item" onclick="goTo('signals',this)"><span class="nav-icon">📜</span>Histór.</button>
<button class="nav-item" onclick="goTo('trades',this)"><span class="nav-icon">💼</span>Trades</button>
<button class="nav-item" onclick="goTo('config',this)"><span class="nav-icon">⚙</span>Config</button>
</nav>
</div>

<script>
const API_BASE = '';  // mesma origem do servidor
let _state=null, _trends=[], _reversals=[], _trendFilter='ALL';

function goTo(page,btn){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b=>b.classList.remove('active'));
  document.getElementById('page-'+page).classList.add('active');
  btn.classList.add('active');
  if(page==='signals') renderHistory();
  if(page==='trades') renderTradesDetail();
  if(page==='trends') loadTrends();
  if(page==='reversals') loadReversals();
}
function fmtPrice(p){if(p===null||p===undefined)return'--';if(p>=1000)return p.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});if(p>=10)return p.toFixed(4);if(p>=1)return p.toFixed(5);return p.toFixed(6)}
async function apiFetch(path,opts={}){const r=await fetch(API_BASE+path,{headers:{'Content-Type':'application/json'},...opts});if(!r.ok)throw new Error(r.statusText);return r.json()}
async function refresh(){
  const btn=document.querySelector('.refresh-btn');btn.style.transform='rotate(360deg)';btn.style.transition='transform .5s';
  setTimeout(()=>{btn.style.transform='';btn.style.transition=''},600);
  try{_state=await apiFetch('/api/status');document.getElementById('error-bar').style.display='none';renderDashboard(_state);
    const active=document.querySelector('.page.active');
    if(active.id==='page-signals')renderHistory();
    if(active.id==='page-trades')renderTradesDetail();
    if(active.id==='page-trends')loadTrends();
    if(active.id==='page-reversals')loadReversals();
  }catch(e){document.getElementById('error-bar').style.display='block'}
  try{const cfg=await apiFetch('/api/config');
    document.getElementById('p-sl').textContent=cfg.atm_sl;
    document.getElementById('p-tp').textContent=cfg.atr_tp;
    document.getElementById('p-mt').textContent=cfg.max_trades;
    document.getElementById('p-mc').textContent=cfg.min_conf;
    updateCfgButtons();
  }catch(_){}
  document.getElementById('last-update').textContent='Atualizado '+new Date().toLocaleTimeString('pt-BR');
}
function renderDashboard(s){
  document.getElementById('s-wins').textContent=s.wins;
  document.getElementById('s-losses').textContent=s.losses;
  document.getElementById('s-winrate').textContent='WR '+s.winrate+'%';
  document.getElementById('s-consec').textContent='Seq: '+s.consecutive_losses;
  document.getElementById('s-mode').textContent=s.mode;
  document.getElementById('s-tf').textContent=s.timeframe;
  document.getElementById('s-ntrades').textContent=s.active_trades.length+'/3';
  const cb=document.getElementById('cb-banner');
  if(s.paused){cb.style.display='flex';document.getElementById('cb-mins').textContent=s.cb_mins+'min'}else{cb.style.display='none'}
  const tl=document.getElementById('trades-list');
  if(!s.active_trades.length){tl.innerHTML='<div class="empty"><span class="empty-icon">📭</span><div class="empty-text">Nenhum trade</div></div>'}
  else{tl.innerHTML=s.active_trades.map(tradeCard).join('')}
  const mg=document.getElementById('mkt-grid');
  const mktNames={FOREX:'📈 FOREX',CRYPTO:'₿ Cripto',COMMODITIES:'🏅 Comm.',INDICES:'📊 Índices'};
  mg.innerHTML=Object.entries(s.markets).map(([c,o])=>`<div class="mkt-item"><span class="mkt-name">${mktNames[c]||c}</span><span class="mkt-status ${o?'mkt-open':'mkt-closed'}">${o?'Aberto':'Fech.'}</span></div>`).join('');
}
function tradeCard(t){
  const isBuy=t.dir==='BUY';const pnlPos=t.pnl>=0;
  const cardCls=isBuy?'buy-card':'sell-card';
  const dirCls=isBuy?'dir-buy':'dir-sell';
  const dirTxt=isBuy?'▲ BUY':'▼ SELL';
  const pnlPct=Math.min(Math.abs(t.pnl)/2*100,100);
  return `<div class="trade-card ${cardCls}">
<div class="trade-top"><div><div class="trade-sym">${t.symbol}</div><div class="trade-name">${t.name||''} · ${t.opened_at||''}</div></div><div class="trade-dir ${dirCls}">${dirTxt}</div></div>
<div class="trade-levels">
<div class="level-box"><div class="level-label">Entrada</div><div class="level-val">${fmtPrice(t.entry)}</div></div>
<div class="level-box"><div class="level-label">SL 🛡</div><div class="level-val red">${fmtPrice(t.sl)}</div></div>
<div class="level-box"><div class="level-label">TP 🎯</div><div class="level-val green">${fmtPrice(t.tp)}</div></div>
</div>
<div class="trade-footer"><div class="pnl-badge" style="color:${pnlPos?'var(--green)':'var(--red)'}">${t.pnl>0?'+':''}${t.pnl.toFixed(2)}%</div><div class="trade-time">Atual: ${fmtPrice(t.current)}</div></div>
<div class="pnl-bar ${pnlPos?'pnl-positive':'pnl-negative'}"><div class="pnl-fill" style="width:${pnlPct}%"></div></div>
</div>`;
}
async function renderHistory(){
  const el=document.getElementById('hist-list');
  try{const hist=await apiFetch('/api/history');
    if(!hist.length){el.innerHTML='<div class="empty"><span class="empty-icon">📜</span><div class="empty-text">Sem histórico</div></div>';return}
    el.innerHTML=`<div class="card" style="padding:0 14px">`+hist.map(h=>{const win=h.result==='WIN';
      return `<div class="hist-item ${win?'hist-win':'hist-loss'}"><div class="hist-icon">${win?'✅':'❌'}</div><div class="hist-info"><div class="hist-sym">${h.symbol} <span style="font-size:10px;color:var(--muted)">${h.dir}</span></div><div class="hist-meta">${h.closed_at||''}</div></div><div class="hist-pnl" style="color:${win?'var(--green)':'var(--red)'}">${h.pnl>0?'+':''}${h.pnl.toFixed(2)}%</div></div>`;
    }).join('')+`</div>`;
  }catch(e){el.innerHTML='<div class="empty">⚠ Erro</div>'}
}
function renderTradesDetail(){
  const el=document.getElementById('trades-detail');
  if(!_state||!_state.active_trades.length){el.innerHTML='<div class="empty"><span class="empty-icon">💼</span><div class="empty-text">Sem operações</div></div>';return}
  el.innerHTML=_state.active_trades.map(tradeCard).join('');
}
async function loadTrends(){
  const el=document.getElementById('trends-list');
  el.innerHTML='<div class="empty"><span class="empty-icon">⏳</span><div class="empty-text">Carregando...</div></div>';
  try{_trends=await apiFetch('/api/trends');renderTrends()}
  catch(e){el.innerHTML='<div class="empty">⚠ Erro ao carregar</div>'}
}
function renderTrends(){
  const el=document.getElementById('trends-list');
  let list=_trends;
  if(_trendFilter!=='ALL'){
    if(['ALTA','BAIXA','NEUTRO'].includes(_trendFilter))list=list.filter(t=>t.cenario===_trendFilter);
    else list=list.filter(t=>t.category===_trendFilter);
  }
  if(!list.length){el.innerHTML='<div class="empty"><span class="empty-icon">🔍</span><div class="empty-text">Nenhum ativo</div></div>';return}
  el.innerHTML=list.map(t=>{
    const cls=t.cenario==='ALTA'?'trend-alta':t.cenario==='BAIXA'?'trend-baixa':'trend-neutro';
    const badge=t.cenario==='ALTA'?'badge-alta':t.cenario==='BAIXA'?'badge-baixa':'badge-neutro';
    const ico=t.cenario==='ALTA'?'▲':t.cenario==='BAIXA'?'▼':'─';
    const chCol=t.change_pct>=0?'var(--green)':'var(--red)';
    return `<div class="trend-row ${cls}">
<div class="trend-left">
<div class="trend-sym-line"><span class="trend-sym">${t.symbol}</span><span class="trend-badge ${badge}">${ico} ${t.cenario}</span></div>
<div class="trend-name">${t.name}</div>
<div class="trend-meta"><span>RSI ${t.rsi.toFixed(0)}</span><span>ADX ${t.adx.toFixed(0)}</span></div>
</div>
<div class="trend-right">
<div class="trend-price">${fmtPrice(t.price)}</div>
<div class="trend-change" style="color:${chCol}">${t.change_pct>=0?'+':''}${t.change_pct.toFixed(2)}%</div>
</div>
</div>`;
  }).join('');
}
document.addEventListener('click',(e)=>{
  if(e.target.classList.contains('filter-chip')){
    document.querySelectorAll('.filter-chip').forEach(c=>c.classList.remove('active'));
    e.target.classList.add('active');
    _trendFilter=e.target.dataset.f;
    renderTrends();
  }
});
async function loadReversals(){
  const el=document.getElementById('reversals-list');
  el.innerHTML='<div class="empty"><span class="empty-icon">⏳</span><div class="empty-text">Analisando...</div></div>';
  try{_reversals=await apiFetch('/api/reversals');
    if(!_reversals.length){el.innerHTML='<div class="empty"><span class="empty-icon">✨</span><div class="empty-text">Nenhuma reversão detectada</div></div>';return}
    el.innerHTML=_reversals.map(r=>{
      const dirCls=r.direction==='BUY'?'rev-to-buy':'rev-to-sell';
      const dirTxt=r.direction==='BUY'?'🔻 BAIXA → ALTA 🟢':'🔺 ALTA → BAIXA 🔴';
      return `<div class="rev-card">
<div class="rev-top"><span class="rev-sym">${r.symbol} <span style="font-size:10px;color:var(--muted);font-weight:400">${r.name}</span></span><span class="rev-arrow ${dirCls}">${dirTxt}</span></div>
<div class="rev-strength"><div class="rev-bar"><div class="rev-bar-fill" style="width:${r.strength}%"></div></div><div class="rev-pct">${r.strength}%</div></div>
<div class="rev-reasons">${r.reasons.map(m=>`<div>• ${m}</div>`).join('')}</div>
<div style="font-size:10px;color:var(--muted);margin-top:8px;font-family:var(--mono)">Preço: ${fmtPrice(r.price)} · RSI ${r.rsi.toFixed(0)}</div>
</div>`;
    }).join('');
  }catch(e){el.innerHTML='<div class="empty">⚠ Erro</div>'}
}
function updateCfgButtons(){
  if(!_state)return;
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active-cfg',b.dataset.mode===_state.mode));
  document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('active-tf',b.dataset.tf===_state.timeframe));
}
async function setMode(m){try{await apiFetch('/api/mode',{method:'POST',body:JSON.stringify({mode:m})});await refresh()}catch(e){alert(e.message)}}
async function setTf(t){try{await apiFetch('/api/timeframe',{method:'POST',body:JSON.stringify({timeframe:t})});await refresh()}catch(e){alert(e.message)}}
async function resetPausa(){if(!confirm('Resetar CB?'))return;try{await apiFetch('/api/resetpausa',{method:'POST'});await refresh()}catch(e){alert(e.message)}}
window.addEventListener('load',()=>{refresh();setInterval(refresh,30000)});

/* PWA manifest inline */
const manifest={name:'Sniper Bot',short_name:'SniperBot',start_url:'/',display:'standalone',orientation:'portrait',background_color:'#080b12',theme_color:'#080b12',
icons:[{src:"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'%3E%3Crect width='192' height='192' rx='32' fill='%23080b12'/%3E%3Ctext x='96' y='130' font-size='110' text-anchor='middle' fill='%2300e676' font-family='monospace' font-weight='700'%3ES%3C/text%3E%3C/svg%3E",sizes:'192x192',type:'image/svg+xml'},
{src:"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'%3E%3Crect width='512' height='512' rx='80' fill='%23080b12'/%3E%3Ctext x='256' y='360' font-size='300' text-anchor='middle' fill='%2300e676' font-family='monospace' font-weight='700'%3ES%3C/text%3E%3C/svg%3E",sizes:'512x512',type:'image/svg+xml'}]};
const blob=new Blob([JSON.stringify(manifest)],{type:'application/json'});
const link=document.createElement('link');link.rel='manifest';link.href=URL.createObjectURL(blob);document.head.appendChild(link);
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════
# API FLASK
# ══════════════════════════════════════════════════════════════════
def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def index():
        return Response(DASHBOARD_HTML, mimetype="text/html")

    @app.route("/api/status")
    def api_status():
        total = bot.wins + bot.losses
        winrate = round((bot.wins / total * 100), 1) if total > 0 else 0
        trades_out = []
        for t in bot.active_trades:
            try:
                res = get_analysis(t["symbol"], bot.timeframe)
                cur = res["price"] if res else t["entry"]
            except: cur = t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL": pnl = -pnl
            trades_out.append({
                "symbol": t["symbol"], "name": t.get("name", ""), "dir": t["dir"],
                "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
                "current": cur, "pnl": round(pnl, 2),
                "opened_at": t.get("opened_at", ""),
            })
        markets = {cat: market_open(cat) for cat in Config.MARKET_CATEGORIES.keys()}
        cb_mins = max(0, int((bot.paused_until - time.time()) / 60)) if bot.is_paused() else 0
        return jsonify({
            "wins": bot.wins, "losses": bot.losses, "winrate": winrate,
            "consecutive_losses": bot.consecutive_losses,
            "mode": bot.mode, "timeframe": bot.timeframe,
            "paused": bot.is_paused(), "cb_mins": cb_mins,
            "active_trades": trades_out, "markets": markets,
        })

    @app.route("/api/config")
    def api_config():
        return jsonify({"atm_sl": Config.ATR_MULT_SL, "atr_tp": Config.ATR_MULT_TP,
                        "max_trades": Config.MAX_TRADES, "min_conf": Config.MIN_CONFLUENCE})

    @app.route("/api/history")
    def api_history():
        return jsonify(list(reversed(bot.history[-50:])))

    @app.route("/api/trends")
    def api_trends():
        """Tendência de TODOS os ativos (usa cache)"""
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            d = entry["data"]
            out.append({
                "symbol":     sym,
                "name":       d["name"],
                "category":   asset_category(sym),
                "price":      d["price"],
                "cenario":    d["cenario"],
                "rsi":        d["rsi"],
                "adx":        d["adx"],
                "change_pct": d["change_pct"],
            })
        # ordena: ALTA primeiro (maior change), BAIXA depois, NEUTRO por último
        order = {"ALTA": 0, "BAIXA": 1, "NEUTRO": 2}
        out.sort(key=lambda x: (order.get(x["cenario"], 9), -abs(x["change_pct"])))
        return jsonify(out)

    @app.route("/api/reversals")
    def api_reversals():
        """Possíveis contra-tendências com força >= 40"""
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            rev = entry.get("reversal", {})
            if rev.get("has"):
                d = entry["data"]
                out.append({
                    "symbol":    sym,
                    "name":      d["name"],
                    "price":     d["price"],
                    "rsi":       d["rsi"],
                    "direction": rev["dir"],
                    "strength":  rev["strength"],
                    "reasons":   rev["reasons"],
                })
        out.sort(key=lambda x: -x["strength"])
        return jsonify(out)

    @app.route("/api/mode", methods=["POST"])
    def api_mode():
        data = request.get_json(force=True) or {}
        mode = data.get("mode", "")
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]:
            return jsonify({"error": "inválido"}), 400
        bot.set_mode(mode); return jsonify({"ok": True})

    @app.route("/api/timeframe", methods=["POST"])
    def api_timeframe():
        data = request.get_json(force=True) or {}
        tf = data.get("timeframe", "")
        if tf not in Config.TIMEFRAMES:
            return jsonify({"error": "inválido"}), 400
        bot.set_timeframe(tf); return jsonify({"ok": True})

    @app.route("/api/resetpausa", methods=["POST"])
    def api_reset():
        bot.reset_pause(); return jsonify({"ok": True})

    return app


def run_api(bot):
    port = int(os.getenv("PORT", 8080))
    app = create_api(bot)
    log(f"🌐 Servidor HTTP: http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


# ══════════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def main():
    log("🔌 Iniciando Bot Sniper v7 – All-in-One...")
    try:
        requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=8)
    except: pass

    bot = TradingBot()
    load_state(bot)

    api_thread = threading.Thread(target=run_api, args=(bot,), daemon=True)
    api_thread.start()

    bot.build_menu()
    if bot._restore_msg:
        bot.send(bot._restore_msg); bot._restore_msg = None

    try: bot.send_news()
    except: pass

    while True:
        try:
            url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates?offset={bot.last_id+1}&timeout=5"
            r = requests.get(url, timeout=12).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]
                    if "message" in u:
                        txt = u["message"].get("text", "").strip().lower()
                        if txt in ("/noticias","/news"): bot.send_news()
                        elif txt == "/status": bot.send_status()
                        elif txt in ("/placar","/score"): bot.send_placar()
                        elif txt in ("/menu","/start"): bot.build_menu()
                        elif txt == "/resetpausa": bot.reset_pause()
                    if "callback_query" in u:
                        cb = u["callback_query"]["data"]
                        cid = u["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery",
                                      json={"callback_query_id": cid}, timeout=5)
                        if cb.startswith("set_tf_"): bot.set_timeframe(cb.replace("set_tf_",""))
                        elif cb.startswith("set_"):  bot.set_mode(cb.replace("set_",""))
                        elif cb == "tf_menu": bot.build_tf_menu()
                        elif cb == "main_menu": bot.build_menu()
                        elif cb == "news": bot.send_news()
                        elif cb == "status": bot.send_status()
                        elif cb == "placar": bot.send_placar()

            bot.maybe_send_news()
            bot.scan()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)
        except Exception as e:
            log(f"Erro loop: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
