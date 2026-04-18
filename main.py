# -*- coding: utf-8 -*-
"""
BOT SNIPER – ESTRATÉGIA CURINGA (v5.0)
══════════════════════════════════════════════════════════════════
HISTÓRICO DE VERSÕES
  v3 → EMA real, MACD, Volume, Trailing Stop, /status, /placar
  v4 → SL/TP via ATR, Circuit Breaker, ADX, Filtro H1,
        Cooldown por ativo, MAX_TRADES, MIN_CONFLUENCE=5
  v4.1 → Aviso de trades restaurados, flag session_alerted
  v4.x → Timeframe dinâmico via Telegram (1m→4h)

NOVIDADES v5:
  • 5 categorias de mercado operáveis pelo Telegram:
      FOREX      – 10 pares principais + cruzamentos
      CRIPTO     – 12 ativos (BTC, ETH, SOL, BNB, XRP…)
      COMMODITIES– Ouro, Prata, Petróleo WTI/Brent, Gás, Cobre
      ÍNDICES    – S&P500, Nasdaq, Dow, DAX, IBOV, Nikkei, FTSE
      TUDO       – Todos os ativos acima em paralelo
  • Resolução inteligente de símbolo por tipo de ativo
      Forex  → agrega "=X"   (ex: EURUSD=X)
      Crypto → usa diretamente (ex: BTC-USD)
      Futures→ já tem "=F"   (ex: GC=F)
      Índices→ já tem "^"    (ex: ^GSPC)
  • Horário de mercado por categoria (FOREX, COMMODITIES, ÍNDICES)
  • Volume ignorado para índices/futuros (dado não-confiável)
  • Confluência adaptada: 6 fatores com H1 + ADX
══════════════════════════════════════════════════════════════════
"""
import os, time, json, math, requests, pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ══════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════
class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ      = timezone(timedelta(hours=-3))

    # ── Ativos por categoria ────────────────────────────────────
    # Símbolo : nome amigável
    MARKET_CATEGORIES = {
        "FOREX": {
            "label":   "📈 FOREX",
            "assets": {
                "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
                "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
                "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
                "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
                "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY",
            }
        },
        "CRYPTO": {
            "label":   "₿ CRIPTO",
            "assets": {
                "BTC-USD":  "Bitcoin",  "ETH-USD":  "Ethereum",
                "SOL-USD":  "Solana",   "BNB-USD":  "BNB",
                "XRP-USD":  "XRP",      "ADA-USD":  "Cardano",
                "DOGE-USD": "Dogecoin", "AVAX-USD": "Avalanche",
                "LINK-USD": "Chainlink","DOT-USD":  "Polkadot",
                "MATIC-USD":"Polygon",  "LTC-USD":  "Litecoin",
            }
        },
        "COMMODITIES": {
            "label":   "🏅 COMMODITIES",
            "assets": {
                "GC=F": "Ouro",           "SI=F": "Prata",
                "CL=F": "Petróleo WTI",   "BZ=F": "Petróleo Brent",
                "NG=F": "Gás Natural",     "HG=F": "Cobre",
                "ZC=F": "Milho",           "ZW=F": "Trigo",
                "ZS=F": "Soja",            "PL=F": "Platina",
            }
        },
        "INDICES": {
            "label":   "📊 ÍNDICES",
            "assets": {
                "ES=F":   "S&P 500",   "NQ=F":   "Nasdaq 100",
                "YM=F":   "Dow Jones", "RTY=F":  "Russell 2000",
                "^GDAXI": "DAX",       "^FTSE":  "FTSE 100",
                "^N225":  "Nikkei",    "^BVSP":  "IBOVESPA",
                "^HSI":   "Hang Seng", "^STOXX50E": "Euro Stoxx 50",
            }
        },
    }

    # ── Gestão de risco via ATR ─────────────────────────────────
    ATR_MULT_SL    = 1.5   # SL  = preço ± 1.5 × ATR
    ATR_MULT_TP    = 3.0   # TP  = preço ± 3.0 × ATR  (ratio 2:1)
    ATR_MULT_TRAIL = 1.2   # Trailing = pico ± 1.2 × ATR

    # ── Circuit Breaker ─────────────────────────────────────────
    MAX_CONSECUTIVE_LOSSES = 2
    PAUSE_DURATION         = 3600   # 1 hora

    # ── Filtros ─────────────────────────────────────────────────
    ADX_MIN        = 22
    MAX_TRADES     = 3     # Aumentado para comportar mais categorias
    ASSET_COOLDOWN = 3600  # 1 hora de cooldown por ativo após loss
    MIN_CONFLUENCE = 5     # de 7 fatores

    # ── Timeframes ──────────────────────────────────────────────
    TIMEFRAMES = {
        "1m":  ("🔴 Agressivo",    "7d"),
        "5m":  ("🟠 Alto",         "5d"),
        "15m": ("🟡 Moderado",     "5d"),
        "30m": ("🟢 Conservador",  "5d"),
        "1h":  ("🔵 Seguro",       "60d"),
        "4h":  ("🟣 Muito Seguro", "60d"),
    }
    TIMEFRAME = "15m"

    # ── Horários de mercado (UTC) ────────────────────────────────
    # FOREX: Londres + NY abertas
    FOREX_OPEN_UTC  = 7
    FOREX_CLOSE_UTC = 17
    # COMMODITIES: futures abertos quase 24h, mas melhor liquidez:
    COMM_OPEN_UTC   = 7
    COMM_CLOSE_UTC  = 21
    # ÍNDICES: janela ampla cobrindo EU + US regular + after-hours
    IDX_OPEN_UTC    = 7
    IDX_CLOSE_UTC   = 21

    NEWS_INTERVAL = 7200
    SCAN_INTERVAL = 30
    STATE_FILE    = "bot_state.json"


def log(msg):
    ts = datetime.now(Config.BR_TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ══════════════════════════════════════════════════════════════════
# HELPERS DE SÍMBOLO E MERCADO
# ══════════════════════════════════════════════════════════════════
def to_yf_symbol(symbol: str) -> str:
    """Converte símbolo interno → símbolo do yfinance."""
    if "-" in symbol:          return symbol          # BTC-USD → BTC-USD
    if symbol.startswith("^"): return symbol          # ^GDAXI  → ^GDAXI
    if symbol.endswith("=F"):  return symbol          # GC=F    → GC=F
    return f"{symbol}=X"                              # EURUSD  → EURUSD=X


def asset_category(symbol: str) -> str:
    """Retorna a categoria de um símbolo."""
    for cat, info in Config.MARKET_CATEGORIES.items():
        if symbol in info["assets"]:
            return cat
    return "CRYPTO"


def volume_reliable(symbol: str) -> bool:
    """Volume de índices e alguns futuros não é confiável no yfinance."""
    cat = asset_category(symbol)
    return cat not in ("INDICES",)


def all_symbols() -> list:
    syms = []
    for cat in Config.MARKET_CATEGORIES.values():
        syms.extend(cat["assets"].keys())
    return syms


def market_open(category: str) -> bool:
    """Verifica se o mercado da categoria está aberto (UTC)."""
    now_utc   = datetime.now(timezone.utc)
    hour_utc  = now_utc.hour
    weekday   = now_utc.weekday()   # 0=Mon … 6=Sun

    if category == "CRYPTO":
        return True                 # 24/7
    if weekday >= 5:                # Fds fechados para os demais
        return False
    if category == "FOREX":
        return Config.FOREX_OPEN_UTC <= hour_utc < Config.FOREX_CLOSE_UTC
    if category == "COMMODITIES":
        return Config.COMM_OPEN_UTC <= hour_utc < Config.COMM_CLOSE_UTC
    if category == "INDICES":
        return Config.IDX_OPEN_UTC  <= hour_utc < Config.IDX_CLOSE_UTC
    if category == "TUDO":
        # Aberto se pelo menos CRYPTO (sempre) ou outro mercado aberto
        return True
    return False


# ══════════════════════════════════════════════════════════════════
# PERSISTÊNCIA
# ══════════════════════════════════════════════════════════════════
def save_state(bot):
    data = {
        "mode":               bot.mode,
        "timeframe":          bot.timeframe,
        "wins":               bot.wins,
        "losses":             bot.losses,
        "consecutive_losses": bot.consecutive_losses,
        "paused_until":       bot.paused_until,
        "active_trades":      bot.active_trades,
        "radar_list":         bot.radar_list,
        "asset_cooldown":     bot.asset_cooldown,
        "history":            bot.history,
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
        bot.mode               = data.get("mode", "CRYPTO")
        bot.timeframe          = data.get("timeframe", Config.TIMEFRAME)
        bot.wins               = data.get("wins", 0)
        bot.losses             = data.get("losses", 0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until       = data.get("paused_until", 0)
        bot.active_trades      = data.get("active_trades", [])
        bot.radar_list         = data.get("radar_list", {})
        bot.asset_cooldown     = data.get("asset_cooldown", {})
        bot.history            = data.get("history", [])

        # Marcar trades restaurados como não-anunciados nesta sessão
        for t in bot.active_trades:
            t["session_alerted"] = False

        log(f"[STATE] Restaurado: {bot.wins}W/{bot.losses}L | "
            f"{len(bot.active_trades)} trade(s) | "
            f"Modo: {bot.mode} | TF: {bot.timeframe}")

        if bot.active_trades:
            lines = ["♻️ <b>BOT REINICIADO – TRADES ATIVOS RESTAURADOS</b>\n"]
            for t in bot.active_trades:
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                lines.append(
                    f"📌 <b>{t['symbol']}</b>  {dl}  |  desde {t.get('opened_at','?')}\n"
                    f"   Entrada: <code>{t['entry']:.5f}</code>  "
                    f"TP: <code>{t['tp']:.5f}</code>  SL: <code>{t['sl']:.5f}</code>"
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
    r       = requests.get(url, headers=headers, timeout=8)
    r.raise_for_status()
    root    = ET.fromstring(r.content)
    items   = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
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
        if len(articles) >= max_results:
            break
        try:
            fetched = _parse_rss(url, name, max_results=2)
            articles.extend(fetched)
            log(f"[RSS] {name}: {len(fetched)}")
        except Exception as e:
            log(f"[RSS] {name} falhou: {e}")
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
        return (f"📰 <b>NOTÍCIAS DO MERCADO</b>\n\nNenhum feed disponível.\n"
                f"😱 <b>Fear &amp; Greed:</b> {fg}")
    lines = ["📰 <b>NOTÍCIAS RELEVANTES DO MERCADO</b>\n"]
    for i, a in enumerate(articles, 1):
        title = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{title}</a> <i>({a['source']})</i>")
    lines.append(f"\n😱 <b>Fear &amp; Greed (Cripto):</b> {fg}")
    lines.append(f"🕐 {datetime.now(Config.BR_TZ).strftime('%H:%M')} (Brasília)")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# MOTOR DE ANÁLISE
# ══════════════════════════════════════════════════════════════════
def get_analysis(symbol, timeframe=None):
    import yfinance as yf

    timeframe  = timeframe or Config.TIMEFRAME
    yf_symbol  = to_yf_symbol(symbol)
    period     = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]
    use_volume = volume_reliable(symbol)

    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 50:
            return None

        closes = df["Close"]
        highs  = df["High"]
        lows   = df["Low"]
        volume = df["Volume"]

        # ── EMAs ────────────────────────────────────────────────
        ema9   = closes.ewm(span=9,   adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21,  adjust=False).mean().iloc[-1]
        span200 = min(200, len(closes) - 1)
        ema200 = closes.ewm(span=span200, adjust=False).mean().iloc[-1]

        # ── Bollinger Bands ──────────────────────────────────────
        window     = min(20, len(closes) - 1)
        sma20      = closes.rolling(window).mean().iloc[-1]
        std20      = closes.rolling(window).std().iloc[-1]
        upper_band = sma20 + std20 * 2
        lower_band = sma20 - std20 * 2

        # ── RSI 14 ──────────────────────────────────────────────
        delta   = closes.diff()
        gain    = delta.where(delta > 0, 0).rolling(14).mean()
        loss    = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs      = gain / loss
        cur_rsi = (100 - 100 / (1 + rs)).iloc[-1]

        # ── MACD (12,26,9) ───────────────────────────────────────
        ema12       = closes.ewm(span=12, adjust=False).mean()
        ema26       = closes.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist   = macd_line - signal_line
        macd_bull   = (macd_hist.iloc[-1] > 0 and
                       macd_hist.iloc[-1] > macd_hist.iloc[-2])
        macd_bear   = (macd_hist.iloc[-1] < 0 and
                       macd_hist.iloc[-1] < macd_hist.iloc[-2])

        # ── Volume ───────────────────────────────────────────────
        if use_volume and volume.sum() > 0:
            vol_avg   = volume.rolling(20).mean().iloc[-1]
            vol_cur   = volume.iloc[-1]
            vol_ok    = bool(vol_cur > vol_avg) if vol_avg > 0 else False
            vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 0
        else:
            vol_ok    = True   # ignorado para índices/futuros sem dados
            vol_ratio = 0

        # ── ATR 14 ───────────────────────────────────────────────
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        # ── ADX 14 (Wilder) ──────────────────────────────────────
        high_diff    = highs.diff()
        low_diff     = lows.diff()
        plus_dm_raw  = high_diff.where(
            (high_diff > 0) & (high_diff > -low_diff), 0.0)
        minus_dm_raw = (-low_diff).where(
            (-low_diff > 0) & (-low_diff > high_diff), 0.0)
        atr_s    = tr.ewm(alpha=1/14, adjust=False).mean()
        plus_di  = 100 * plus_dm_raw.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        minus_di = 100 * minus_dm_raw.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        adx      = dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1]

        cur_price    = closes.iloc[-1]
        trigger_buy  = highs.tail(5).max()
        trigger_sell = lows.tail(5).min()

        # ── Cenário base (TF operado) ─────────────────────────────
        cenario = "NEUTRO"
        if cur_price > ema200 and ema9 > ema21:
            cenario = "ALTA"
        elif cur_price < ema200 and ema9 < ema21:
            cenario = "BAIXA"

        # ── Filtro H1: tendência do timeframe superior ────────────
        # Só se o TF operado for < 1h; para 1h/4h usa o 1d
        h1_bull = h1_bear = False
        h1_tf   = "1h" if timeframe in ("1m","5m","15m","30m") else "1d"
        h1_per  = "60d" if h1_tf == "1h" else "2y"
        try:
            df_h = yf.Ticker(yf_symbol).history(period=h1_per, interval=h1_tf)
            if len(df_h) >= 50:
                c_h      = df_h["Close"]
                ema21_h  = c_h.ewm(span=21, adjust=False).mean().iloc[-1]
                sp_h     = min(200, len(c_h) - 1)
                ema_h    = c_h.ewm(span=sp_h, adjust=False).mean().iloc[-1]
                price_h  = c_h.iloc[-1]
                h1_bull  = price_h > ema21_h and ema21_h > ema_h
                h1_bear  = price_h < ema21_h and ema21_h < ema_h
        except Exception as e_h:
            log(f"[H-SUP] {symbol}: {e_h}")

        name = (Config.MARKET_CATEGORIES
                .get(asset_category(symbol), {})
                .get("assets", {})
                .get(symbol, symbol))

        return {
            "symbol":    symbol,
            "name":      name,
            "price":     cur_price,
            "cenario":   cenario,
            "rsi":       cur_rsi,
            "atr":       atr,
            "adx":       adx,
            "ema9":      ema9,
            "ema21":     ema21,
            "ema200":    ema200,
            "upper":     upper_band,
            "lower":     lower_band,
            "macd_bull": macd_bull,
            "macd_bear": macd_bear,
            "vol_ok":    vol_ok,
            "vol_ratio": vol_ratio,
            "t_buy":     trigger_buy,
            "t_sell":    trigger_sell,
            "h1_bull":   h1_bull,
            "h1_bear":   h1_bear,
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# CONFLUÊNCIA (7 fatores)
# ══════════════════════════════════════════════════════════════════
def calc_confluence(res, direcao):
    if direcao == "BUY":
        checks = [
            ("EMA 200",          res["price"]  > res["ema200"]),
            ("EMA 9 > 21",       res["ema9"]   > res["ema21"]),
            ("MACD Alta",        res["macd_bull"]),
            ("Volume / Liquidez",res["vol_ok"]),
            ("RSI < 65",         res["rsi"] < 65),
            ("TF Superior Alta", res["h1_bull"]),
            ("ADX Tendência",    res["adx"] > Config.ADX_MIN),
        ]
    else:
        checks = [
            ("EMA 200",          res["price"]  < res["ema200"]),
            ("EMA 9 < 21",       res["ema9"]   < res["ema21"]),
            ("MACD Baixa",       res["macd_bear"]),
            ("Volume / Liquidez",res["vol_ok"]),
            ("RSI > 35",         res["rsi"] > 35),
            ("TF Superior Baixa",res["h1_bear"]),
            ("ADX Tendência",    res["adx"] > Config.ADX_MIN),
        ]
    score = sum(1 for _, ok in checks if ok)
    return score, len(checks), checks


def confluence_bar(score, total):
    filled = math.floor(score / total * 5)
    return "█" * filled + "░" * (5 - filled)


# ══════════════════════════════════════════════════════════════════
# BOT PRINCIPAL
# ══════════════════════════════════════════════════════════════════
class TradingBot:
    def __init__(self):
        self.mode               = "CRYPTO"
        self.timeframe          = Config.TIMEFRAME
        self.wins               = 0
        self.losses             = 0
        self.consecutive_losses = 0
        self.paused_until       = 0
        self.active_trades      = []
        self.radar_list         = {}
        self.asset_cooldown     = {}
        self.history            = []
        self.last_id            = 0
        self.last_news_ts       = 0
        self._restore_msg       = None

    # ── Telegram ─────────────────────────────────────────────────
    def send(self, text, markup=None, disable_preview=False):
        url     = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id":                  Config.CHAT_ID,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if markup:
            payload["reply_markup"] = json.dumps(markup)
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            log(f"[SEND] {e}")

    # ── Menu principal ───────────────────────────────────────────
    def build_menu(self):
        tf_label  = Config.TIMEFRAMES.get(self.timeframe, ("?",""))[0]
        mode_info = Config.MARKET_CATEGORIES.get(self.mode, {})
        mode_label= mode_info.get("label", self.mode) if self.mode != "TUDO" else "🌍 TUDO"

        markup = {"inline_keyboard": [
            [{"text": f"📍 Mercado: {mode_label}", "callback_data": "ignore"}],
            [{"text": "📈 FOREX",       "callback_data": "set_FOREX"},
             {"text": "₿ CRIPTO",       "callback_data": "set_CRYPTO"}],
            [{"text": "🏅 COMMODITIES", "callback_data": "set_COMMODITIES"},
             {"text": "📊 ÍNDICES",     "callback_data": "set_INDICES"}],
            [{"text": "🌍 TUDO",        "callback_data": "set_TUDO"}],
            [{"text": f"⏱ Timeframe: {self.timeframe} {tf_label}",
              "callback_data": "tf_menu"}],
            [{"text": "📊 Status",      "callback_data": "status"},
             {"text": "🏆 Placar",      "callback_data": "placar"}],
            [{"text": "📰 Notícias",    "callback_data": "news"},
             {"text": "🔄 Atualizar",   "callback_data": "refresh"}],
        ]}

        total   = self.wins + self.losses
        winrate = (self.wins / total * 100) if total > 0 else 0
        fg      = get_fear_greed()

        # Status de mercado por categoria
        mkt_lines = []
        for cat, info in Config.MARKET_CATEGORIES.items():
            icon = "🟢" if market_open(cat) else "🔴"
            mkt_lines.append(f"{icon} {info['label']}")
        mkt_txt = "  |  ".join(mkt_lines)

        cb_txt = ""
        if time.time() < self.paused_until:
            mins  = int((self.paused_until - time.time()) / 60)
            cb_txt = f"\n⛔ <b>CIRCUIT BREAKER</b> – retoma em {mins}min"

        self.send(
            f"<b>🎛 BOT SNIPER v5 – ESTRATÉGIA CURINGA</b>\n"
            f"Placar: <code>{self.wins}W – {self.losses}L</code>  ({winrate:.1f}%)\n"
            f"Losses seguidos: <code>{self.consecutive_losses}</code>  "
            f"(limite: {Config.MAX_CONSECUTIVE_LOSSES})\n"
            f"Modo: <b>{mode_label}</b>  |  TF: <code>{self.timeframe}</code> {tf_label}\n"
            f"Gestão: SL={Config.ATR_MULT_SL}×ATR  TP={Config.ATR_MULT_TP}×ATR\n\n"
            f"<b>Mercados:</b>\n{mkt_txt}"
            f"{cb_txt}",
            markup
        )

    # ── Menu Timeframe ───────────────────────────────────────────
    def build_tf_menu(self):
        rows = []
        for tf, (label, _) in Config.TIMEFRAMES.items():
            active = " ✅" if tf == self.timeframe else ""
            rows.append([{"text": f"{tf}  {label}{active}",
                          "callback_data": f"set_tf_{tf}"}])
        rows.append([{"text": "« Voltar", "callback_data": "main_menu"}])
        self.send(
            "⏱ <b>SELECIONE O TIMEFRAME</b>\n\n"
            "🔴 1m/5m  = mais sinais, mais risco\n"
            "🟢 30m/1h = menos sinais, mais segurança\n"
            f"\nAtual: <b>{self.timeframe}</b>",
            {"inline_keyboard": rows}
        )

    def set_timeframe(self, tf):
        if tf not in Config.TIMEFRAMES:
            return
        old = self.timeframe
        self.timeframe = tf
        label = Config.TIMEFRAMES[tf][0]
        save_state(self)
        log(f"[TF] {old} → {tf}")
        self.send(
            f"✅ <b>Timeframe alterado:</b> <b>{old}</b> → <b>{tf}</b> {label}\n\n"
            f"⚠️ <i>Trades abertos mantêm os níveis do TF anterior.\n"
            f"Novos sinais usarão {tf}.</i>"
        )
        self.build_menu()

    # ── Menu de Mercado ──────────────────────────────────────────
    def set_mode(self, mode):
        valid = list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]
        if mode not in valid:
            return
        self.mode = mode
        label = (Config.MARKET_CATEGORIES[mode]["label"]
                 if mode != "TUDO" else "🌍 TUDO")
        save_state(self)
        log(f"[MODE] Modo → {mode}")

        # Conta ativos que serão escaneados
        if mode == "TUDO":
            n = len(all_symbols())
        else:
            n = len(Config.MARKET_CATEGORIES[mode]["assets"])

        self.send(f"✅ <b>Modo alterado para {label}</b>\n"
                  f"Escaneando <b>{n} ativos</b>.")
        self.build_menu()

    # ── Notícias ─────────────────────────────────────────────────
    def send_news(self):
        log("📰 Enviando notícias...")
        self.send(build_news_message(), disable_preview=True)
        self.last_news_ts = time.time()

    def maybe_send_news(self):
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL:
            self.send_news()

    # ── /status ──────────────────────────────────────────────────
    def send_status(self):
        lines = ["📊 <b>OPERAÇÕES ABERTAS</b>\n"]
        if time.time() < self.paused_until:
            mins = int((self.paused_until - time.time()) / 60)
            lines.append(f"⛔ Circuit Breaker ativo – retoma em {mins}min\n")
        if not self.active_trades:
            lines.append("Nenhuma operação aberta no momento.")
            self.send("\n".join(lines))
            return
        for t in self.active_trades:
            res = get_analysis(t["symbol"], self.timeframe)
            cur = res["price"] if res else t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL":
                pnl = -pnl
            em = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"{em} <b>{t['symbol']}</b> {t['dir']} | {t.get('opened_at','?')}\n"
                f"   Entrada: <code>{t['entry']:.5f}</code>  "
                f"Atual: <code>{cur:.5f}</code>\n"
                f"   P&amp;L: <code>{pnl:+.2f}%</code>  "
                f"SL: <code>{t['sl']:.5f}</code>  TP: <code>{t['tp']:.5f}</code>"
            )
        self.send("\n".join(lines))

    # ── /placar ──────────────────────────────────────────────────
    def send_placar(self):
        total   = self.wins + self.losses
        winrate = (self.wins / total * 100) if total > 0 else 0
        lines   = [
            "<b>🏆 PLACAR DETALHADO</b>\n",
            f"✅ Wins:            <code>{self.wins}</code>",
            f"❌ Losses:          <code>{self.losses}</code>",
            f"📊 Total:           <code>{total}</code>",
            f"🎯 Winrate:         <code>{winrate:.1f}%</code>",
            f"🔴 Losses seguidos: <code>{self.consecutive_losses}</code>",
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

    # ── Circuit Breaker ──────────────────────────────────────────
    def is_paused(self):
        return time.time() < self.paused_until

    def reset_pause(self):
        self.paused_until       = 0
        self.consecutive_losses = 0
        save_state(self)
        self.send("✅ <b>Circuit Breaker resetado.</b> Bot liberado para operar.")
        log("[CB] Resetado manualmente.")

    # ── Scan ─────────────────────────────────────────────────────
    def scan(self):
        if self.is_paused():
            mins = int((self.paused_until - time.time()) / 60)
            log(f"⛔ Pausado (circuit breaker). Retoma em {mins}min.")
            return

        if len(self.active_trades) >= Config.MAX_TRADES:
            log(f"⚠️ Limite de {Config.MAX_TRADES} trades atingido.")
            return

        # Monta lista de ativos a escanear
        if self.mode == "TUDO":
            universe = all_symbols()
        else:
            universe = list(Config.MARKET_CATEGORIES[self.mode]["assets"].keys())

        log(f"🔎 Varrendo {self.mode} ({len(universe)} ativos)...")

        for s in universe:
            cat = asset_category(s)

            # Verifica horário de mercado por categoria do ativo
            if not market_open(cat):
                continue

            # Já tem trade aberto nesse ativo?
            if any(t["symbol"] == s for t in self.active_trades):
                continue

            # Cooldown após loss
            cd_remaining = Config.ASSET_COOLDOWN - (time.time() - self.asset_cooldown.get(s, 0))
            if cd_remaining > 0:
                log(f"[COOL] {s} em cooldown por {int(cd_remaining/60)}min.")
                continue

            res = get_analysis(s, self.timeframe)
            if not res or res["cenario"] == "NEUTRO":
                continue

            price = res["price"]
            name  = res["name"]

            # ── Radar ──────────────────────────────────────────
            if time.time() - self.radar_list.get(s, 0) > 1800:
                g = res["t_buy"] if res["cenario"] == "ALTA" else res["t_sell"]
                self.send(
                    f"⚠️ <b>RADAR: {s}</b> ({name})\n"
                    f"Tendência: <b>{res['cenario']}</b>  |  ADX: <code>{res['adx']:.1f}</code>\n"
                    f"Gatilho: <code>{g:.5f}</code>  ATR: <code>{res['atr']:.5f}</code>  "
                    f"RSI: <code>{res['rsi']:.1f}</code>"
                )
                self.radar_list[s] = time.time()

            # ── Gatilho ────────────────────────────────────────
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

            # ── Confluência ─────────────────────────────────────
            score, total_c, checks = calc_confluence(res, dir_simple)
            if score < Config.MIN_CONFLUENCE:
                log(f"[SINAL] {s} {dir_simple} ignorado – {score}/{total_c}")
                continue

            bar      = confluence_bar(score, total_c)
            conf_txt = "\n".join(
                f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)
            vol_txt = (f"{res['vol_ratio']:.1f}x média"
                       if res["vol_ratio"] > 0 else "N/A (índice/futuro)")

            # ── SL/TP via ATR ───────────────────────────────────
            atr = res["atr"]
            if dir_simple == "BUY":
                sl = price - Config.ATR_MULT_SL * atr
                tp = price + Config.ATR_MULT_TP * atr
            else:
                sl = price + Config.ATR_MULT_SL * atr
                tp = price - Config.ATR_MULT_TP * atr

            sl_pct = abs(price - sl) / price * 100
            tp_pct = abs(tp - price) / price * 100
            dl     = "BUY 🟢" if dir_simple == "BUY" else "SELL 🔴"
            cat_label = Config.MARKET_CATEGORIES.get(cat, {}).get("label", cat)

            self.send(
                f"🎯 <b>SINAL CONFIRMADO</b>\n"
                f"{cat_label}  |  <b>{s}</b> ({name})\n\n"
                f"Ação: <b>{dl}</b>\n"
                f"Entrada: <code>{price:.5f}</code>\n"
                f"ATR(14): <code>{atr:.5f}</code>  "
                f"ADX: <code>{res['adx']:.1f}</code>  "
                f"RSI: <code>{res['rsi']:.1f}</code>\n"
                f"Volume:  <code>{vol_txt}</code>\n"
                f"──────────────────────\n"
                f"🎯 Take Profit: <code>{tp:.5f}</code>  ({tp_pct:+.2f}%)\n"
                f"🛡 Stop Loss:   <code>{sl:.5f}</code>  ({-sl_pct:.2f}%)\n"
                f"──────────────────────\n"
                f"<b>Confluência: {score}/{total_c}  [{bar}]</b>\n"
                f"{conf_txt}"
            )

            self.active_trades.append({
                "symbol":          s,
                "name":            name,
                "entry":           price,
                "tp":              tp,
                "sl":              sl,
                "dir":             dir_simple,
                "peak":            price,
                "atr":             atr,
                "opened_at":       datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "session_alerted": True,
            })
            self.radar_list[s] = time.time()
            save_state(self)

    # ── Monitor + Trailing Stop ──────────────────────────────────
    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res:
                continue
            cur = res["price"]
            atr = res["atr"]

            # Reanunciar trade restaurado (não alertado nesta sessão)
            if not t.get("session_alerted", True):
                dl     = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                sl_pct = abs(t["entry"] - t["sl"]) / t["entry"] * 100
                tp_pct = abs(t["tp"] - t["entry"]) / t["entry"] * 100
                self.send(
                    f"📌 <b>TRADE RESTAURADO – {t['symbol']}</b>\n\n"
                    f"Ação: <b>{dl}</b>  |  Aberto: {t.get('opened_at','?')}\n"
                    f"Entrada: <code>{t['entry']:.5f}</code>  "
                    f"Atual: <code>{cur:.5f}</code>\n"
                    f"🎯 TP: <code>{t['tp']:.5f}</code>  ({tp_pct:+.2f}%)\n"
                    f"🛡 SL: <code>{t['sl']:.5f}</code>  ({-sl_pct:.2f}%)"
                )
                t["session_alerted"] = True
                changed = True

            # Trailing Stop via ATR
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl = cur - Config.ATR_MULT_TRAIL * atr
                if new_sl > t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL {t['sl']:.5f}→{new_sl:.5f}")
                    t["sl"]  = new_sl
                    changed  = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl = cur + Config.ATR_MULT_TRAIL * atr
                if new_sl < t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL {t['sl']:.5f}→{new_sl:.5f}")
                    t["sl"]  = new_sl
                    changed  = True

            # Encerramento
            is_win  = ((t["dir"] == "BUY"  and cur >= t["tp"]) or
                       (t["dir"] == "SELL" and cur <= t["tp"]))
            is_loss = ((t["dir"] == "BUY"  and cur <= t["sl"]) or
                       (t["dir"] == "SELL" and cur >= t["sl"]))

            if is_win or is_loss:
                status = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                pnl    = (cur - t["entry"]) / t["entry"] * 100
                if t["dir"] == "SELL":
                    pnl = -pnl
                closed_at = datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")

                if is_win:
                    self.wins              += 1
                    self.consecutive_losses = 0
                else:
                    self.losses             += 1
                    self.consecutive_losses += 1
                    self.asset_cooldown[t["symbol"]] = time.time()
                    log(f"[COOL] Cooldown 1h ativado: {t['symbol']}")

                self.history.append({
                    "symbol":    t["symbol"],
                    "dir":       t["dir"],
                    "result":    "WIN" if is_win else "LOSS",
                    "pnl":       round(pnl, 2),
                    "closed_at": closed_at,
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

                # Circuit Breaker
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    mins = Config.PAUSE_DURATION // 60
                    log(f"[CB] ⛔ Ativado! {self.consecutive_losses} losses. Pausa {mins}min.")
                    self.send(
                        f"⛔ <b>CIRCUIT BREAKER ATIVADO</b>\n\n"
                        f"🔴 {self.consecutive_losses} losses consecutivos.\n"
                        f"🕐 Pausado por <b>{mins} minutos</b>.\n\n"
                        f"Use /resetpausa para retomar antes do prazo."
                    )

        if changed:
            save_state(self)


# ══════════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def main():
    log("🔌 Iniciando Bot Sniper v5 – Multi-Mercado...")
    requests.get(
        f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook",
        timeout=8
    )
    bot = TradingBot()
    load_state(bot)
    bot.build_menu()

    if bot._restore_msg:
        bot.send(bot._restore_msg)
        bot._restore_msg = None

    bot.send_news()

    while True:
        try:
            url = (f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                   f"/getUpdates?offset={bot.last_id + 1}&timeout=5")
            r = requests.get(url, timeout=12).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]

                    # Comandos de texto
                    if "message" in u:
                        txt = u["message"].get("text", "").strip().lower()
                        if txt in ("/noticias", "/news"):
                            bot.send_news()
                        elif txt == "/status":
                            bot.send_status()
                        elif txt in ("/placar", "/score"):
                            bot.send_placar()
                        elif txt in ("/menu", "/start"):
                            bot.build_menu()
                        elif txt == "/resetpausa":
                            bot.reset_pause()

                    # Botões inline
                    if "callback_query" in u:
                        cb  = u["callback_query"]["data"]
                        cid = u["callback_query"]["id"]
                        requests.post(
                            f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                            f"/answerCallbackQuery",
                            json={"callback_query_id": cid}, timeout=5,
                        )
                        if cb.startswith("set_tf_"):
                            bot.set_timeframe(cb.replace("set_tf_", ""))
                        elif cb.startswith("set_"):
                            bot.set_mode(cb.replace("set_", ""))
                        elif cb == "tf_menu":
                            bot.build_tf_menu()
                        elif cb == "main_menu":
                            bot.build_menu()
                        elif cb == "news":
                            bot.send_news()
                        elif cb == "status":
                            bot.send_status()
                        elif cb == "placar":
                            bot.send_placar()
                        elif cb in ("refresh", "ignore"):
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
