# -*- coding: utf-8 -*-
"""
BOT SNIPER – ESTRATÉGIA CURINGA (v6.0)
══════════════════════════════════════════════════════════════════
HISTÓRICO
  v3  → EMA, MACD, Volume, Trailing Stop, /status, /placar
  v4  → ATR-based SL/TP, Circuit Breaker, ADX, Filtro H1,
         Cooldown, MAX_TRADES, MIN_CONFLUENCE=5
  v4.1→ Aviso de trades restaurados, flag session_alerted
  v4.x→ Timeframe dinâmico via botões Telegram
  v5  → Multi-mercado: FOREX / CRIPTO / COMMODITIES / ÍNDICES / TUDO
         Horário por categoria, resolução de símbolo automática

NOVIDADES v6 — Fluxo de alertas completo e acionável:
  ① ⚠️  RADAR         → Tendência detectada, preço AINDA não chegou
                         no gatilho. Mostra: gatilho, SL estimado,
                         TP estimado, ratio, instrução clara.
  ② 🔔  GATILHO       → Preço CHEGOU no nível de entrada. Alerta
                         separado: "ENTRE AGORA, aqui estão os níveis".
  ③ 🎯  SINAL         → Confluência confirmada. Card operacional
                         completo para abrir o trade na plataforma.
  ④ ⚡  CONFLUÊNCIA   → Gatilho atingido mas score insuficiente.
         INSUFICIENTE    Bot NÃO entrou; mostra quais filtros falharam.
  • Décimos de preço adaptados por ativo (forex 5d, cripto 2d…)
  • Formatação de preço inteligente por magnitude do ativo
  • Novo dict gatilho_list para anti-spam do alerta de gatilho
══════════════════════════════════════════════════════════════════
"""
import os, time, json, math, requests, pandas as pd, xml.etree.ElementTree as ET
import threading
from datetime import datetime, timedelta, timezone

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
                "POL-USD":   "Polygon (POL)",   "LTC-USD":   "Litecoin",
            },
        },
        "COMMODITIES": {
            "label": "🏅 COMMODITIES",
            "assets": {
                "GC=F": "Ouro",          "SI=F": "Prata",
                "CL=F": "Petróleo WTI",  "BZ=F": "Petróleo Brent",
                "NG=F": "Gás Natural",    "HG=F": "Cobre",
                "ZC=F": "Milho",          "ZW=F": "Trigo",
                "ZS=F": "Soja",           "PL=F": "Platina",
            },
        },
        "INDICES": {
            "label": "📊 ÍNDICES",
            "assets": {
                "ES=F":      "S&P 500",      "NQ=F":      "Nasdaq 100",
                "YM=F":      "Dow Jones",    "RTY=F":     "Russell 2000",
                "^GDAXI":    "DAX",          "^FTSE":     "FTSE 100",
                "^N225":     "Nikkei",       "^BVSP":     "IBOVESPA",
                "^HSI":      "Hang Seng",    "^STOXX50E": "Euro Stoxx 50",
            },
        },
    }

    # ── Gestão de risco ──────────────────────────────────────────
    ATR_MULT_SL    = 1.5   # SL  = entrada ± 1.5×ATR
    ATR_MULT_TP    = 3.0   # TP  = entrada ± 3.0×ATR  (ratio 2:1)
    ATR_MULT_TRAIL = 1.2   # Trailing = pico ± 1.2×ATR

    # ── Circuit Breaker ──────────────────────────────────────────
    MAX_CONSECUTIVE_LOSSES = 2
    PAUSE_DURATION         = 3600   # 1 hora

    # ── Filtros ──────────────────────────────────────────────────
    ADX_MIN        = 22
    MAX_TRADES     = 3
    ASSET_COOLDOWN = 3600   # 1h cooldown por ativo após loss
    MIN_CONFLUENCE = 5      # de 7 fatores

    # ── Timers de alertas ────────────────────────────────────────
    RADAR_COOLDOWN   = 1800  # 30min entre radares do mesmo ativo
    GATILHO_COOLDOWN = 300   # 5min entre alertas de gatilho (anti-spam)

    # ── Timeframes ───────────────────────────────────────────────
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
    FOREX_OPEN_UTC  = 7;  FOREX_CLOSE_UTC = 17
    COMM_OPEN_UTC   = 7;  COMM_CLOSE_UTC  = 21
    IDX_OPEN_UTC    = 7;  IDX_CLOSE_UTC   = 21

    # ── Contra-Tendência (exclusivo FOREX) ─────────────────────
    MIN_CONFLUENCE_CT  = 4     # de 7 fatores de reversão
    REVERSAL_COOLDOWN  = 2700  # 45min entre alertas de reversão

    NEWS_INTERVAL = 7200
    SCAN_INTERVAL = 30
    STATE_FILE    = "bot_state.json"


# ── Formatação inteligente de preço ─────────────────────────────
def fmt(price: float) -> str:
    """Casas decimais adaptadas à magnitude do preço."""
    if price == 0:
        return "0"
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 10:
        return f"{price:.4f}"
    if price >= 1:
        return f"{price:.5f}"
    return f"{price:.6f}"


def log(msg):
    ts = datetime.now(Config.BR_TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ══════════════════════════════════════════════════════════════════
# HELPERS DE SÍMBOLO E MERCADO
# ══════════════════════════════════════════════════════════════════
def to_yf_symbol(symbol: str) -> str:
    if "-" in symbol:          return symbol
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
    now     = datetime.now(timezone.utc)
    h, wd   = now.hour, now.weekday()
    if category == "CRYPTO":
        return True
    if wd >= 5:
        return False
    if category == "FOREX":
        return Config.FOREX_OPEN_UTC <= h < Config.FOREX_CLOSE_UTC
    if category == "COMMODITIES":
        return Config.COMM_OPEN_UTC  <= h < Config.COMM_CLOSE_UTC
    if category == "INDICES":
        return Config.IDX_OPEN_UTC   <= h < Config.IDX_CLOSE_UTC
    return True   # TUDO


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
        "gatilho_list":       bot.gatilho_list,
        "reversal_list":      bot.reversal_list,
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
        bot.mode               = data.get("mode",               "CRYPTO")
        bot.timeframe          = data.get("timeframe",          Config.TIMEFRAME)
        bot.wins               = data.get("wins",               0)
        bot.losses             = data.get("losses",             0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until       = data.get("paused_until",       0)
        bot.active_trades      = data.get("active_trades",      [])
        bot.radar_list         = data.get("radar_list",         {})
        bot.gatilho_list       = data.get("gatilho_list",       {})
        bot.reversal_list      = data.get("reversal_list",      {})
        bot.asset_cooldown     = data.get("asset_cooldown",     {})
        bot.history            = data.get("history",            [])

        for t in bot.active_trades:
            t["session_alerted"] = False

        log(f"[STATE] {bot.wins}W/{bot.losses}L | "
            f"{len(bot.active_trades)} trade(s) | "
            f"Modo: {bot.mode} | TF: {bot.timeframe}")

        if bot.active_trades:
            lines = ["♻️ <b>BOT REINICIADO – TRADES ATIVOS RESTAURADOS</b>\n"]
            for t in bot.active_trades:
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                lines.append(
                    f"📌 <b>{t['symbol']}</b> ({t.get('name', t['symbol'])})  {dl}\n"
                    f"   Aberto: {t.get('opened_at','?')}  |  "
                    f"Entrada: <code>{fmt(t['entry'])}</code>\n"
                    f"   🎯 TP: <code>{fmt(t['tp'])}</code>  "
                    f"🛡 SL: <code>{fmt(t['sl'])}</code>"
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
    ("CoinDesk",         "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph",    "https://cointelegraph.com/rss"),
    ("Decrypt",          "https://decrypt.co/feed"),
    ("Yahoo Finance",    "https://finance.yahoo.com/rss/topfinstories"),
    ("SeekingAlpha",     "https://seekingalpha.com/market_currents.xml"),
]

def _parse_rss(url, source_name, max_results=3):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"}
    r       = requests.get(url, headers=headers, timeout=8)
    r.raise_for_status()
    root    = ET.fromstring(r.content)
    items   = (root.findall(".//item") or
               root.findall(".//{http://www.w3.org/2005/Atom}entry"))
    out = []
    for item in items[:max_results]:
        title = (item.findtext("title") or
                 item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link  = (item.findtext("link") or
                 item.findtext("{http://www.w3.org/2005/Atom}link") or "").strip()
        if title and link:
            out.append({"title": title, "url": link, "source": source_name})
    return out

def get_news(max_results=5):
    articles = []
    for name, url in RSS_FEEDS:
        if len(articles) >= max_results:
            break
        try:
            articles.extend(_parse_rss(url, name, 2))
        except Exception as e:
            log(f"[RSS] {name}: {e}")
    return articles[:max_results]

def get_fear_greed():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6).json()["data"][0]
        return f"{d['value']} – {d['value_classification']}"
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
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{t}</a> <i>({a['source']})</i>")
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
        ema9    = closes.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21   = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        sp200   = min(200, len(closes) - 1)
        ema200  = closes.ewm(span=sp200, adjust=False).mean().iloc[-1]

        # ── Bollinger Bands ──────────────────────────────────────
        w          = min(20, len(closes) - 1)
        sma20      = closes.rolling(w).mean().iloc[-1]
        std20      = closes.rolling(w).std().iloc[-1]
        upper_band = sma20 + std20 * 2
        lower_band = sma20 - std20 * 2

        # ── RSI 14 ──────────────────────────────────────────────
        delta   = closes.diff()
        gain    = delta.where(delta > 0, 0).rolling(14).mean()
        loss    = (-delta.where(delta < 0, 0)).rolling(14).mean()
        cur_rsi = (100 - 100 / (1 + gain / loss)).iloc[-1]

        # ── MACD (12,26,9) ───────────────────────────────────────
        ema12       = closes.ewm(span=12, adjust=False).mean()
        ema26       = closes.ewm(span=26, adjust=False).mean()
        macd_hist   = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
        macd_bull   = macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2]
        macd_bear   = macd_hist.iloc[-1] < 0 and macd_hist.iloc[-1] < macd_hist.iloc[-2]

        # ── Volume ───────────────────────────────────────────────
        if use_volume and volume.sum() > 0:
            vol_avg   = volume.rolling(20).mean().iloc[-1]
            vol_cur   = volume.iloc[-1]
            vol_ok    = bool(vol_cur > vol_avg) if vol_avg > 0 else False
            vol_ratio = vol_cur / vol_avg if vol_avg > 0 else 0
        else:
            vol_ok    = True
            vol_ratio = 0

        # ── ATR 14 ───────────────────────────────────────────────
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        # ── ADX 14 (Wilder) ──────────────────────────────────────
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd > 0) & (hd > -ld), 0.0)
        mdm = (-ld).where((-ld > 0) & (-ld > hd), 0.0)
        atr_s   = tr.ewm(alpha=1/14, adjust=False).mean()
        pdi     = 100 * pdm.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        mdi     = 100 * mdm.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        dx      = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-10)
        adx     = dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1]

        cur_price    = closes.iloc[-1]
        trigger_buy  = highs.tail(5).max()   # rompimento de máxima dos últimos 5 candles
        trigger_sell = lows.tail(5).min()    # rompimento de mínima dos últimos 5 candles

        # ── Cenário base ──────────────────────────────────────────
        cenario = "NEUTRO"
        if cur_price > ema200 and ema9 > ema21:
            cenario = "ALTA"
        elif cur_price < ema200 and ema9 < ema21:
            cenario = "BAIXA"

        # ── Filtro timeframe superior ─────────────────────────────
        h1_bull = h1_bear = False
        sup_tf  = "1h"  if timeframe in ("1m","5m","15m","30m") else "1d"
        sup_per = "60d" if sup_tf == "1h" else "2y"
        try:
            dh = yf.Ticker(yf_symbol).history(period=sup_per, interval=sup_tf)
            if len(dh) >= 50:
                ch     = dh["Close"]
                e21h   = ch.ewm(span=21,       adjust=False).mean().iloc[-1]
                e200h  = ch.ewm(span=min(200, len(ch)-1), adjust=False).mean().iloc[-1]
                ph     = ch.iloc[-1]
                h1_bull = ph > e21h and e21h > e200h
                h1_bear = ph < e21h and e21h < e200h
        except Exception as eh:
            log(f"[H-SUP] {symbol}: {eh}")

        return {
            "symbol":    symbol,
            "name":      asset_name(symbol),
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
# MOTOR DE CONTRA-TENDÊNCIA (exclusivo FOREX)
# Detecta exaustão de tendência e sinais de reversão usando:
#   • RSI divergência (preço vs RSI em direções opostas)
#   • Bollinger Band extremo (preço fora ou tocando a banda)
#   • RSI sobrecomprado / sobrevendido (>75 / <25)
#   • MACD divergência (histograma contradiz o preço)
#   • Padrões de candle de reversão (engolfo, martelo, estrela,
#     doji, hanging man, shooting star)
#   • Wick rejection (sombra longa rejeitando nível)
#   • ADX alto (tendência madura = maior risco de exaustão)
# ══════════════════════════════════════════════════════════════════
def detect_candle_patterns(df):
    """
    Detecta padrões de reversão nos últimos 2 candles.
    Retorna (pattern_bull, pattern_bear, pattern_name).
    """
    if len(df) < 3:
        return False, False, ""

    o1, h1, l1, c1 = (df["Open"].iloc[-2], df["High"].iloc[-2],
                       df["Low"].iloc[-2],  df["Close"].iloc[-2])
    o0, h0, l0, c0 = (df["Open"].iloc[-1], df["High"].iloc[-1],
                       df["Low"].iloc[-1],  df["Close"].iloc[-1])

    body0     = abs(c0 - o0)
    body1     = abs(c1 - o1)
    rng0      = h0 - l0 if h0 != l0 else 1e-10
    upper_wick= h0 - max(c0, o0)
    lower_wick= min(c0, o0) - l0
    bull0     = c0 > o0
    bear0     = c0 < o0
    bull1     = c1 > o1
    bear1     = c1 < o1

    pattern_bull = False
    pattern_bear = False
    name         = ""

    # Engolfo de alta
    if bull0 and bear1 and c0 > o1 and o0 < c1:
        pattern_bull = True
        name = "Engolfo de Alta 🕯"

    # Engolfo de baixa
    elif bear0 and bull1 and c0 < o1 and o0 > c1:
        pattern_bear = True
        name = "Engolfo de Baixa 🕯"

    # Martelo (hammer) – reversão de baixa para alta
    elif (lower_wick > body0 * 2 and upper_wick < body0 * 0.5
          and body0 < rng0 * 0.4):
        pattern_bull = True
        name = "Martelo (Hammer) 🔨"

    # Estrela Cadente (shooting star) – reversão de alta para baixa
    elif (upper_wick > body0 * 2 and lower_wick < body0 * 0.5
          and body0 < rng0 * 0.4):
        pattern_bear = True
        name = "Estrela Cadente 🌠"

    # Doji (indecisão)
    elif body0 < rng0 * 0.1:
        # Doji no topo → baixista; no fundo → altista (contexto externo decide)
        pattern_bull = True
        pattern_bear = True
        name = "Doji ✤"

    # Pin Bar de alta (grande wick inferior)
    elif lower_wick > rng0 * 0.6 and body0 < rng0 * 0.25:
        pattern_bull = True
        name = "Pin Bar de Alta 📌"

    # Pin Bar de baixa (grande wick superior)
    elif upper_wick > rng0 * 0.6 and body0 < rng0 * 0.25:
        pattern_bear = True
        name = "Pin Bar de Baixa 📌"

    return pattern_bull, pattern_bear, name


def get_reversal_analysis(symbol, timeframe=None):
    """
    Análise completa de contra-tendência para FOREX.
    Retorna dict com todos os sinais de reversão ou None.
    """
    import yfinance as yf

    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf_symbol(symbol)
    period    = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]

    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 30:
            return None

        closes = df["Close"]
        highs  = df["High"]
        lows   = df["Low"]

        cur_price = closes.iloc[-1]

        # ── Bollinger Bands ──────────────────────────────────────
        w          = min(20, len(closes) - 1)
        sma20      = closes.rolling(w).mean()
        std20      = closes.rolling(w).std()
        upper_band = (sma20 + std20 * 2).iloc[-1]
        lower_band = (sma20 - std20 * 2).iloc[-1]
        bb_width   = (upper_band - lower_band) / sma20.iloc[-1]  # largura %

        above_upper = cur_price >= upper_band
        below_lower = cur_price <= lower_band
        near_upper  = cur_price >= upper_band * 0.998   # 0.2% da banda
        near_lower  = cur_price <= lower_band * 1.002

        # ── RSI ──────────────────────────────────────────────────
        delta      = closes.diff()
        gain       = delta.where(delta > 0, 0).rolling(14).mean()
        loss       = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi_series = 100 - 100 / (1 + gain / loss)
        cur_rsi    = rsi_series.iloc[-1]
        prev_rsi   = rsi_series.iloc[-2]

        rsi_overbought  = cur_rsi > 75
        rsi_oversold    = cur_rsi < 25

        # ── RSI Divergência ───────────────────────────────────────
        # Janela de 10 candles: preço faz novo extremo, RSI não confirma
        lookback = 10
        recent_high   = closes.tail(lookback).max()
        recent_low    = closes.tail(lookback).min()
        rsi_at_high   = rsi_series.iloc[-lookback:][closes.tail(lookback) == recent_high].mean()
        rsi_at_low    = rsi_series.iloc[-lookback:][closes.tail(lookback) == recent_low].mean()
        prev_high     = closes.iloc[-lookback*2:-lookback].max()
        prev_low      = closes.iloc[-lookback*2:-lookback].min()
        prev_rsi_high = rsi_series.iloc[-lookback*2:-lookback].max()
        prev_rsi_low  = rsi_series.iloc[-lookback*2:-lookback].min()

        # Divergência bearish: preço faz máxima mais alta, RSI faz máxima mais baixa
        div_bear = (recent_high > prev_high and
                    not (rsi_at_high > prev_rsi_high) and
                    cur_rsi > 55)
        # Divergência bullish: preço faz mínima mais baixa, RSI faz mínima mais alta
        div_bull = (recent_low < prev_low and
                    not (rsi_at_low < prev_rsi_low) and
                    cur_rsi < 45)

        # ── MACD Divergência ──────────────────────────────────────
        ema12      = closes.ewm(span=12, adjust=False).mean()
        ema26      = closes.ewm(span=26, adjust=False).mean()
        macd_hist  = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()
        # Divergência: MACD histograma caindo enquanto preço sobe (bearish)
        macd_div_bear = (closes.iloc[-1] > closes.iloc[-3] and
                         macd_hist.iloc[-1] < macd_hist.iloc[-3])
        # Divergência: MACD histograma subindo enquanto preço cai (bullish)
        macd_div_bull = (closes.iloc[-1] < closes.iloc[-3] and
                         macd_hist.iloc[-1] > macd_hist.iloc[-3])

        # ── ATR ──────────────────────────────────────────────────
        tr  = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows  - closes.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]

        # ── ADX ──────────────────────────────────────────────────
        hd      = highs.diff(); ld = lows.diff()
        pdm     = hd.where((hd > 0) & (hd > -ld), 0.0)
        mdm     = (-ld).where((-ld > 0) & (-ld > hd), 0.0)
        atr_s   = tr.ewm(alpha=1/14, adjust=False).mean()
        pdi     = 100 * pdm.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        mdi     = 100 * mdm.ewm(alpha=1/14, adjust=False).mean() / (atr_s + 1e-10)
        dx      = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-10)
        adx     = dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1]
        adx_mature = adx > 30   # tendência madura → maior risco de exaustão

        # ── Wick Rejection ───────────────────────────────────────
        rng0        = highs.iloc[-1] - lows.iloc[-1] or 1e-10
        upper_wick  = highs.iloc[-1] - max(closes.iloc[-1], df["Open"].iloc[-1])
        lower_wick  = min(closes.iloc[-1], df["Open"].iloc[-1]) - lows.iloc[-1]
        wick_bear   = upper_wick > rng0 * 0.5   # wick superior longo
        wick_bull   = lower_wick > rng0 * 0.5   # wick inferior longo

        # ── Padrões de candle ────────────────────────────────────
        pat_bull, pat_bear, pat_name = detect_candle_patterns(df)

        # ── Determina direção do sinal de reversão ───────────────
        # SELL reversal: preço sobrecomprado, divergências bearish
        signal_sell_ct = (near_upper or rsi_overbought or div_bear or macd_div_bear)
        # BUY reversal: preço sobrevendido, divergências bullish
        signal_buy_ct  = (near_lower or rsi_oversold  or div_bull or macd_div_bull)

        if not (signal_sell_ct or signal_buy_ct):
            return None

        return {
            "symbol":        symbol,
            "name":          asset_name(symbol),
            "price":         cur_price,
            "rsi":           cur_rsi,
            "atr":           atr,
            "adx":           adx,
            "upper_band":    upper_band,
            "lower_band":    lower_band,
            "bb_width":      bb_width,
            "above_upper":   above_upper,
            "below_lower":   below_lower,
            "near_upper":    near_upper,
            "near_lower":    near_lower,
            "rsi_overbought":rsi_overbought,
            "rsi_oversold":  rsi_oversold,
            "div_bear":      div_bear,
            "div_bull":      div_bull,
            "macd_div_bear": macd_div_bear,
            "macd_div_bull": macd_div_bull,
            "adx_mature":    adx_mature,
            "wick_bear":     wick_bear,
            "wick_bull":     wick_bull,
            "pat_bull":      pat_bull,
            "pat_bear":      pat_bear,
            "pat_name":      pat_name,
            "signal_sell_ct":signal_sell_ct,
            "signal_buy_ct": signal_buy_ct,
        }
    except Exception as e:
        log(f"[CT] {symbol}: {e}")
        return None


def calc_reversal_confluence(res, direcao):
    """
    Confluência de contra-tendência (7 fatores de reversão).
    direcao: "BUY" (reversão de queda→alta) ou "SELL" (reversão de alta→queda)
    """
    if direcao == "SELL":
        checks = [
            ("RSI sobrecomprado (>75)",    res["rsi_overbought"]),
            ("Preço na Banda Superior BB", res["near_upper"]),
            ("RSI divergência bearish",    res["div_bear"]),
            ("MACD divergência bearish",   res["macd_div_bear"]),
            ("Padrão candle de baixa",     res["pat_bear"]),
            ("Wick de rejeição superior",  res["wick_bear"]),
            ("ADX tendência madura (>30)", res["adx_mature"]),
        ]
    else:
        checks = [
            ("RSI sobrevendido (<25)",     res["rsi_oversold"]),
            ("Preço na Banda Inferior BB", res["near_lower"]),
            ("RSI divergência bullish",    res["div_bull"]),
            ("MACD divergência bullish",   res["macd_div_bull"]),
            ("Padrão candle de alta",      res["pat_bull"]),
            ("Wick de rejeição inferior",  res["wick_bull"]),
            ("ADX tendência madura (>30)", res["adx_mature"]),
        ]
    score = sum(1 for _, ok in checks if ok)
    return score, len(checks), checks

# ══════════════════════════════════════════════════════════════════
# CONFLUÊNCIA (7 fatores)
# ══════════════════════════════════════════════════════════════════
def calc_confluence(res, direcao):
    if direcao == "BUY":
        checks = [
            ("EMA 200 (preço acima)",    res["price"]  > res["ema200"]),
            ("EMA 9 acima da 21",        res["ema9"]   > res["ema21"]),
            ("MACD em alta",             res["macd_bull"]),
            ("Volume / Liquidez OK",     res["vol_ok"]),
            ("RSI abaixo de 65",         res["rsi"] < 65),
            ("TF Superior em alta",      res["h1_bull"]),
            ("ADX força tendência",      res["adx"] > Config.ADX_MIN),
        ]
    else:
        checks = [
            ("EMA 200 (preço abaixo)",   res["price"]  < res["ema200"]),
            ("EMA 9 abaixo da 21",       res["ema9"]   < res["ema21"]),
            ("MACD em queda",            res["macd_bear"]),
            ("Volume / Liquidez OK",     res["vol_ok"]),
            ("RSI acima de 35",          res["rsi"] > 35),
            ("TF Superior em queda",     res["h1_bear"]),
            ("ADX força tendência",      res["adx"] > Config.ADX_MIN),
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
        self.radar_list         = {}    # {symbol: ts} último alerta RADAR
        self.gatilho_list       = {}    # {symbol: ts} último alerta GATILHO
        self.reversal_list      = {}    # {symbol: ts} último alerta REVERSÃO
        self.asset_cooldown     = {}    # {symbol: ts} cooldown pós-loss
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
        tf_label   = Config.TIMEFRAMES.get(self.timeframe, ("?",""))[0]
        mode_label = (Config.MARKET_CATEGORIES[self.mode]["label"]
                      if self.mode != "TUDO" else "🌍 TUDO")
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

        mkt_status = []
        for cat, info in Config.MARKET_CATEGORIES.items():
            icon = "🟢" if market_open(cat) else "🔴"
            mkt_status.append(f"{icon} {info['label']}")

        cb_txt = ""
        if self.is_paused():
            mins   = int((self.paused_until - time.time()) / 60)
            cb_txt = f"\n⛔ <b>CIRCUIT BREAKER</b> – retoma em {mins}min"

        self.send(
            f"<b>🎛 BOT SNIPER v6 – MULTI-MERCADO</b>\n"
            f"Placar: <code>{self.wins}W – {self.losses}L</code>  ({winrate:.1f}%)\n"
            f"Losses seguidos: <code>{self.consecutive_losses}</code>  "
            f"(limite: {Config.MAX_CONSECUTIVE_LOSSES})\n"
            f"Modo: <b>{mode_label}</b>  |  TF: <code>{self.timeframe}</code> {tf_label}\n"
            f"Gestão: SL={Config.ATR_MULT_SL}×ATR  TP={Config.ATR_MULT_TP}×ATR\n\n"
            f"<b>Mercados:</b>\n" + "  |  ".join(mkt_status) + cb_txt,
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
            "🔴 1m / 5m  → mais sinais, mais risco\n"
            "🟡 15m / 30m→ equilíbrio risco/retorno\n"
            "🔵 1h / 4h  → menos sinais, mais segurança\n"
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
            f"⚠️ <i>Trades abertos mantêm os níveis anteriores.\n"
            f"Novos sinais usarão {tf}.</i>"
        )
        self.build_menu()

    # ── Menu Mercado ─────────────────────────────────────────────
    def set_mode(self, mode):
        valid = list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]
        if mode not in valid:
            return
        self.mode  = mode
        label      = (Config.MARKET_CATEGORIES[mode]["label"]
                      if mode != "TUDO" else "🌍 TUDO")
        n = len(all_symbols()) if mode == "TUDO" else len(Config.MARKET_CATEGORIES[mode]["assets"])
        save_state(self)
        log(f"[MODE] → {mode}")
        self.send(f"✅ <b>Modo: {label}</b> — escaneando <b>{n} ativos</b>.")
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
        if self.is_paused():
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
                f"{em} <b>{t['symbol']}</b> ({t.get('name','-')})  "
                f"{t['dir']} | {t.get('opened_at','?')}\n"
                f"   Entrada: <code>{fmt(t['entry'])}</code>  "
                f"Atual: <code>{fmt(cur)}</code>\n"
                f"   P&amp;L: <code>{pnl:+.2f}%</code>  "
                f"SL: <code>{fmt(t['sl'])}</code>  TP: <code>{fmt(t['tp'])}</code>"
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

    # ══════════════════════════════════════════════════════════════
    # SCAN — FLUXO DE 4 FASES
    # ══════════════════════════════════════════════════════════════
    def scan(self):
        if self.is_paused():
            mins = int((self.paused_until - time.time()) / 60)
            log(f"⛔ Pausado. Retoma em {mins}min.")
            return

        if len(self.active_trades) >= Config.MAX_TRADES:
            log(f"⚠️ Limite de {Config.MAX_TRADES} trades atingido.")
            return

        universe = all_symbols() if self.mode == "TUDO" else \
                   list(Config.MARKET_CATEGORIES[self.mode]["assets"].keys())

        log(f"🔎 Varrendo {self.mode} ({len(universe)} ativos, TF {self.timeframe})...")

        for s in universe:
            cat = asset_category(s)
            if not market_open(cat):
                continue
            if any(t["symbol"] == s for t in self.active_trades):
                continue
            cd_rem = Config.ASSET_COOLDOWN - (time.time() - self.asset_cooldown.get(s, 0))
            if cd_rem > 0:
                log(f"[COOL] {s} cooldown {int(cd_rem/60)}min.")
                continue

            res = get_analysis(s, self.timeframe)
            if not res or res["cenario"] == "NEUTRO":
                continue

            price      = res["price"]
            name       = res["name"]
            cat_label  = Config.MARKET_CATEGORIES.get(cat, {}).get("label", cat)
            atr        = res["atr"]
            cenario    = res["cenario"]

            # ── Preços estimados de SL/TP (calculados no gatilho) ──
            if cenario == "ALTA":
                gatilho    = res["t_buy"]
                sl_est     = gatilho - Config.ATR_MULT_SL * atr
                tp_est     = gatilho + Config.ATR_MULT_TP * atr
                dir_simple = "BUY"
                preco_ok   = price >= gatilho and price < res["upper"] and res["rsi"] < 70
            else:
                gatilho    = res["t_sell"]
                sl_est     = gatilho + Config.ATR_MULT_SL * atr
                tp_est     = gatilho - Config.ATR_MULT_TP * atr
                dir_simple = "SELL"
                preco_ok   = price <= gatilho and price > res["lower"] and res["rsi"] > 30

            sl_pct_est = abs(gatilho - sl_est) / gatilho * 100
            tp_pct_est = abs(tp_est  - gatilho) / gatilho * 100
            ratio_str  = f"1:{Config.ATR_MULT_TP / Config.ATR_MULT_SL:.1f}"

            # ══════════════════════════════════════════════════════
            # FASE 1 — ⚠️ RADAR
            # Preço ainda NÃO chegou no gatilho. Avisa o que está
            # se formando e o que o usuário deve esperar.
            # ══════════════════════════════════════════════════════
            if not preco_ok:
                if time.time() - self.radar_list.get(s, 0) > Config.RADAR_COOLDOWN:
                    dir_label  = "COMPRA 🟢" if dir_simple == "BUY" else "VENDA 🔴"
                    dist_pct   = abs(price - gatilho) / price * 100
                    self.send(
                        f"⚠️ <b>RADAR – {s}</b> ({name})\n"
                        f"{cat_label}  |  TF: <code>{self.timeframe}</code>\n\n"
                        f"📡 Tendência de <b>{cenario}</b> detectada\n"
                        f"Aguardando preço chegar no gatilho de <b>{dir_label}</b>\n\n"
                        f"──────────────────────\n"
                        f"🎯 Gatilho de entrada: <code>{fmt(gatilho)}</code>\n"
                        f"📍 Preço atual:        <code>{fmt(price)}</code>  "
                        f"({dist_pct:.2f}% de distância)\n"
                        f"──────────────────────\n"
                        f"🛡 Stop Loss est.:  <code>{fmt(sl_est)}</code>  ({-sl_pct_est:.2f}%)\n"
                        f"🎯 Take Profit est.:<code>{fmt(tp_est)}</code>  ({tp_pct_est:+.2f}%)\n"
                        f"⚖️ Ratio estimado:   <b>{ratio_str}</b>\n"
                        f"──────────────────────\n"
                        f"RSI: <code>{res['rsi']:.1f}</code>  "
                        f"ADX: <code>{res['adx']:.1f}</code>  "
                        f"ATR: <code>{fmt(atr)}</code>\n\n"
                        f"🕐 <i>Você receberá um alerta quando o preço "
                        f"atingir <code>{fmt(gatilho)}</code></i>"
                    )
                    self.radar_list[s] = time.time()
                continue   # Preço ainda não chegou, não abre trade

            # ══════════════════════════════════════════════════════
            # FASE 2 — 🔔 GATILHO ATINGIDO
            # Preço chegou no nível. Avisa IMEDIATAMENTE com todas
            # as informações necessárias para entrar na plataforma.
            # ══════════════════════════════════════════════════════
            if time.time() - self.gatilho_list.get(s, 0) > Config.GATILHO_COOLDOWN:
                dir_label = "COMPRAR (BUY) 🟢" if dir_simple == "BUY" else "VENDER (SELL) 🔴"
                self.send(
                    f"🔔 <b>GATILHO ATINGIDO – {s}</b> ({name})\n"
                    f"{cat_label}  |  TF: <code>{self.timeframe}</code>\n\n"
                    f"✅ Preço chegou no nível de entrada!\n\n"
                    f"▶️ <b>AÇÃO: {dir_label}</b>\n\n"
                    f"──────────────────────\n"
                    f"💰 Entrada agora:    <code>{fmt(price)}</code>\n"
                    f"🛡 Stop Loss:        <code>{fmt(sl_est)}</code>  ({-sl_pct_est:.2f}%)\n"
                    f"🎯 Take Profit:      <code>{fmt(tp_est)}</code>  ({tp_pct_est:+.2f}%)\n"
                    f"⚖️ Ratio risco:retorno: <b>{ratio_str}</b>\n"
                    f"──────────────────────\n"
                    f"RSI: <code>{res['rsi']:.1f}</code>  "
                    f"ADX: <code>{res['adx']:.1f}</code>\n\n"
                    f"⏳ <i>Verificando confluência…</i>"
                )
                self.gatilho_list[s] = time.time()

            # ══════════════════════════════════════════════════════
            # FASE 3 — Verificação de confluência
            # ══════════════════════════════════════════════════════
            score, total_c, checks = calc_confluence(res, dir_simple)
            bar      = confluence_bar(score, total_c)
            conf_txt = "\n".join(
                f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)
            vol_txt  = (f"{res['vol_ratio']:.1f}x média"
                        if res["vol_ratio"] > 0 else "N/A (índice/futuro)")

            # ── FASE 4A — ⚡ Confluência insuficiente ─────────────
            if score < Config.MIN_CONFLUENCE:
                log(f"[SINAL] {s} {dir_simple} – confluência {score}/{total_c}")
                falhou = [nm for nm, ok in checks if not ok]
                self.send(
                    f"⚡ <b>CONFLUÊNCIA INSUFICIENTE – {s}</b>\n\n"
                    f"Gatilho foi atingido mas o bot <b>NÃO entrou</b>.\n"
                    f"Score: <code>{score}/{total_c}</code>  [{bar}]  "
                    f"(mínimo: {Config.MIN_CONFLUENCE})\n\n"
                    f"<b>Filtros que falharam:</b>\n"
                    + "\n".join(f"   ❌ {nm}" for nm in falhou) +
                    f"\n\n<i>Aguardando melhor configuração…</i>"
                )
                continue

            # ── FASE 4B — 🎯 SINAL CONFIRMADO — Card operacional ──
            # Recalcula com preço exato atual
            if dir_simple == "BUY":
                sl = price - Config.ATR_MULT_SL * atr
                tp = price + Config.ATR_MULT_TP * atr
            else:
                sl = price + Config.ATR_MULT_SL * atr
                tp = price - Config.ATR_MULT_TP * atr

            sl_pct = abs(price - sl) / price * 100
            tp_pct = abs(tp - price) / price * 100
            dl     = "COMPRAR (BUY) 🟢" if dir_simple == "BUY" else "VENDER (SELL) 🔴"

            self.send(
                f"🎯 <b>SINAL CONFIRMADO – {s}</b> ({name})\n"
                f"{cat_label}  |  TF: <code>{self.timeframe}</code>\n\n"
                f"╔══════════════════════╗\n"
                f"  ▶️  <b>{dl}</b>\n"
                f"╚══════════════════════╝\n\n"
                f"💰 <b>Entrada:</b>     <code>{fmt(price)}</code>\n"
                f"🛡 <b>Stop Loss:</b>   <code>{fmt(sl)}</code>  ({-sl_pct:.2f}%)\n"
                f"🎯 <b>Take Profit:</b> <code>{fmt(tp)}</code>  ({tp_pct:+.2f}%)\n"
                f"⚖️ <b>Ratio:</b>       <b>{ratio_str}</b>  "
                f"(arrisca {sl_pct:.2f}% p/ ganhar {tp_pct:.2f}%)\n\n"
                f"──────────────────────\n"
                f"ATR(14): <code>{fmt(atr)}</code>  "
                f"ADX: <code>{res['adx']:.1f}</code>  "
                f"RSI: <code>{res['rsi']:.1f}</code>\n"
                f"Volume: <code>{vol_txt}</code>\n\n"
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
            self.radar_list[s]   = time.time()
            self.gatilho_list[s] = time.time()
            save_state(self)


    # ══════════════════════════════════════════════════════════════
    # SCAN CONTRA-TENDÊNCIA — exclusivo FOREX
    # ══════════════════════════════════════════════════════════════
    def scan_reversal_forex(self):
        """
        Scanner híbrido de reversão para os pares FOREX.
        Opera na direção OPOSTA à tendência atual quando detecta
        exaustão com pelo menos MIN_CONFLUENCE_CT fatores confirmados.
        Sinal enviado separadamente do scanner de tendência principal.
        """
        if self.is_paused():
            return
        if not market_open("FOREX"):
            return
        if len(self.active_trades) >= Config.MAX_TRADES:
            return

        forex_symbols = list(Config.MARKET_CATEGORIES["FOREX"]["assets"].keys())
        log(f"⚡ Scan CT-FOREX ({len(forex_symbols)} pares, TF {self.timeframe})...")

        for s in forex_symbols:
            # Não abre contra-tendência se já há trade aberto nesse par
            if any(t["symbol"] == s for t in self.active_trades):
                continue

            # Cooldown pós-loss
            cd_rem = Config.ASSET_COOLDOWN - (time.time() - self.asset_cooldown.get(s, 0))
            if cd_rem > 0:
                continue

            # Cooldown anti-spam para alertas de reversão
            if time.time() - self.reversal_list.get(s, 0) < Config.REVERSAL_COOLDOWN:
                continue

            res = get_reversal_analysis(s, self.timeframe)
            if not res:
                continue

            price = res["price"]
            name  = res["name"]
            atr   = res["atr"]

            # Decide a direção do sinal de reversão
            # Prioridade: se ambos ativos, escolhe o com mais fatores confirmados
            dir_sell = "SELL" if res["signal_sell_ct"] else None
            dir_buy  = "BUY"  if res["signal_buy_ct"]  else None

            candidates = []
            for d in [dir_sell, dir_buy]:
                if d is None:
                    continue
                sc, tc, ch = calc_reversal_confluence(res, d)
                candidates.append((sc, tc, ch, d))

            if not candidates:
                continue

            # Escolhe a direção com maior score
            candidates.sort(key=lambda x: x[0], reverse=True)
            score, total_c, checks, dir_simple = candidates[0]

            if score < Config.MIN_CONFLUENCE_CT:
                log(f"[CT] {s} {dir_simple} ignorado – {score}/{total_c}")
                continue

            bar      = confluence_bar(score, total_c)
            conf_txt = "\n".join(
                f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)

            # SL/TP via ATR (ratio 1:1.5 para contra-tendência — mais conservador)
            ct_sl_mult = Config.ATR_MULT_SL
            ct_tp_mult = Config.ATR_MULT_SL * 1.5   # ratio 1:1.5 (mais conservador)
            if dir_simple == "BUY":
                sl = price - ct_sl_mult * atr
                tp = price + ct_tp_mult * atr
            else:
                sl = price + ct_sl_mult * atr
                tp = price - ct_tp_mult * atr

            sl_pct  = abs(price - sl) / price * 100
            tp_pct  = abs(tp - price) / price * 100
            ratio   = f"1:{ct_tp_mult / ct_sl_mult:.1f}"
            dl      = "COMPRAR (BUY) 🟢" if dir_simple == "BUY" else "VENDER (SELL) 🔴"

            # Monta resumo dos sinais detectados
            sinais = []
            if dir_simple == "SELL":
                if res["rsi_overbought"]:  sinais.append(f"RSI sobrecomprado ({res['rsi']:.1f})")
                if res["near_upper"]:      sinais.append(f"Preço na BB superior ({fmt(res['upper_band'])})")
                if res["div_bear"]:        sinais.append("RSI divergência bearish")
                if res["macd_div_bear"]:   sinais.append("MACD divergência bearish")
                if res["wick_bear"]:       sinais.append("Wick de rejeição superior")
                if res["pat_bear"] and res["pat_name"]: sinais.append(f"Padrão: {res['pat_name']}")
            else:
                if res["rsi_oversold"]:    sinais.append(f"RSI sobrevendido ({res['rsi']:.1f})")
                if res["near_lower"]:      sinais.append(f"Preço na BB inferior ({fmt(res['lower_band'])})")
                if res["div_bull"]:        sinais.append("RSI divergência bullish")
                if res["macd_div_bull"]:   sinais.append("MACD divergência bullish")
                if res["wick_bull"]:       sinais.append("Wick de rejeição inferior")
                if res["pat_bull"] and res["pat_name"]: sinais.append(f"Padrão: {res['pat_name']}")

            sinais_txt = "\n".join(f"   ⚡ {s_}" for s_ in sinais)

            self.send(
                f"⚡ <b>CONTRA-TENDÊNCIA FOREX – {s}</b> ({name})\n"
                f"📈 FOREX  |  TF: <code>{self.timeframe}</code>\n\n"
                f"🔄 <i>Sinal de reversão detectado — operação CONTRA a tendência</i>\n\n"
                f"╔══════════════════════╗\n"
                f"  ▶️  <b>{dl}</b>\n"
                f"╚══════════════════════╝\n\n"
                f"💰 <b>Entrada:</b>     <code>{fmt(price)}</code>\n"
                f"🛡 <b>Stop Loss:</b>   <code>{fmt(sl)}</code>  ({-sl_pct:.2f}%)\n"
                f"🎯 <b>Take Profit:</b> <code>{fmt(tp)}</code>  ({tp_pct:+.2f}%)\n"
                f"⚖️ <b>Ratio:</b>       <b>{ratio}</b>\n\n"
                f"──────────────────────\n"
                f"<b>Sinais de exaustão detectados:</b>\n{sinais_txt}\n\n"
                f"ADX: <code>{res['adx']:.1f}</code>  "
                f"RSI: <code>{res['rsi']:.1f}</code>  "
                f"ATR: <code>{fmt(atr)}</code>\n\n"
                f"<b>Confluência: {score}/{total_c}  [{bar}]</b>\n"
                f"{conf_txt}\n\n"
                f"⚠️ <i>Operação contra a tendência — use gestão de risco reduzida.</i>"
            )

            self.reversal_list[s] = time.time()

            self.active_trades.append({
                "symbol":          s,
                "name":            name,
                "entry":           price,
                "tp":              tp,
                "sl":              sl,
                "dir":             dir_simple,
                "peak":            price,
                "atr":             atr,
                "tipo":            "CONTRA-TENDÊNCIA ⚡",
                "opened_at":       datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "session_alerted": True,
            })
            self.reversal_list[s] = time.time()
            save_state(self)

    # ══════════════════════════════════════════════════════════════
    # MONITOR + TRAILING STOP
    # ══════════════════════════════════════════════════════════════
    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res:
                continue
            cur = res["price"]
            atr = res["atr"]

            # Reanunciar trade restaurado (bot reiniciado)
            if not t.get("session_alerted", True):
                dl     = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                sl_pct = abs(t["entry"] - t["sl"]) / t["entry"] * 100
                tp_pct = abs(t["tp"] - t["entry"]) / t["entry"] * 100
                self.send(
                    f"📌 <b>TRADE RESTAURADO – {t['symbol']}</b> ({t.get('name','')})\n\n"
                    f"Ação: <b>{dl}</b>  |  Aberto: {t.get('opened_at','?')}\n"
                    f"Entrada: <code>{fmt(t['entry'])}</code>  "
                    f"Atual: <code>{fmt(cur)}</code>\n"
                    f"🎯 TP: <code>{fmt(t['tp'])}</code>  ({tp_pct:+.2f}%)\n"
                    f"🛡 SL: <code>{fmt(t['sl'])}</code>  ({-sl_pct:.2f}%)"
                )
                t["session_alerted"] = True
                changed = True

            # Trailing Stop via ATR
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl    = cur - Config.ATR_MULT_TRAIL * atr
                if new_sl > t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL {fmt(t['sl'])}→{fmt(new_sl)}")
                    t["sl"]  = new_sl
                    changed  = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur
                new_sl    = cur + Config.ATR_MULT_TRAIL * atr
                if new_sl < t["sl"]:
                    log(f"[TRAIL] {t['symbol']} SL {fmt(t['sl'])}→{fmt(new_sl)}")
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
                    self.wins               += 1
                    self.consecutive_losses  = 0
                else:
                    self.losses             += 1
                    self.consecutive_losses += 1
                    self.asset_cooldown[t["symbol"]] = time.time()
                    log(f"[COOL] Cooldown 1h: {t['symbol']}")

                self.history.append({
                    "symbol":    t["symbol"],
                    "dir":       t["dir"],
                    "result":    "WIN" if is_win else "LOSS",
                    "pnl":       round(pnl, 2),
                    "closed_at": closed_at,
                })

                self.send(
                    f"🏁 <b>OPERAÇÃO ENCERRADA</b>\n"
                    f"Ativo: <b>{t['symbol']}</b> ({t.get('name','')})\n"
                    f"Tipo: <b>{t.get('tipo', 'Tendência 📈')}</b>  |  {t['dir']}  |  Aberto: {t.get('opened_at','?')}\n"
                    f"Resultado: <b>{status}</b>\n\n"
                    f"💰 Entrada: <code>{fmt(t['entry'])}</code>\n"
                    f"🔚 Saída:   <code>{fmt(cur)}</code>\n"
                    f"P&amp;L:   <code>{pnl:+.2f}%</code>"
                )
                self.active_trades.remove(t)
                changed = True
                self.build_menu()

                # Circuit Breaker
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    mins = Config.PAUSE_DURATION // 60
                    log(f"[CB] ⛔ {self.consecutive_losses} losses → pausa {mins}min.")
                    self.send(
                        f"⛔ <b>CIRCUIT BREAKER ATIVADO</b>\n\n"
                        f"🔴 {self.consecutive_losses} losses consecutivos detectados.\n"
                        f"🕐 Bot pausado por <b>{mins} minutos</b>.\n\n"
                        f"Use /resetpausa para retomar antes do prazo."
                    )

        if changed:
            save_state(self)




# ══════════════════════════════════════════════════════════════════
# LOOP DO BOT (roda em thread separada)
# ══════════════════════════════════════════════════════════════════
def bot_loop(bot):
    """Loop principal do bot em thread de background."""
    bot.send_news()
    while True:
        try:
            url = (f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                   f"/getUpdates?offset={bot.last_id + 1}&timeout=5")
            r = requests.get(url, timeout=12).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]

                    if "message" in u:
                        txt = u["message"].get("text", "").strip().lower()
                        if txt in ("/noticias", "/news"):   bot.send_news()
                        elif txt == "/status":              bot.send_status()
                        elif txt in ("/placar", "/score"):  bot.send_placar()
                        elif txt in ("/menu", "/start"):    bot.build_menu()
                        elif txt == "/resetpausa":          bot.reset_pause()

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
                        elif cb == "tf_menu":     bot.build_tf_menu()
                        elif cb == "main_menu":   bot.build_menu()
                        elif cb == "news":        bot.send_news()
                        elif cb == "status":      bot.send_status()
                        elif cb == "placar":      bot.send_placar()
                        else:                     bot.build_menu()

            bot.maybe_send_news()
            bot.scan()
            bot.scan_reversal_forex()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)

        except Exception as e:
            log(f"Erro no loop: {e}")
            time.sleep(10)


# ══════════════════════════════════════════════════════════════════
# API REST — Flask na thread principal (obrigatório para Railway)
# ══════════════════════════════════════════════════════════════════
def main():
    log("🔌 Iniciando Bot Sniper v6.1 – Híbrido Tendência + Contra-Tendência FOREX...")
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

    # Bot loop em thread de background
    t = threading.Thread(target=bot_loop, args=(bot,), daemon=True)
    t.start()

    # Flask na thread PRINCIPAL — Railway roteia para cá
    try:
        from flask import Flask, jsonify, request as freq
        from flask_cors import CORS
    except ImportError:
        log("[API] Instale: pip install flask flask-cors")
        # fallback: roda só o bot sem API
        bot_loop(bot)
        return

    app = Flask(__name__)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    @app.after_request
    def add_cors(response):
        response.headers["Access-Control-Allow-Origin"]  = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.route("/api/health")
    def api_health():
        return jsonify({"status": "ok", "version": "6.1"})

    @app.route("/api/status")
    def api_status():
        total   = bot.wins + bot.losses
        winrate = round(bot.wins / total * 100, 1) if total > 0 else 0
        paused  = bot.is_paused()
        trades  = []
        for t_ in bot.active_trades:
            try:
                res = get_analysis(t_["symbol"], bot.timeframe)
                cur = res["price"] if res else t_["entry"]
            except:
                cur = t_["entry"]
            pnl = (cur - t_["entry"]) / t_["entry"] * 100
            if t_["dir"] == "SELL":
                pnl = -pnl
            trades.append({
                "symbol":    t_["symbol"],
                "name":      t_.get("name", t_["symbol"]),
                "dir":       t_["dir"],
                "tipo":      t_.get("tipo", "Tendência 📈"),
                "entry":     t_["entry"],
                "current":   cur,
                "tp":        t_["tp"],
                "sl":        t_["sl"],
                "pnl":       round(pnl, 2),
                "opened_at": t_.get("opened_at", ""),
            })
        return jsonify({
            "mode":               bot.mode,
            "timeframe":          bot.timeframe,
            "wins":               bot.wins,
            "losses":             bot.losses,
            "winrate":            winrate,
            "consecutive_losses": bot.consecutive_losses,
            "paused":             paused,
            "cb_mins":            int((bot.paused_until - time.time()) / 60) if paused else 0,
            "active_trades":      trades,
            "markets": {
                cat: market_open(cat)
                for cat in list(Config.MARKET_CATEGORIES.keys()) + ["CRYPTO"]
            },
        })

    @app.route("/api/history")
    def api_history():
        return jsonify(list(reversed(bot.history[-30:])))

    @app.route("/api/config")
    def api_config():
        return jsonify({
            "timeframes": list(Config.TIMEFRAMES.keys()),
            "tf_labels":  {k: v[0] for k, v in Config.TIMEFRAMES.items()},
            "modes":      list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"],
            "atm_sl":     Config.ATR_MULT_SL,
            "atr_tp":     Config.ATR_MULT_TP,
            "max_trades": Config.MAX_TRADES,
            "min_conf":   Config.MIN_CONFLUENCE,
        })

    @app.route("/api/mode", methods=["POST", "OPTIONS"])
    def api_set_mode():
        if freq.method == "OPTIONS":
            return jsonify({}), 200
        data = freq.get_json(force=True) or {}
        mode = data.get("mode", "")
        valid = list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]
        if mode not in valid:
            return jsonify({"error": "modo inválido"}), 400
        bot.set_mode(mode)
        return jsonify({"ok": True, "mode": mode})

    @app.route("/api/timeframe", methods=["POST", "OPTIONS"])
    def api_set_timeframe():
        if freq.method == "OPTIONS":
            return jsonify({}), 200
        data = freq.get_json(force=True) or {}
        tf   = data.get("timeframe", "")
        if tf not in Config.TIMEFRAMES:
            return jsonify({"error": "TF inválido"}), 400
        bot.set_timeframe(tf)
        return jsonify({"ok": True, "timeframe": tf})

    @app.route("/api/resetpausa", methods=["POST", "OPTIONS"])
    def api_reset_pausa():
        if freq.method == "OPTIONS":
            return jsonify({}), 200
        bot.reset_pause()
        return jsonify({"ok": True})

    port = int(os.getenv("PORT", 8080))
    log(f"[API] Flask rodando na porta {port} (thread principal)...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
