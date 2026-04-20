# -*- coding: utf-8 -*-
"""
BOT SNIPER v7.2 — Multi-mercado + API HTTP + Dashboard PWA + Push Notifications
═══════════════════════════════════════════════════════════════════════════════
ARQUITETURA: Flask serve o HTML/API direto (1 único app no Railway)
MELHORIAS v7.2 (sobre v7.1):
  • UI Premium: Design system, animações suaves, cards com profundidade
  • Sparklines CSS-only: Tendência visual de preço sem libs externas
  • Virtual Scroll: Renderização eficiente para listas longas de sinais
  • Filtros Instantâneos: Categoria, tendência, RSI sem recarregar página
  • Busca em Tempo Real: Encontrar ativos por símbolo/nome com highlight
  • Performance: Debounce, requestAnimationFrame, cache frontend, diff de dados
  • Real-Time Visual: Indicadores de movimento de preço + pulse em novos sinais
  • Preferências Persistentes: Tema, filtros salvos no localStorage
  • Loading States: Skeleton screens para melhor percepção de carregamento
  • Mobile First: Toques maiores, gestos, layout adaptativo aprimorado
"""
import os, time, json, math, threading, requests
import pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES (INALTERADAS - Lógica original preservada)
# ═══════════════════════════════════════════════════════════════
class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ      = timezone(timedelta(hours=-3))

    MARKET_CATEGORIES = {
        "FOREX": {
            "label": "FOREX",
            "assets": {
                "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
                "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
                "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
                "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
                "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY",
            },
        },
        "CRYPTO": {
            "label": "CRIPTO",
            "assets": {
                "BTC-USD":  "Bitcoin",   "ETH-USD":  "Ethereum",
                "SOL-USD":  "Solana",    "BNB-USD":  "BNB",
                "XRP-USD":  "XRP",       "ADA-USD":  "Cardano",
                "DOGE-USD": "Dogecoin",  "AVAX-USD": "Avalanche",
                "LINK-USD": "Chainlink", "DOT-USD":  "Polkadot",                "POL-USD":  "Polygon",   "LTC-USD":  "Litecoin",
            },
        },
        "COMMODITIES": {
            "label": "COMMODITIES",
            "assets": {
                "GC=F": "Ouro",         "SI=F": "Prata",
                "CL=F": "Petróleo WTI", "BZ=F": "Petróleo Brent",
                "NG=F": "Gás Natural",  "HG=F": "Cobre",
                "ZC=F": "Milho",        "ZW=F": "Trigo",
                "ZS=F": "Soja",         "PL=F": "Platina",
            },
        },
        "INDICES": {
            "label": "INDICES",
            "assets": {
                "ES=F":      "S&P 500",     "NQ=F":      "Nasdaq 100",
                "YM=F":      "Dow Jones",   "RTY=F":     "Russell 2000",
                "^GDAXI":    "DAX",         "^FTSE":     "FTSE 100",
                "^N225":     "Nikkei",      "^BVSP":     "IBOVESPA",
                "^HSI":      "Hang Seng",   "^STOXX50E": "Euro Stoxx 50",
            },
        },
    }

    # Risco
    ATR_MULT_SL    = 1.5
    ATR_MULT_TP    = 3.0
    ATR_MULT_TRAIL = 1.2

    # Circuit Breaker
    MAX_CONSECUTIVE_LOSSES = 2
    PAUSE_DURATION         = 3600

    # Filtros tendência
    ADX_MIN        = 22
    MAX_TRADES     = 3
    ASSET_COOLDOWN = 3600
    MIN_CONFLUENCE = 5

    # Filtros CT
    MIN_CONFLUENCE_CT = 4
    REVERSAL_COOLDOWN = 2700   # 45min entre alertas CT

    # Timers
    RADAR_COOLDOWN   = 1800
    GATILHO_COOLDOWN = 300
    TRENDS_INTERVAL  = 120
    NEWS_INTERVAL    = 7200
    SCAN_INTERVAL    = 30
    TIMEFRAMES = {
        "1m":  ("Agressivo",    "7d"),
        "5m":  ("Alto",         "5d"),
        "15m": ("Moderado",     "5d"),
        "30m": ("Conservador",  "5d"),
        "1h":  ("Seguro",       "60d"),
        "4h":  ("Muito Seguro", "60d"),
    }
    TIMEFRAME = "15m"

    FOREX_OPEN_UTC = 7;  FOREX_CLOSE_UTC = 17
    COMM_OPEN_UTC  = 7;  COMM_CLOSE_UTC  = 21
    IDX_OPEN_UTC   = 7;  IDX_CLOSE_UTC   = 21

    STATE_FILE = "bot_state.json"


def fmt(p: float) -> str:
    if not p: return "0"
    if p >= 10000: return f"{p:,.2f}"
    if p >= 1000:  return f"{p:.2f}"
    if p >= 10:    return f"{p:.4f}"
    if p >= 1:     return f"{p:.5f}"
    return f"{p:.6f}"

def log(msg):
    print(f"[{datetime.now(Config.BR_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


# ═══════════════════════════════════════════════════════════════
# HELPERS DE MERCADO (INALTERADOS)
# ═══════════════════════════════════════════════════════════════
def to_yf(s):
    if "-" in s or s.startswith("^") or s.endswith("=F"): return s
    return f"{s}=X"

def asset_cat(s):
    for cat, info in Config.MARKET_CATEGORIES.items():
        if s in info["assets"]: return cat
    return "CRYPTO"

def asset_name(s):
    for info in Config.MARKET_CATEGORIES.values():
        if s in info["assets"]: return info["assets"][s]
    return s

def vol_reliable(s): return asset_cat(s) not in ("INDICES",)

def all_syms():
    out = []

    for c in Config.MARKET_CATEGORIES.values():
        out.extend(c["assets"].keys())

    return out

def mkt_open(cat):
    now = datetime.now(timezone.utc); h = now.hour; wd = now.weekday()
    if cat == "CRYPTO": return True
    if wd >= 5: return False
    if cat == "FOREX":       return Config.FOREX_OPEN_UTC <= h < Config.FOREX_CLOSE_UTC
    if cat == "COMMODITIES": return Config.COMM_OPEN_UTC  <= h < Config.COMM_CLOSE_UTC
    if cat == "INDICES":     return Config.IDX_OPEN_UTC   <= h < Config.IDX_CLOSE_UTC
    return True


# ═══════════════════════════════════════════════════════════════
# PERSISTÊNCIA (INALTERADA)
# ═══════════════════════════════════════════════════════════════
def save_state(bot):
    data = {
        "mode": bot.mode, "timeframe": bot.timeframe,
        "wins": bot.wins, "losses": bot.losses,
        "consecutive_losses": bot.consecutive_losses,
        "paused_until": bot.paused_until,
        "active_trades": bot.active_trades,
        "radar_list": bot.radar_list,
        "gatilho_list": bot.gatilho_list,
        "reversal_list": bot.reversal_list,
        "asset_cooldown": bot.asset_cooldown,
        "history": bot.history,
    }
    try:
        with open(Config.STATE_FILE, "w") as f: json.dump(data, f, indent=2)
    except Exception as e: log(f"[STATE] {e}")

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
        bot.reversal_list      = data.get("reversal_list", {})
        bot.asset_cooldown     = data.get("asset_cooldown", {})
        bot.history = data.get("history", [])

        for t in bot.active_trades:
            t["session_alerted"] = False
          
        log(f"[STATE] {bot.wins}W/{bot.losses}L | {len(bot.active_trades)} trade(s)")
        if bot.active_trades:
            lines = ["♻️ <b>BOT REINICIADO – TRADES ATIVOS</b>\n"]
            for t in bot.active_trades:
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                lines.append(f"📌 <b>{t['symbol']}</b> {dl} | Entrada: <code>{fmt(t['entry'])}</code> | TP: <code>{fmt(t['tp'])}</code> | SL: <code>{fmt(t['sl'])}</code>")
            bot._restore_msg = "\n".join(lines)
        else: bot._restore_msg = None
    except Exception as e: log(f"[STATE] Erro: {e}")


# ═══════════════════════════════════════════════════════════════
# NOTÍCIAS / FEAR & GREED (INALTERADO)
# ═══════════════════════════════════════════════════════════════
RSS_FEEDS = [
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt",       "https://decrypt.co/feed"),
    ("Yahoo Finance", "https://finance.yahoo.com/rss/topfinstories"),
]

def _parse_rss(url, src, mx=3):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
    r.raise_for_status()
    root  = ET.fromstring(r.content)
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for item in items[:mx]:
        title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link  = (item.findtext("link")  or item.findtext("{http://www.w3.org/2005/Atom}link")  or "").strip()
        if title and link: out.append({"title": title, "url": link, "source": src})
    return out

def get_news(mx=15):
    arts = []
    for name, url in RSS_FEEDS:
        if len(arts) >= mx: break
        try: arts.extend(_parse_rss(url, name, 4))
        except Exception as e: log(f"[RSS] {name}: {e}")
    return arts[:mx]

def get_fear_greed():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6).json()["data"][0]
        return {"value": d["value"], "label": d["value_classification"]}
    except: return {"value": "N/D", "label": ""}

def build_news_msg():
    arts = get_news(5)
    fg = get_fear_greed()
    lines = ["📰 <b>NOTÍCIAS</b>\n"]
    for i, a in enumerate(arts, 1):
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{t}</a> <i>({a['source']})</i>")
    lines.append(f"\n😱 F&amp;G: <b>{fg['value']} – {fg['label']}</b>")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# MOTOR DE ANÁLISE PRINCIPAL (INALTERADO)
# ═══════════════════════════════════════════════════════════════
def get_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe  = timeframe or Config.TIMEFRAME
    yf_symbol  = to_yf(symbol)
    period     = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]
    use_vol    = vol_reliable(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 50: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]; volume = df["Volume"]
        ema9   = closes.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]
        w = min(20, len(closes)-1)
        sma20 = closes.rolling(w).mean().iloc[-1]
        std20 = closes.rolling(w).std().iloc[-1]
        upper = sma20 + std20*2; lower = sma20 - std20*2
        delta = closes.diff()
        gain  = delta.where(delta>0, 0).rolling(14).mean()
        loss  = (-delta.where(delta<0, 0)).rolling(14).mean()
        rsi   = (100 - 100/(1 + gain/loss)).iloc[-1]
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        ml    = ema12 - ema26
        mh    = ml - ml.ewm(span=9, adjust=False).mean()
        macd_bull = bool(mh.iloc[-1] > 0 and mh.iloc[-1] > mh.iloc[-2])
        macd_bear = bool(mh.iloc[-1] < 0 and mh.iloc[-1] < mh.iloc[-2])
        if use_vol and volume.sum() > 0:
            va = volume.rolling(20).mean().iloc[-1]; vc = volume.iloc[-1]
            vol_ok = bool(vc > va) if va > 0 else False
            vol_ratio = float(vc/va) if va > 0 else 0
        else: vol_ok = True; vol_ratio = 0
        tr  = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd>0)&(hd>-ld), 0.0)
        mdm = (-ld).where((-ld>0)&(-ld>hd), 0.0)
        as_ = tr.ewm(alpha=1/14, adjust=False).mean()
        pdi = 100*pdm.ewm(alpha=1/14, adjust=False).mean()/(as_+1e-10)
        mdi = 100*mdm.ewm(alpha=1/14, adjust=False).mean()/(as_+1e-10)
        dx  = 100*(pdi-mdi).abs()/(pdi+mdi+1e-10)
        adx = float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
        price = float(closes.iloc[-1])
        chg   = float((closes.iloc[-1]-closes.iloc[-10])/closes.iloc[-10]*100) if len(closes)>=10 else 0
        cen   = "NEUTRO"
        if price > ema200 and ema9 > ema21:   cen = "ALTA"
        elif price < ema200 and ema9 < ema21: cen = "BAIXA"
        h1b = h1r = False
        sup_tf = "1h" if timeframe in ("1m","5m","15m","30m") else "1d"
        sup_per = "60d" if sup_tf == "1h" else "2y"
        try:
            dh = yf.Ticker(yf_symbol).history(period=sup_per, interval=sup_tf)
            if len(dh) >= 50:
                ch = dh["Close"]
                e21h = ch.ewm(span=21, adjust=False).mean().iloc[-1]
                e200h = ch.ewm(span=min(200,len(ch)-1), adjust=False).mean().iloc[-1]
                ph = ch.iloc[-1]
                h1b = bool(ph > e21h and e21h > e200h)
                h1r = bool(ph < e21h and e21h < e200h)
        except: pass
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price,
            "cenario": cen, "rsi": float(rsi), "atr": atr, "adx": adx,
            "ema9": float(ema9), "ema21": float(ema21), "ema200": float(ema200),
            "upper": float(upper), "lower": float(lower),
            "macd_bull": macd_bull, "macd_bear": macd_bear, "macd_hist": float(mh.iloc[-1]),
            "vol_ok": vol_ok, "vol_ratio": vol_ratio,
            "t_buy": float(highs.tail(5).max()), "t_sell": float(lows.tail(5).min()),
            "h1_bull": h1b, "h1_bear": h1r, "change_pct": chg,
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}"); return None


# ═══════════════════════════════════════════════════════════════
# CONFLUÊNCIA (INALTERADO)
# ═══════════════════════════════════════════════════════════════
def calc_confluence(res, d):
    if d == "BUY":
        checks = [
            ("EMA 200 acima",    res["price"]  > res["ema200"]),
            ("EMA 9 > 21",       res["ema9"]   > res["ema21"]),
            ("MACD Alta",        res["macd_bull"]),
            ("Volume OK",        res["vol_ok"]),
            ("RSI < 65",         res["rsi"] < 65),
            ("TF Superior Alta", res["h1_bull"]),
            ("ADX tendência",    res["adx"] > Config.ADX_MIN),
        ]
    else:        checks = [
            ("EMA 200 abaixo",   res["price"]  < res["ema200"]),
            ("EMA 9 < 21",       res["ema9"]   < res["ema21"]),
            ("MACD Baixa",       res["macd_bear"]),
            ("Volume OK",        res["vol_ok"]),
            ("RSI > 35",         res["rsi"] > 35),
            ("TF Superior Baixa",res["h1_bear"]),
            ("ADX tendência",    res["adx"] > Config.ADX_MIN),
        ]
    sc = sum(1 for _, ok in checks if ok)
    return sc, len(checks), checks

def cbar(sc, tot):
    f = math.floor(sc/tot*5)
    return "█"*f + "░"*(5-f)


# ═══════════════════════════════════════════════════════════════
# MOTOR DE CONTRA-TENDÊNCIA (FOREX) (INALTERADO)
# ═══════════════════════════════════════════════════════════════
def detect_candle_patterns(df):
    if len(df) < 3: return False, False, ""
    o1,h1,l1,c1 = df["Open"].iloc[-2],df["High"].iloc[-2],df["Low"].iloc[-2],df["Close"].iloc[-2]
    o0,h0,l0,c0 = df["Open"].iloc[-1],df["High"].iloc[-1],df["Low"].iloc[-1],df["Close"].iloc[-1]
    body0 = abs(c0-o0); rng0 = h0-l0 or 1e-10
    uw = h0-max(c0,o0); lw = min(c0,o0)-l0
    pb = pb2 = False; nm = ""
    if (c0>o0) and (c1<o1) and c0>o1 and o0<c1:   pb = True;  nm = "Engolfo de Alta"
    elif (c0<o0) and (c1>o1) and c0<o1 and o0>c1: pb2 = True; nm = "Engolfo de Baixa"
    elif lw>body0*2 and uw<body0*0.5 and body0<rng0*0.4: pb = True; nm = "Martelo"
    elif uw>body0*2 and lw<body0*0.5 and body0<rng0*0.4: pb2 = True; nm = "Estrela Cadente"
    elif body0 < rng0*0.1: pb = pb2 = True; nm = "Doji"
    elif lw>rng0*0.6 and body0<rng0*0.25: pb = True; nm = "Pin Bar Alta"
    elif uw>rng0*0.6 and body0<rng0*0.25: pb2 = True; nm = "Pin Bar Baixa"
    return pb, pb2, nm

def get_reversal_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period    = Config.TIMEFRAMES.get(timeframe, ("","5d"))[1]
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 30: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]
        price = float(closes.iloc[-1])
        w = min(20, len(closes)-1)
        sma = closes.rolling(w).mean(); std = closes.rolling(w).std()
        ub = float((sma+std*2).iloc[-1]); lb = float((sma-std*2).iloc[-1])
        delta = closes.diff()
        gain  = delta.where(delta>0,0).rolling(14).mean()
        loss  = (-delta.where(delta<0,0)).rolling(14).mean()
        rsi_s = 100-100/(1+gain/loss)
        rsi   = float(rsi_s.iloc[-1])
        ema12 = closes.ewm(span=12,adjust=False).mean()
        ema26 = closes.ewm(span=26,adjust=False).mean()
        mh    = (ema12-ema26)-(ema12-ema26).ewm(span=9,adjust=False).mean()
        tr    = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()],axis=1).max(axis=1)
        atr   = float(tr.rolling(14).mean().iloc[-1])
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd>0)&(hd>-ld),0.0); mdm = (-ld).where((-ld>0)&(-ld>hd),0.0)
        as_ = tr.ewm(alpha=1/14,adjust=False).mean()
        pdi = 100*pdm.ewm(alpha=1/14,adjust=False).mean()/(as_+1e-10)
        mdi = 100*mdm.ewm(alpha=1/14,adjust=False).mean()/(as_+1e-10)
        adx = float((100*(pdi-mdi).abs()/(pdi+mdi+1e-10)).ewm(alpha=1/14,adjust=False).mean().iloc[-1])
        lb10 = 10
        rh = closes.tail(lb10).max(); rl = closes.tail(lb10).min()
        ph = closes.iloc[-lb10*2:-lb10].max(); pl = closes.iloc[-lb10*2:-lb10].min()
        div_bear = bool(rh > ph and rsi < rsi_s.iloc[-lb10*2:-lb10].max() and rsi > 55)
        div_bull = bool(rl < pl and rsi > rsi_s.iloc[-lb10*2:-lb10].min() and rsi < 45)
        mdiv_bear = bool(closes.iloc[-1]>closes.iloc[-3] and mh.iloc[-1]<mh.iloc[-3])
        mdiv_bull = bool(closes.iloc[-1]<closes.iloc[-3] and mh.iloc[-1]>mh.iloc[-3])
        rng0 = highs.iloc[-1]-lows.iloc[-1] or 1e-10
        uw = highs.iloc[-1]-max(closes.iloc[-1],df["Open"].iloc[-1])
        lw = min(closes.iloc[-1],df["Open"].iloc[-1])-lows.iloc[-1]
        pb, pb2, pnm = detect_candle_patterns(df)
        near_up = price >= ub*0.998; near_dn = price <= lb*1.002
        rsi_ob  = rsi > 75;  rsi_os = rsi < 25
        sig_sell = near_up or rsi_ob or div_bear or mdiv_bear
        sig_buy  = near_dn or rsi_os or div_bull or mdiv_bull
        if not (sig_sell or sig_buy): return None
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price,
            "rsi": rsi, "atr": atr, "adx": adx, "adx_mature": adx>30,
            "upper_band": ub, "lower_band": lb,
            "near_upper": near_up, "near_lower": near_dn,
            "rsi_overbought": rsi_ob, "rsi_oversold": rsi_os,
            "div_bear": div_bear, "div_bull": div_bull,
            "macd_div_bear": mdiv_bear, "macd_div_bull": mdiv_bull,
            "wick_bear": bool(uw>rng0*0.5), "wick_bull": bool(lw>rng0*0.5),
            "pat_bull": pb, "pat_bear": pb2, "pat_name": pnm,
            "signal_sell_ct": sig_sell, "signal_buy_ct": sig_buy,
        }
    except Exception as e:
        log(f"[CT] {symbol}: {e}"); return None

def calc_reversal_conf(res, d):
    if d == "SELL":
        checks = [
            ("RSI sobrecomprado",  res["rsi_overbought"]),            ("Banda Superior BB",  res["near_upper"]),
            ("RSI div. bearish",   res["div_bear"]),
            ("MACD div. bearish",  res["macd_div_bear"]),
            ("Candle de baixa",    res["pat_bear"]),
            ("Wick superior",      res["wick_bear"]),
            ("ADX maduro",         res["adx_mature"]),
        ]
    else:
        checks = [
            ("RSI sobrevendido",   res["rsi_oversold"]),
            ("Banda Inferior BB",  res["near_lower"]),
            ("RSI div. bullish",   res["div_bull"]),
            ("MACD div. bullish",  res["macd_div_bull"]),
            ("Candle de alta",     res["pat_bull"]),
            ("Wick inferior",      res["wick_bull"]),
            ("ADX maduro",         res["adx_mature"]),
        ]
    sc = sum(1 for _, ok in checks if ok)
    return sc, len(checks), checks

def detect_reversal(res):
    """Versão rápida de detecção CT para o cache de tendências."""
    if not res: return (False, None, 0, [])
    motivos = []; forca = 0; dir_rev = None
    rsi = res["rsi"]; price = res["price"]; cen = res["cenario"]
    if cen == "ALTA" or res["ema9"] > res["ema21"]:
        if rsi >= 70:   motivos.append(f"RSI sobrecomprado ({rsi:.0f})"); forca += 30; dir_rev = "SELL"
        if rsi >= 75:   motivos.append("RSI extremo"); forca += 15
        if price >= res["upper"]: motivos.append("Banda superior BB"); forca += 25; dir_rev = "SELL"
        if res["macd_hist"] < 0 and res["ema9"] > res["ema21"]: motivos.append("Div. MACD baixista"); forca += 20; dir_rev = "SELL"
        if res["adx"] < 20 and cen == "ALTA": motivos.append(f"ADX fraco ({res['adx']:.0f})"); forca += 10
    if cen == "BAIXA" or res["ema9"] < res["ema21"]:
        if rsi <= 30:   motivos.append(f"RSI sobrevendido ({rsi:.0f})"); forca += 30; dir_rev = "BUY"
        if rsi <= 25:   motivos.append("RSI extremo"); forca += 15
        if price <= res["lower"]: motivos.append("Banda inferior BB"); forca += 25; dir_rev = "BUY"
        if res["macd_hist"] > 0 and res["ema9"] < res["ema21"]: motivos.append("Div. MACD altista"); forca += 20; dir_rev = "BUY"
        if res["adx"] < 20 and cen == "BAIXA": motivos.append(f"ADX fraco ({res['adx']:.0f})"); forca += 10
    forca = min(forca, 100)
    return (forca >= 40 and dir_rev is not None, dir_rev, forca, motivos)


# ═══════════════════════════════════════════════════════════════
# PUSH NOTIFICATIONS (INALTERADO)
# ═══════════════════════════════════════════════════════════════
_push_subscriptions = []  # lista de subscription dicts

def send_push(title, body, icon="/icon-192.png"):
    """Envia push para todos os clientes inscritos via Web Push."""
    try:
        from pywebpush import webpush, WebPushException
        import os
        priv_key = os.getenv("VAPID_PRIVATE_KEY", "")
        pub_key  = os.getenv("VAPID_PUBLIC_KEY", "")
        email    = os.getenv("VAPID_EMAIL", "mailto:admin@sniperbot.app")
        if not priv_key or not pub_key: return
        data = json.dumps({"title": title, "body": body, "icon": icon})
        dead = []
        for sub in _push_subscriptions:
            try:
                webpush(
                    subscription_info=sub,
                    data=data,
                    vapid_private_key=priv_key,
                    vapid_claims={"sub": email, "aud": sub["endpoint"].split("/")[0]+"//"+sub["endpoint"].split("/")[2]},
                )
            except WebPushException as e:
                if "410" in str(e) or "404" in str(e): dead.append(sub)
            except Exception as e: log(f"[PUSH] {e}")
        for d in dead: _push_subscriptions.remove(d)
    except ImportError: pass
    except Exception as e: log(f"[PUSH] {e}")


# ═══════════════════════════════════════════════════════════════
# BOT PRINCIPAL (INALTERADO)
# ═══════════════════════════════════════════════════════════════
class TradingBot:
    def __init__(self):
        self.mode = "CRYPTO"; self.timeframe = Config.TIMEFRAME
        self.wins = 0; self.losses = 0; self.consecutive_losses = 0
        self.paused_until = 0
        self.active_trades = []
        self.radar_list    = {}
        self.gatilho_list  = {}
        self.reversal_list = {}
        self.asset_cooldown = {}
        self.history = []
        self.last_id = 0; self.last_news_ts = 0
        self._restore_msg = None
        self.trend_cache = {}; self.last_trends_update = 0
        self.signals_feed = []   # feed de sinais para o app
        self.news_cache   = []; self.news_cache_ts = 0

    # ── Telegram + captura de sinais ──────────────────────────
    def send(self, text, markup=None, disable_preview=False):
        import re
        clean = re.sub(r"<[^>]+>", "", text).strip()
        tipo = push_title = push_body = None
        if "RADAR" in text:            tipo = "radar";   push_title = "⚠ RADAR"
        elif "GATILHO ATINGIDO" in text: tipo = "gatilho"; push_title = "🔔 GATILHO ATINGIDO!"
        elif "SINAL CONFIRMADO" in text: tipo = "sinal";   push_title = "🎯 SINAL CONFIRMADO!"
        elif "CONTRA-TENDÊNCIA" in text: tipo = "ct";      push_title = "⚡ Contra-Tendência!"
        elif "CONFLUÊNCIA INSUF" in text: tipo = "insuf"
        elif "OPERAÇÃO ENCERRADA" in text:
            tipo = "close"
            push_title = "🏁 Operação Encerrada"
            push_body  = clean[:80]
        elif "CIRCUIT BREAKER" in text: tipo = "cb"; push_title = "⛔ Circuit Breaker Ativado"
        if tipo:
            # NOVO: Adicionar unix_ts para timer de validade no frontend
            self.signals_feed.append({
                "tipo": tipo, "texto": clean[:300],
                "ts": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "unix_ts": time.time()  # ← NOVO: timestamp Unix para cálculo de validade
            })
            self.signals_feed = self.signals_feed[-50:]
            # Push notification para sinais importantes
            if push_title:
                body = push_body or clean[:100]
                threading.Thread(target=send_push, args=(push_title, body), daemon=True).start()
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text,
                   "parse_mode": "HTML", "disable_web_page_preview": disable_preview}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=8)
        except Exception as e: log(f"[SEND] {e}")

    def build_menu(self):
        tfl = Config.TIMEFRAMES.get(self.timeframe, ("?",""))[0]
        ml  = Config.MARKET_CATEGORIES[self.mode]["label"] if self.mode != "TUDO" else "TUDO"
        markup = {"inline_keyboard": [
            [{"text": f"Mercado: {ml}", "callback_data": "ignore"}],
            [{"text": "FOREX", "callback_data": "set_FOREX"}, {"text": "CRIPTO", "callback_data": "set_CRYPTO"}],
            [{"text": "COMM.", "callback_data": "set_COMMODITIES"}, {"text": "INDICES", "callback_data": "set_INDICES"}],
            [{"text": "TUDO", "callback_data": "set_TUDO"}],
            [{"text": f"TF: {self.timeframe} {tfl}", "callback_data": "tf_menu"}],
            [{"text": "Status", "callback_data": "status"}, {"text": "Placar", "callback_data": "placar"}],
            [{"text": "Noticias", "callback_data": "news"}],
        ]}
        tot = self.wins + self.losses; wr = (self.wins/tot*100) if tot > 0 else 0
        cb = f"\n⛔ CB – retoma em {int((self.paused_until-time.time())/60)}min" if self.is_paused() else ""
        self.send(f"<b>BOT SNIPER v7.1</b>\n{self.wins}W / {self.losses}L ({wr:.1f}%)\nModo: {ml} | TF: {self.timeframe}{cb}", markup)

    def build_tf_menu(self):
        rows = [[{"text": f"{tf} {lb}{'✅' if tf==self.timeframe else ''}", "callback_data": f"set_tf_{tf}"}]
                for tf, (lb, _) in Config.TIMEFRAMES.items()]
        rows.append([{"text": "« Voltar", "callback_data": "main_menu"}])
        self.send("Selecione o Timeframe", {"inline_keyboard": rows})

    def set_timeframe(self, tf):
        if tf not in Config.TIMEFRAMES: return
        old = self.timeframe; self.timeframe = tf; save_state(self)
        self.send(f"✅ TF: {old} → {tf}")

    def set_mode(self, mode):
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]: return
        self.mode = mode; save_state(self); self.send(f"✅ Modo: {mode}")

    def send_news(self):
        self.send(build_news_msg(), disable_preview=True); self.last_news_ts = time.time()

    def maybe_send_news(self):
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL: self.send_news()

    def send_status(self):
        lines = ["<b>OPERAÇÕES ABERTAS</b>\n"]
        if not self.active_trades: lines.append("Nenhuma."); self.send("\n".join(lines)); return
        for t in self.active_trades:
            res = get_analysis(t["symbol"], self.timeframe)
            cur = res["price"] if res else t["entry"]
            pnl = (cur-t["entry"])/t["entry"]*100
            if t["dir"] == "SELL": pnl = -pnl
            lines.append(f"{'🟢' if pnl>=0 else '🔴'} {t['symbol']} {t['dir']} P&L: {pnl:+.2f}%")
        self.send("\n".join(lines))

    def send_placar(self):
        tot = self.wins+self.losses; wr = (self.wins/tot*100) if tot>0 else 0
        self.send(f"🏆 W/L: {self.wins}/{self.losses} ({wr:.1f}%)")

    def is_paused(self): return time.time() < self.paused_until

    def reset_pause(self):
        self.paused_until = 0; self.consecutive_losses = 0
        save_state(self); self.send("✅ Circuit Breaker resetado.")

    # ── Cache de tendências ───────────────────────────────────
    def update_trends_cache(self):
        if time.time() - self.last_trends_update < Config.TRENDS_INTERVAL: return
        log("📡 Atualizando cache tendências...")
        for s in all_syms():
            try:
                res = get_analysis(s, self.timeframe)
                if res:
                    rev = detect_reversal(res)
                    self.trend_cache[s] = {
                        "data": res,
                        "reversal": {"has": rev[0], "dir": rev[1], "strength": rev[2], "reasons": rev[3]},
                        "ts": time.time(),
                    }
            except Exception as e: log(f"[TRENDS] {s}: {e}")
        self.last_trends_update = time.time()
        log(f"📡 Cache: {len(self.trend_cache)} ativos")

    # ── SCAN — 4 fases ───────────────────────────────────────
    def scan(self):
        if self.is_paused(): return
        if len(self.active_trades) >= Config.MAX_TRADES: return
        universe = all_syms() if self.mode == "TUDO" else list(Config.MARKET_CATEGORIES[self.mode]["assets"].keys())
        log(f"🔎 Scan {self.mode} ({len(universe)} ativos, TF {self.timeframe})")
        for s in universe:
            cat = asset_cat(s)
            if not mkt_open(cat): continue
            if any(t["symbol"] == s for t in self.active_trades): continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue

            res = self.trend_cache.get(s, {}).get("data") or get_analysis(s, self.timeframe)
            if not res: continue
            # Atualiza cache
            if s not in self.trend_cache:
                rev = detect_reversal(res)
                self.trend_cache[s] = {"data": res, "reversal": {"has":rev[0],"dir":rev[1],"strength":rev[2],"reasons":rev[3]}, "ts": time.time()}

            if res["cenario"] == "NEUTRO":
                # FASE 1 – Radar (só se não NEUTRO após filtro)
                continue

            price = res["price"]; atr = res["atr"]; cen = res["cenario"]
            cl = asset_cat(s); cl_lbl = Config.MARKET_CATEGORIES.get(cl, {}).get("label", cl)
            if cen == "ALTA":
                gatilho = res["t_buy"]; dir_s = "BUY"
                sl_est = gatilho - Config.ATR_MULT_SL * atr
                tp_est = gatilho + Config.ATR_MULT_TP * atr
                preco_ok = price >= gatilho and price < res["upper"] and res["rsi"] < 70
            else:
                gatilho = res["t_sell"]; dir_s = "SELL"
                sl_est = gatilho + Config.ATR_MULT_SL * atr
                tp_est = gatilho - Config.ATR_MULT_TP * atr
                preco_ok = price <= gatilho and price > res["lower"] and res["rsi"] > 30

            sl_p = abs(gatilho-sl_est)/gatilho*100
            tp_p = abs(tp_est-gatilho)/gatilho*100
            ratio = f"1:{Config.ATR_MULT_TP/Config.ATR_MULT_SL:.1f}"

            # FASE 1 — RADAR (preço ainda não chegou no gatilho)
            if not preco_ok:
                if time.time() - self.radar_list.get(s, 0) > Config.RADAR_COOLDOWN:
                    dist = abs(price-gatilho)/price*100
                    dl = "COMPRA" if dir_s=="BUY" else "VENDA"
                    self.send(
                        f"⚠️ <b>RADAR – {s}</b> ({res['name']})\n"                        f"{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
                        f"Tendência de <b>{cen}</b> detectada\n"
                        f"Aguardando gatilho de <b>{dl}</b>\n\n"
                        f"🎯 Gatilho: <code>{fmt(gatilho)}</code>\n"
                        f"📍 Atual:   <code>{fmt(price)}</code> ({dist:.2f}% de distância)\n"
                        f"🛡 SL est.: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n"
                        f"🎯 TP est.: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n"
                        f"⚖️ Ratio: <b>{ratio}</b>\n"
                        f"RSI: <code>{res['rsi']:.1f}</code> | ADX: <code>{res['adx']:.1f}</code>"
                    )
                    self.radar_list[s] = time.time()
                continue

            # FASE 2 — GATILHO ATINGIDO
            if time.time() - self.gatilho_list.get(s, 0) > Config.GATILHO_COOLDOWN:
                dl = "COMPRAR (BUY) 🟢" if dir_s=="BUY" else "VENDER (SELL) 🔴"
                self.send(
                    f"🔔 <b>GATILHO ATINGIDO – {s}</b> ({res['name']})\n"
                    f"{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
                    f"✅ Preço chegou no nível de entrada!\n\n"
                    f"▶️ <b>AÇÃO: {dl}</b>\n\n"
                    f"💰 Entrada: <code>{fmt(price)}</code>\n"
                    f"🛡 Stop Loss: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n"
                    f"🎯 Take Profit: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n"
                    f"⚖️ Ratio: <b>{ratio}</b>\n\n"
                    f"⏳ <i>Verificando confluência…</i>"
                )
                self.gatilho_list[s] = time.time()

            # FASE 3 — Confluência
            sc, tot_c, checks = calc_confluence(res, dir_s)
            bar = cbar(sc, tot_c)
            conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)

            # FASE 4A — Insuficiente
            if sc < Config.MIN_CONFLUENCE:
                log(f"[SINAL] {s} {dir_s} – {sc}/{tot_c}")
                falhou = [nm for nm, ok in checks if not ok]
                self.send(
                    f"⚡ <b>CONFLUÊNCIA INSUF. – {s}</b>\n\n"
                    f"Gatilho atingido mas bot NÃO entrou.\n"
                    f"Score: <code>{sc}/{tot_c}</code> [{bar}] (min: {Config.MIN_CONFLUENCE})\n\n"
                    f"<b>Filtros que falharam:</b>\n"
                    + "\n".join(f"   ❌ {nm}" for nm in falhou)
                ); continue

            # FASE 4B — SINAL CONFIRMADO
            if dir_s == "BUY":
                sl = price - Config.ATR_MULT_SL * atr
                tp = price + Config.ATR_MULT_TP * atr
            else:
                sl = price + Config.ATR_MULT_SL * atr
                tp = price - Config.ATR_MULT_TP * atr
            dl = "COMPRAR (BUY) 🟢" if dir_s=="BUY" else "VENDER (SELL) 🔴"
            vol_txt = f"{res['vol_ratio']:.1f}x média" if res["vol_ratio"]>0 else "N/A"
            self.send(
                f"🎯 <b>SINAL CONFIRMADO – {s}</b> ({res['name']})\n"
                f"{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
                f"╔══════════════════╗\n"
                f"  ▶️  <b>{dl}</b>\n"
                f"╚══════════════════╝\n\n"
                f"💰 <b>Entrada:</b>     <code>{fmt(price)}</code>\n"
                f"🛡 <b>Stop Loss:</b>   <code>{fmt(sl)}</code>  ({-sl_pct:.2f}%)\n"
                f"🎯 <b>Take Profit:</b> <code>{fmt(tp)}</code>  ({tp_pct:+.2f}%)\n"
                f"⚖️ <b>Ratio:</b>       <b>{ratio}</b>\n\n"
                f"ATR: <code>{fmt(atr)}</code> | ADX: <code>{res['adx']:.1f}</code> | RSI: <code>{res['rsi']:.1f}</code>\n"
                f"Volume: <code>{vol_txt}</code>\n\n"
                f"<b>Confluência: {sc}/{tot_c} [{bar}]</b>\n{conf_txt}"
            )
            self.active_trades.append({
                "symbol": s, "name": res["name"], "entry": price,
                "tp": tp, "sl": sl, "dir": dir_s, "peak": price, "atr": atr,
                "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "session_alerted": True,
            })
            self.radar_list[s] = self.gatilho_list[s] = time.time()
            save_state(self)

    # ── Scan Contra-Tendência FOREX ───────────────────────────
    def scan_reversal_forex(self):
        if self.is_paused(): return
        if not mkt_open("FOREX"): return
        if len(self.active_trades) >= Config.MAX_TRADES: return
        for s in Config.MARKET_CATEGORIES["FOREX"]["assets"].keys():
            if any(t["symbol"] == s for t in self.active_trades): continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
            if time.time() - self.reversal_list.get(s, 0) < Config.REVERSAL_COOLDOWN: continue
            res = get_reversal_analysis(s, self.timeframe)
            if not res: continue
            price = res["price"]; atr = res["atr"]
            cands = []
            for d in (["SELL"] if res["signal_sell_ct"] else []) + (["BUY"] if res["signal_buy_ct"] else []):
                sc, tc, ch = calc_reversal_conf(res, d)
                if sc >= Config.MIN_CONFLUENCE_CT:
                    sinais = []
                    if d == "SELL":
                        if res["rsi_overbought"]: sinais.append(f"RSI {res['rsi']:.0f} sobrecomprado")
                        if res["near_upper"]:     sinais.append("BB Superior atingida")
                        if res["div_bear"]:       sinais.append("RSI divergência bearish")
                        if res["macd_div_bear"]:  sinais.append("MACD divergência bearish")
                        if res["wick_bear"]:      sinais.append("Wick de rejeição")
                        if res["pat_bear"] and res["pat_name"]: sinais.append(res["pat_name"])
                    else:
                        if res["rsi_oversold"]:   sinais.append(f"RSI {res['rsi']:.0f} sobrevendido")
                        if res["near_lower"]:     sinais.append("BB Inferior atingida")
                        if res["div_bull"]:       sinais.append("RSI divergência bullish")
                        if res["macd_div_bull"]:  sinais.append("MACD divergência bullish")
                        if res["wick_bull"]:      sinais.append("Wick de rejeição")
                        if res["pat_bull"] and res["pat_name"]: sinais.append(res["pat_name"])
                    cands.append((sc, tc, ch, d, sinais))
            if not cands: continue
            cands.sort(key=lambda x: x[0], reverse=True)
            sc, tc, ch, dir_s, sinais = cands[0]
            bar = cbar(sc, tc)
            conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in ch)
            sl_m = Config.ATR_MULT_SL; tp_m = Config.ATR_MULT_SL * 1.5
            if dir_s == "BUY":
                sl = price - sl_m*atr; tp = price + tp_m*atr
            else:
                sl = price + sl_m*atr; tp = price - tp_m*atr
            sl_p = abs(price-sl)/price*100; tp_p = abs(tp-price)/price*100
            ratio = f"1:{tp_m/sl_m:.1f}"
            dl = "COMPRAR (BUY) 🟢" if dir_s=="BUY" else "VENDER (SELL) 🔴"
            sinais_txt = "\n".join(f"   ⚡ {sg}" for sg in sinais)
            self.send(
                f"⚡ <b>CONTRA-TENDÊNCIA FOREX – {s}</b> ({res['name']})\n"
                f"📈 FOREX | TF: <code>{self.timeframe}</code>\n\n"
                f"🔄 <i>Sinal de reversão — CONTRA a tendência</i>\n\n"
                f"╔══════════════════╗\n"
                f"  ▶️  <b>{dl}</b>\n"
                f"╚══════════════════╝\n\n"
                f"💰 <b>Entrada:</b>     <code>{fmt(price)}</code>\n"
                f"🛡 <b>Stop Loss:</b>   <code>{fmt(sl)}</code>  ({-sl_p:.2f}%)\n"
                f"🎯 <b>Take Profit:</b> <code>{fmt(tp)}</code>  ({tp_p:+.2f}%)\n"
                f"⚖️ <b>Ratio:</b>       <b>{ratio}</b>\n\n"
                f"<b>Sinais de exaustão:</b>\n{sinais_txt}\n\n"
                f"ADX: <code>{res['adx']:.1f}</code> | RSI: <code>{res['rsi']:.1f}</code>\n\n"
                f"<b>Confluência: {sc}/{tc} [{bar}]</b>\n{conf_txt}\n\n"
                f"⚠️ <i>Use gestão de risco reduzida.</i>"
            )
            self.reversal_list[s] = time.time()
            self.active_trades.append({
                "symbol": s, "name": res["name"], "entry": price,
                "tp": tp, "sl": sl, "dir": dir_s, "peak": price, "atr": atr,
                "tipo": "CONTRA-TENDÊNCIA ⚡",
                "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "session_alerted": True,
            })
            save_state(self)
    # ── Monitor + Trailing Stop ───────────────────────────────
    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res: continue
            cur = res["price"]; atr = res["atr"]

            # Reanunciar trade restaurado
            if not t.get("session_alerted", True):
                dl = "BUY 🟢" if t["dir"]=="BUY" else "SELL 🔴"
                sl_p = abs(t["entry"]-t["sl"])/t["entry"]*100
                tp_p = abs(t["tp"]-t["entry"])/t["entry"]*100
                self.send(
                    f"📌 <b>TRADE RESTAURADO – {t['symbol']}</b>\n"
                    f"Ação: <b>{dl}</b> | Aberto: {t.get('opened_at','?')}\n"
                    f"Entrada: <code>{fmt(t['entry'])}</code> | Atual: <code>{fmt(cur)}</code>\n"
                    f"🎯 TP: <code>{fmt(t['tp'])}</code> ({tp_p:+.2f}%)\n"
                    f"🛡 SL: <code>{fmt(t['sl'])}</code> ({-sl_p:.2f}%)"
                )
                t["session_alerted"] = True; changed = True

            # Trailing Stop
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur; nsl = cur - Config.ATR_MULT_TRAIL*atr
                if nsl > t["sl"]: t["sl"] = nsl; changed = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur; nsl = cur + Config.ATR_MULT_TRAIL*atr
                if nsl < t["sl"]: t["sl"] = nsl; changed = True

            is_win  = (t["dir"]=="BUY" and cur>=t["tp"]) or (t["dir"]=="SELL" and cur<=t["tp"])
            is_loss = (t["dir"]=="BUY" and cur<=t["sl"]) or (t["dir"]=="SELL" and cur>=t["sl"])
            if is_win or is_loss:
                pnl = (cur-t["entry"])/t["entry"]*100
                if t["dir"] == "SELL": pnl = -pnl
                st = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                closed_at = datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")
                if is_win:  self.wins += 1; self.consecutive_losses = 0
                else:       self.losses += 1; self.consecutive_losses += 1; self.asset_cooldown[t["symbol"]] = time.time()
                self.history.append({"symbol": t["symbol"], "dir": t["dir"], "result": "WIN" if is_win else "LOSS", "pnl": round(pnl,2), "closed_at": closed_at})
                self.send(
                    f"🏁 <b>OPERAÇÃO ENCERRADA</b>\n"
                    f"Ativo: <b>{t['symbol']}</b> ({t.get('name','')}) | {t['dir']}\n"
                    f"Resultado: <b>{st}</b>\n\n"
                    f"💰 Entrada: <code>{fmt(t['entry'])}</code>\n"
                    f"🔚 Saída:   <code>{fmt(cur)}</code>\n"
                    f"P&amp;L:   <code>{pnl:+.2f}%</code>"
                )
                self.active_trades.remove(t); changed = True
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    mins = Config.PAUSE_DURATION // 60
                    self.send(f"⛔ <b>CIRCUIT BREAKER ATIVADO</b>\n\n{self.consecutive_losses} losses consecutivos.\nPausado por <b>{mins} minutos</b>.\n\nUse /resetpausa para retomar.")
        if changed: save_state(self)


# ═══════════════════════════════════════════════════════════════
# SERVICE WORKER JS (OTIMIZADO)
# ═══════════════════════════════════════════════════════════════
SW_JS = """
const CACHE_NAME = 'sniper-v7.2';
const STATIC_ASSETS = ['/', '/sw.js', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', e => { e.waitUntil(clients.claim()); });

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Estratégia: Cache First para estáticos, Network First para API
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(e.request, clone));
        return res;
      }).catch(() => caches.match(e.request))
    );
  } else {
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});

self.addEventListener('push', e => {
  let data = { title: 'Sniper Bot', body: 'Novo sinal!', icon: '/icon-192.png' };
  try { data = JSON.parse(e.data.text()); } catch (_) {}

  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon || '/icon-192.png',
      badge: '/icon-192.png',
      vibrate: [200, 100, 200],
      data: { url: '/' }
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({type:'window'}).then(cs => {
    if (cs.length) cs[0].focus();
    else clients.openWindow('/');  }));
});
"""

# ═══════════════════════════════════════════════════════════════
# DASHBOARD HTML — VERSÃO OTIMIZADA v7.2 (COM MELHORIAS DE EXECUÇÃO)
# ═══════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<meta name="mobile-web-app-capable" content="yes"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
<meta name="theme-color" content="#06090f"/>
<title>Sniper Bot</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
/* ═══════════════════════════════════════════════════════════ */
/* DESIGN SYSTEM — Variáveis CSS para consistência visual */
/* ═══════════════════════════════════════════════════════════ */
:root {
  /* Cores base */
  --bg: #06090f; --bg2: #0b1018; --bg3: #111827; --bg4: #192032;
  --border: #1e2d45; --border-soft: #2a3a52;
  --text: #e6f1ff; --text-muted: #6b84a3; --text-dim: #4a607d;
  
  /* Cores de estado */
  --green: #00e676; --green-soft: rgba(0,230,118,0.12); --green-border: rgba(0,230,118,0.3);
  --red: #ff5252; --red-soft: rgba(255,82,82,0.12); --red-border: rgba(255,82,82,0.3);
  --gold: #ffc107; --gold-soft: rgba(255,193,7,0.12); --gold-border: rgba(255,193,7,0.3);
  --blue: #4da6ff; --blue-soft: rgba(77,166,255,0.12); --blue-border: rgba(77,166,255,0.3);
  --cyan: #00d4ff; --cyan-soft: rgba(0,212,255,0.12);
  --orange: #ff9800; --purple: #ab47bc;
  
  /* Tipografia */
  --font-mono: 'JetBrains Mono', monospace;
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  
  /* Espaçamento e bordas */
  --radius: 14px; --radius-sm: 8px; --radius-lg: 20px;
  --nav-h: 64px; --header-h: 60px; --safe-bottom: env(safe-area-inset-bottom, 0);
  
  /* Animações */
  --transition: 180ms cubic-bezier(0.4, 0, 0.2, 1);
  --transition-slow: 320ms cubic-bezier(0.4, 0, 0.2, 1);
}
/* Reset e base */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html, body { height: 100%; overflow: hidden; background: var(--bg); color: var(--text); font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
body::after { content: ''; position: fixed; inset: 0; pointer-events: none; z-index: 0; background: radial-gradient(ellipse at top, rgba(77,166,255,0.03), transparent 60%); }

/* ═══════════════════════════════════════════════════════════ */
/* LAYOUT PRINCIPAL */
/* ═══════════════════════════════════════════════════════════ */
#app { display: flex; flex-direction: column; height: 100%; max-width: 520px; margin: 0 auto; position: relative; z-index: 1; }

/* Header */
#hdr { height: var(--header-h); flex-shrink: 0; background: linear-gradient(135deg, var(--bg2), #0a0f18); border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; padding: 0 16px; position: relative; z-index: 100; }
.hdr-left { display: flex; align-items: center; gap: 12px; }
.logo { width: 38px; height: 38px; border-radius: 10px; background: linear-gradient(135deg, var(--green), var(--cyan)); display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 18px; font-weight: 700; color: #000; box-shadow: 0 0 24px rgba(0,230,118,0.25); }
.app-title { display: flex; flex-direction: column; }
.app-title .main { font-size: 16px; font-weight: 700; letter-spacing: -0.02em; }
.app-title .sub { font-size: 9px; color: var(--text-muted); letter-spacing: 1.2px; text-transform: uppercase; margin-top: 2px; }
.hdr-right { display: flex; align-items: center; gap: 8px; }
.status-pill { display: flex; align-items: center; gap: 6px; background: var(--bg3); border: 1px solid var(--border); border-radius: 20px; padding: 5px 12px; font-size: 10px; color: var(--text-muted); letter-spacing: 0.5px; text-transform: uppercase; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(0.9); } }
.icon-btn { width: 36px; height: 36px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg3); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 16px; transition: var(--transition); color: var(--text-muted); }
.icon-btn:hover, .icon-btn:active { background: var(--border); color: var(--text); transform: scale(0.96); }
.icon-btn.refreshing { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Páginas — CORREÇÃO NAVEGAÇÃO: !important para garantir prioridade */
#pages { flex: 1; overflow: hidden; position: relative; }
.page { position: absolute; inset: 0; display: none !important; overflow-y: auto; padding: 14px 14px calc(var(--nav-h) + var(--safe-bottom) + 12px); scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
.page::-webkit-scrollbar { width: 3px; }
.page::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
.page.active { display: block !important; }

/* Navigation */
#nav { position: fixed; bottom: 0; left: 50%; transform: translateX(-50%); width: 100%; max-width: 520px; height: var(--nav-h); background: var(--bg2); border-top: 1px solid var(--border); display: flex; z-index: 200; padding-bottom: var(--safe-bottom); }
.nav-btn { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; border: none; background: none; cursor: pointer; font-size: 10px; color: var(--text-muted); letter-spacing: 0.3px; text-transform: uppercase; padding: 0; transition: var(--transition); position: relative; }
.nav-btn .icon { font-size: 19px; transition: var(--transition); }
.nav-btn.active { color: var(--green); }
.nav-btn.active .icon { transform: scale(1.1); }
.nav-btn:active { opacity: 0.7; }
.nav-badge { position: absolute; top: 8px; right: calc(50% - 18px); min-width: 16px; height: 16px; border-radius: 8px; background: var(--red); color: #fff; font-size: 9px; font-family: var(--font-mono); font-weight: 700; display: none; align-items: center; justify-content: center; padding: 0 4px; }

/* ═══════════════════════════════════════════════════════════ */
/* COMPONENTES UI */
/* ═══════════════════════════════════════════════════════════ */
.card { background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px; margin-bottom: 10px; transition: var(--transition); }
.card:hover { border-color: var(--border-soft); }
.card-header { font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }

/* Stats Grid */.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px; }
.stat-box { background: var(--bg3); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px 10px; text-align: center; transition: var(--transition); }
.stat-box:hover { transform: translateY(-2px); border-color: var(--border-soft); }
.stat-label { font-size: 8px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 4px; }
.stat-value { font-size: 20px; font-weight: 700; font-family: var(--font-mono); line-height: 1; margin-bottom: 2px; }
.stat-value.green { color: var(--green); }
.stat-value.red { color: var(--red); }
.stat-value.cyan { color: var(--cyan); }
.stat-value.gold { color: var(--gold); }
.stat-sub { font-size: 9px; color: var(--text-dim); }

/* Trade Card */
.trade-card { border-radius: var(--radius); padding: 14px; margin-bottom: 10px; border-left: 4px solid var(--border); background: var(--bg2); transition: var(--transition); }
.trade-card:hover { transform: translateX(2px); }
.trade-card.buy { border-left-color: var(--green); }
.trade-card.sell { border-left-color: var(--red); }
.trade-card.ct { border-left-color: var(--gold); background: var(--gold-soft); }
.trade-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 10px; }
.trade-symbol { font-size: 16px; font-weight: 700; font-family: var(--font-mono); display: flex; align-items: center; gap: 6px; }
.trade-symbol .ct-badge { font-size: 9px; background: var(--gold); color: #000; padding: 2px 6px; border-radius: 4px; font-weight: 600; }
.trade-name { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
.trade-badge { font-size: 10px; font-weight: 700; font-family: var(--font-mono); padding: 5px 10px; border-radius: 20px; }
.trade-badge.buy { background: var(--green-soft); color: var(--green); border: 1px solid var(--green-border); }
.trade-badge.sell { background: var(--red-soft); color: var(--red); border: 1px solid var(--red-border); }
.trade-levels { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin-bottom: 10px; }
.level-box { background: var(--bg3); border-radius: var(--radius-sm); padding: 8px 6px; text-align: center; }
.level-label { font-size: 8px; letter-spacing: 0.8px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 3px; }
.level-value { font-size: 11px; font-family: var(--font-mono); font-weight: 600; }
.level-value.sl { color: var(--red); }
.level-value.tp { color: var(--green); }
.trade-footer { display: flex; align-items: center; justify-content: space-between; }
.trade-pnl { font-size: 15px; font-weight: 700; font-family: var(--font-mono); }
.trade-pnl.pos { color: var(--green); }
.trade-pnl.neg { color: var(--red); }
.trade-current { font-size: 10px; color: var(--text-muted); }
.progress-bar { height: 3px; background: var(--bg4); border-radius: 2px; margin-top: 8px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 2px; transition: width 0.4s ease; }
.progress-fill.pos { background: linear-gradient(90deg, var(--green), #00c853); }
.progress-fill.neg { background: linear-gradient(90deg, var(--red), #d50000); }

/* Sparkline CSS-only */
.sparkline { height: 24px; display: flex; align-items: flex-end; gap: 1px; margin: 4px 0; }
.spark-bar { flex: 1; background: var(--border); border-radius: 1px; min-width: 2px; transition: height 0.3s ease; }
.spark-bar.up { background: var(--green); }
.spark-bar.down { background: var(--red); }

/* Signal Item */
.signal-item { display: flex; gap: 10px; padding: 12px 0; border-bottom: 1px solid var(--border); animation: fadeIn 0.2s ease; }
.signal-item:last-child { border-bottom: none; }
.signal-item.new { animation: pulseNew 0.6s ease; }@keyframes pulseNew { 0% { background: transparent; } 50% { background: var(--blue-soft); } 100% { background: transparent; } }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
.signal-icon { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.signal-icon.radar { background: var(--blue-soft); color: var(--blue); }
.signal-icon.gatilho { background: var(--cyan-soft); color: var(--cyan); }
.signal-icon.sinal { background: var(--green-soft); color: var(--green); }
.signal-icon.ct { background: var(--gold-soft); color: var(--gold); }
.signal-icon.insuf { background: var(--bg4); color: var(--text-dim); }
.signal-icon.close { background: var(--bg4); color: var(--text-muted); }
.signal-icon.cb { background: var(--red-soft); color: var(--red); }
.signal-body { flex: 1; min-width: 0; }
.signal-type { font-size: 9px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; margin-bottom: 3px; }
.signal-type.radar { color: var(--blue); }
.signal-type.gatilho { color: var(--cyan); }
.signal-type.sinal { color: var(--green); }
.signal-type.ct { color: var(--gold); }
.signal-type.insuf { color: var(--text-dim); }
.signal-type.close { color: var(--text-muted); }
.signal-type.cb { color: var(--red); }
.signal-text { font-size: 11px; color: var(--text-muted); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.signal-time { font-size: 9px; color: var(--text-dim); margin-top: 4px; font-family: var(--font-mono); }

/* Asset Row (Scanner) */
.asset-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border); transition: var(--transition); }
.asset-row:hover { background: var(--bg3); margin: 0 -14px; padding: 10px 14px; border-radius: var(--radius-sm); }
.asset-icon { width: 38px; height: 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 16px; font-weight: 700; font-family: var(--font-mono); flex-shrink: 0; }
.asset-icon.up { background: var(--green-soft); color: var(--green); }
.asset-icon.down { background: var(--red-soft); color: var(--red); }
.asset-icon.neutral { background: var(--bg4); color: var(--text-muted); }
.asset-info { flex: 1; min-width: 0; }
.asset-symbol { font-size: 13px; font-weight: 600; font-family: var(--font-mono); display: flex; align-items: center; gap: 5px; }
.asset-name { font-size: 9px; color: var(--text-muted); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.asset-meta { display: flex; align-items: center; gap: 4px; margin-top: 3px; flex-wrap: wrap; }
.asset-tag { font-size: 8px; font-family: var(--font-mono); padding: 2px 6px; border-radius: 4px; }
.asset-tag.green { background: var(--green-soft); color: var(--green); }
.asset-tag.red { background: var(--red-soft); color: var(--red); }
.asset-tag.gray { background: var(--bg4); color: var(--text-muted); }
.asset-price { text-align: right; flex-shrink: 0; }
.asset-price-value { font-size: 12px; font-family: var(--font-mono); font-weight: 600; }
.asset-price-change { font-size: 10px; margin-top: 2px; }
.asset-price-change.pos { color: var(--green); }
.asset-price-change.neg { color: var(--red); }
.asset-indicators { display: flex; gap: 3px; margin-top: 4px; }
.indicator-dot { width: 6px; height: 6px; border-radius: 50%; }
.indicator-dot.rsi-ok { background: var(--green); }
.indicator-dot.rsi-warn { background: var(--gold); }
.indicator-dot.rsi-bad { background: var(--red); }
.indicator-dot.adx-strong { background: var(--green); }
.indicator-dot.adx-weak { background: var(--text-dim); }
/* Chips/Filters */
.chip-group { display: flex; gap: 6px; margin-bottom: 12px; overflow-x: auto; padding-bottom: 4px; scrollbar-width: none; }
.chip-group::-webkit-scrollbar { display: none; }
.chip { flex-shrink: 0; padding: 6px 14px; border-radius: 20px; border: 1px solid var(--border); background: var(--bg3); font-size: 11px; cursor: pointer; transition: var(--transition); color: var(--text-muted); white-space: nowrap; }
.chip:hover { background: var(--border); }
.chip.active { background: var(--green-soft); border-color: var(--green-border); color: var(--green); font-weight: 500; }
.chip:active { transform: scale(0.97); }

/* Search Box */
.search-box { display: flex; align-items: center; gap: 8px; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 12px; }
.search-box input { flex: 1; background: none; border: none; color: var(--text); font-size: 13px; outline: none; }
.search-box input::placeholder { color: var(--text-dim); }
.search-icon { color: var(--text-muted); font-size: 14px; }

/* Section Header */
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.section-title { font-size: 11px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--text-muted); display: flex; align-items: center; gap: 6px; }
.refresh-btn { font-size: 10px; color: var(--text-muted); cursor: pointer; padding: 3px 8px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg3); transition: var(--transition); }
.refresh-btn:hover { background: var(--border); color: var(--text); }

/* Fear & Greed Card */
.fg-card { background: linear-gradient(135deg, var(--bg3), var(--bg4)); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; }
.fg-label { font-size: 9px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 4px; }
.fg-value { font-size: 17px; font-weight: 700; }
.fg-score { font-size: 32px; font-weight: 700; font-family: var(--font-mono); opacity: 0.15; }

/* Config Section */
.config-section { margin-bottom: 18px; }
.config-label { font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-muted); margin-bottom: 10px; }
.mode-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 7px; }
.mode-btn { background: var(--bg3); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px 8px; cursor: pointer; font-size: 12px; color: var(--text); text-align: center; transition: var(--transition); line-height: 1.4; border: none; display: flex; flex-direction: column; align-items: center; gap: 4px; }
.mode-btn:active { transform: scale(0.98); }
.mode-btn.active { background: var(--green-soft); border: 1px solid var(--green-border); color: var(--green); }
.mode-icon { font-size: 18px; }
.tf-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.tf-btn { background: var(--bg3); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 6px; cursor: pointer; font-size: 11px; font-family: var(--font-mono); color: var(--text); text-align: center; transition: var(--transition); border: none; }
.tf-btn:active { transform: scale(0.97); }
.tf-btn.active { background: rgba(0,212,255,0.1); border: 1px solid var(--cyan); color: var(--cyan); }
.tf-value { font-size: 13px; font-weight: 600; display: block; margin-bottom: 2px; }
.tf-label { font-size: 8px; color: var(--text-dim); }

/* Action Buttons */
.action-btn { width: 100%; padding: 14px; border-radius: var(--radius); border: none; cursor: pointer; font-size: 13px; font-weight: 600; margin-bottom: 8px; transition: var(--transition); letter-spacing: 0.3px; display: flex; align-items: center; justify-content: center; gap: 6px; }
.action-btn:active { transform: scale(0.98); }
.action-btn.danger { background: var(--red-soft); color: var(--red); border: 1px solid var(--red-border); }
.action-btn.success { background: var(--green-soft); color: var(--green); border: 1px solid var(--green-border); }
.action-btn.primary { background: var(--blue-soft); color: var(--blue); border: 1px solid var(--blue-border); }

/* Empty State */
.empty-state { text-align: center; padding: 40px 20px; color: var(--text-muted); }.empty-icon { font-size: 42px; margin-bottom: 12px; display: block; opacity: 0.6; }
.empty-text { font-size: 12px; line-height: 1.6; }

/* Circuit Breaker Banner */
.cb-banner { background: var(--red-soft); border: 1px solid var(--red-border); border-radius: var(--radius-sm); padding: 12px 14px; margin-bottom: 12px; display: none; align-items: center; justify-content: space-between; }
.cb-text { font-size: 11px; color: var(--red); font-weight: 600; }
.cb-timer { font-size: 18px; font-family: var(--font-mono); font-weight: 700; color: var(--red); }

/* Error Banner */
.error-banner { background: var(--red-soft); border: 1px solid var(--red-border); border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 12px; font-size: 11px; color: var(--red); display: none; }

/* Timestamp */
.timestamp { font-size: 9px; color: var(--text-dim); text-align: center; padding: 8px 0; letter-spacing: 0.5px; font-family: var(--font-mono); }

/* Divider */
.divider { height: 1px; background: var(--border); margin: 14px 0; }

/* Highlight for search */
.highlight { background: rgba(255,193,7,0.2); padding: 0 2px; border-radius: 2px; }

/* Virtual scroll container */
.virtual-container { position: relative; }
.virtual-content { position: absolute; top: 0; left: 0; right: 0; }

/* Loading skeleton */
.skeleton { background: linear-gradient(90deg, var(--bg3) 25%, var(--bg4) 50%, var(--bg3) 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 4px; }
@keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
.skeleton-row { height: 48px; margin-bottom: 8px; border-radius: var(--radius-sm); }
.skeleton-card { height: 120px; margin-bottom: 10px; border-radius: var(--radius); }

/* Toggle Switch */
.toggle { display: flex; align-items: center; gap: 10px; padding: 10px 0; }
.toggle-label { font-size: 12px; color: var(--text); flex: 1; }
.toggle-switch { position: relative; width: 44px; height: 24px; }
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background: var(--bg4); border: 1px solid var(--border); border-radius: 24px; transition: var(--transition); }
.toggle-slider:before { position: absolute; content: ""; height: 18px; width: 18px; left: 3px; bottom: 2px; background: var(--text-muted); border-radius: 50%; transition: var(--transition); }
input:checked + .toggle-slider { background: var(--green-soft); border-color: var(--green-border); }
input:checked + .toggle-slider:before { transform: translateX(20px); background: var(--green); }

/* Sub-tab navigation */
.sub-tabs { display: flex; gap: 0; margin-bottom: 14px; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.sub-tab { flex: 1; padding: 10px; border: none; background: none; color: var(--text-muted); font-size: 12px; font-weight: 600; cursor: pointer; transition: var(--transition); font-family: var(--font-sans); }
.sub-tab.active { color: var(--green); background: var(--green-soft); }
.sub-tab:active { opacity: 0.8; }

/* Market status */
.market-item { display: flex; align-items: center; justify-content: space-between; background: var(--bg3); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 14px; margin-bottom: 7px; }
.market-name { font-size: 12px; font-weight: 500; display: flex; align-items: center; gap: 8px; }
.market-status { font-size: 9px; letter-spacing: 0.8px; text-transform: uppercase; padding: 3px 10px; border-radius: 20px; font-family: var(--font-mono); font-weight: 600; }.market-status.open { background: var(--green-soft); color: var(--green); }
.market-status.closed { background: var(--red-soft); color: var(--red); }

/* Confluence bar */
.confluence-bar { display: flex; align-items: center; gap: 6px; margin: 6px 0; }
.confluence-label { font-size: 9px; color: var(--text-muted); min-width: 80px; }
.confluence-track { flex: 1; height: 6px; background: var(--bg4); border-radius: 3px; overflow: hidden; }
.confluence-fill { height: 100%; border-radius: 3px; transition: width 0.3s ease; background: linear-gradient(90deg, var(--gold), var(--green)); }
.confluence-value { font-size: 10px; font-family: var(--font-mono); font-weight: 600; min-width: 32px; text-align: right; }

/* Price movement indicator */
.price-movement { display: inline-flex; align-items: center; gap: 3px; font-size: 10px; font-family: var(--font-mono); font-weight: 600; }
.price-movement.up { color: var(--green); }
.price-movement.down { color: var(--red); }
.price-arrow { font-size: 8px; }

/* New signal pulse animation */
@keyframes newSignal { 0% { box-shadow: 0 0 0 0 rgba(77,166,255,0.4); } 70% { box-shadow: 0 0 0 8px rgba(77,166,255,0); } 100% { box-shadow: 0 0 0 0 rgba(77,166,255,0); } }
.signal-item.new-signal { animation: newSignal 0.8s ease-out; }

/* ═══════════════════════════════════════════════════════════ */
/* NOVAS CLASSES PARA MELHORIAS DE EXECUÇÃO */
/* ═══════════════════════════════════════════════════════════ */
.copy-btn { cursor: pointer; opacity: 0.7; transition: 0.2s; font-size: 14px; margin-left: 4px; }
.copy-btn:hover { opacity: 1; transform: scale(1.1); }
.copy-btn.copied { color: var(--green); opacity: 1; }

.calc-panel { background: var(--bg3); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; margin-bottom: 12px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.calc-input { background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 6px 8px; border-radius: 6px; width: 100%; font-family: var(--font-mono); font-size: 12px; }
.calc-result { grid-column: span 2; background: var(--green-soft); border: 1px solid var(--green-border); padding: 8px; border-radius: 6px; text-align: center; font-weight: 700; color: var(--green); font-family: var(--font-mono); }

.exec-badge { font-size: 9px; background: var(--cyan-soft); color: var(--cyan); padding: 2px 6px; border-radius: 4px; display: inline-flex; align-items: center; gap: 4px; }
.exec-timer { font-family: var(--font-mono); font-size: 10px; font-weight: 600; }
.asset-stat { font-size: 9px; color: var(--text-dim); background: var(--bg4); padding: 2px 6px; border-radius: 4px; }

.toast { position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%); background: var(--bg3); border: 1px solid var(--green-border); color: var(--green); padding: 8px 16px; border-radius: 20px; font-size: 12px; font-weight: 500; opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 999; white-space: nowrap; }
.toast.show { opacity: 1; }

.exec-overlay { position: absolute; inset: 0; background: rgba(6,9,15,0.85); display: flex; align-items: center; justify-content: center; border-radius: var(--radius); z-index: 5; backdrop-filter: blur(3px); }
.exec-overlay span { background: var(--green-soft); color: var(--green); padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; border: 1px solid var(--green-border); }

.exec-done-btn { margin-top: 6px; width: 100%; padding: 6px; border: 1px dashed var(--border); background: var(--bg4); color: var(--text-muted); border-radius: 6px; font-size: 10px; cursor: pointer; transition: 0.2s; }
.exec-done-btn:hover { background: var(--border); color: var(--text); }

/* === MELHORIA 1: Card de sinal com copiar dados === */
.signal-item { position: relative; }
.signal-card-data { background: var(--bg3); border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-top: 8px; font-family: var(--font-mono); font-size: 11px; line-height: 1.8; }
.signal-card-data .card-row { display: flex; justify-content: space-between; align-items: center; padding: 2px 0; }
.signal-card-data .card-row .label { color: var(--text-dim); font-size: 10px; }
.signal-card-data .card-row .value { color: var(--text); font-weight: 600; }
.signal-copy-btn { margin-top: 8px; width: 100%; padding: 8px; border: 1px solid var(--cyan-border); background: var(--cyan-soft); color: var(--cyan); border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer; transition: 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px; }
.signal-copy-btn:hover { background: var(--cyan); color: var(--bg); }
.signal-copy-btn.copied { background: var(--green-soft); color: var(--green); border-color: var(--green-border); }

/* === MELHORIA 2: Timer de expiracao melhorado === */
.timer-container { margin-top: 6px; }
.timer-bar-bg { width: 100%; height: 4px; background: var(--bg4); border-radius: 2px; overflow: hidden; margin-top: 4px; }
.timer-bar { height: 100%; border-radius: 2px; transition: width 1s linear, background 2s ease; }
.timer-bar.green { background: var(--green); }
.timer-bar.yellow { background: var(--gold); }
.timer-bar.red { background: var(--red); }
.timer-text { font-family: var(--font-mono); font-size: 11px; font-weight: 700; display: flex; align-items: center; gap: 4px; }
.timer-text.green { color: var(--green); }
.timer-text.yellow { color: var(--gold); }
.timer-text.red { color: var(--red); }
.signal-item.expired { opacity: 0.45; filter: grayscale(0.3); }
.expired-badge { background: var(--red-soft); color: var(--red); border: 1px solid var(--red-border); padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; gap: 4px; margin-top: 6px; }

/* === MELHORIA 3: Modo Apenas Sinais === */
.signals-only-mode #hdr,
.signals-only-mode #nav,
.signals-only-mode .calc-panel,
.signals-only-mode .chip-group,
.signals-only-mode .section-header { display: none !important; }
.signals-only-mode #pages { padding: 0; margin: 0; }
.signals-only-mode #page-sig { padding: 10px; }
.signals-only-mode .page:not(#page-sig) { display: none !important; }
.signals-only-mode #page-sig { display: block !important; }
.signals-only-mode .signal-item { padding: 16px 12px; }
.signals-only-mode .signal-text { font-size: 13px; -webkit-line-clamp: 10; }
.signals-only-mode .signal-icon { width: 44px; height: 44px; font-size: 20px; }
.signals-only-mode .signal-card-data { font-size: 13px; padding: 14px; }
.signals-only-toggle { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-muted); cursor: pointer; }
.signals-only-toggle input { accent-color: var(--cyan); }
#exitSignalsOnly { position: fixed; bottom: 24px; right: 24px; z-index: 1000; background: var(--cyan); color: var(--bg); border: none; border-radius: 50%; width: 56px; height: 56px; font-size: 24px; cursor: pointer; box-shadow: 0 4px 20px rgba(0,212,255,0.4); display: none; align-items: center; justify-content: center; transition: 0.2s; }
#exitSignalsOnly:hover { transform: scale(1.1); }
.signals-only-mode #exitSignalsOnly { display: flex !important; }

/* === MELHORIA 4: Fila de pendentes com swipe === */
.pending-counter { display: flex; align-items: center; gap: 6px; background: var(--cyan-soft); border: 1px solid var(--cyan-border); color: var(--cyan); padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 600; margin-bottom: 10px; }
.pending-counter .count { background: var(--cyan); color: var(--bg); border-radius: 50%; width: 22px; height: 22px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.signal-item.swiping { transition: transform 0.05s ease; }
.signal-item.swipe-dismiss { transition: transform 0.3s ease, opacity 0.3s ease; transform: translateX(200%); opacity: 0; }
.signal-item.swipe-dismiss-left { transition: transform 0.3s ease, opacity 0.3s ease; transform: translateX(-200%); opacity: 0; }
.swipe-hint { position: absolute; top: 50%; transform: translateY(-50%); font-size: 10px; font-weight: 700; padding: 4px 8px; border-radius: 4px; pointer-events: none; opacity: 0; transition: opacity 0.15s; z-index: 2; }
.swipe-hint-right { right: 8px; background: var(--green-soft); color: var(--green); border: 1px solid var(--green-border); }
.swipe-hint-left { left: 8px; background: var(--red-soft); color: var(--red); border: 1px solid var(--red-border); }
.signal-item.swiping .swipe-hint { opacity: 1; }
</style>
</head>
<body>
<div id="app">
<!-- Header -->
<div id="hdr">
  <div class="hdr-left">    <div class="logo">S</div>
    <div class="app-title">
      <span class="main">Sniper Bot</span>
      <span class="sub">Multi-Mercado v7.2</span>
    </div>
  </div>
  <div class="hdr-right">
    <div class="status-pill"><div class="status-dot"></div>LIVE</div>
    <button class="icon-btn" id="refreshBtn" onclick="refreshAll()" title="Atualizar">↻</button>
  </div>
</div>

<!-- Pages Container -->
<div id="pages">

<!-- ═══ DASHBOARD ═══ -->
<div class="page active" id="page-dash">
  <div class="error-banner" id="errorBanner">⚠ Erro de conexão. Verifique sua internet.</div>
  <div class="cb-banner" id="cbBanner">
    <span class="cb-text">⛔ CIRCUIT BREAKER ATIVO</span>
    <span class="cb-timer" id="cbTimer">--m</span>
  </div>
  
  <!-- Stats -->
  <div class="stats-grid">
    <div class="stat-box">
      <div class="stat-label">Wins</div>
      <div class="stat-value green" id="statWins">--</div>
      <div class="stat-sub" id="statWR">--% WR</div>
    </div>
    <div class="stat-box">
      <div class="stat-label">Losses</div>
      <div class="stat-value red" id="statLosses">--</div>
      <div class="stat-sub" id="statSeq">Seq: --</div>
    </div>
    <div class="stat-box">
      <div class="stat-label">Trades</div>
      <div class="stat-value cyan" id="statActive">--/3</div>
      <div class="stat-sub" id="statMode">--</div>
    </div>
  </div>
  
  <!-- Active Trades -->
  <div class="section-header">
    <span class="section-title">💼 Trades Abertos</span>
    <label class="toggle">
      <span class="toggle-label" style="font-size:10px">Mostrar fechados</span>
      <label class="toggle-switch">
        <input type="checkbox" id="toggleClosed" onchange="toggleClosedTrades()">
        <span class="toggle-slider"></span>      </label>
    </label>
  </div>
  <div id="tradesContainer">
    <div class="empty-state"><span class="empty-icon">📭</span><div class="empty-text">Nenhum trade aberto no momento</div></div>
  </div>
  
  <!-- Markets -->
  <div class="section-header" style="margin-top:16px">
    <span class="section-title">🌐 Status dos Mercados</span>
  </div>
  <div id="marketsContainer"></div>
  
  <div class="timestamp" id="lastUpdate">--:--:--</div>
</div>

<!-- ═══ SCANNER ═══ -->
<div class="page" id="page-scan">
  <div class="section-header">
    <span class="section-title">📡 Scanner em Tempo Real</span>
    <button class="refresh-btn" onclick="loadScanner()">↻ Atualizar</button>
  </div>
  
  <!-- Trend Summary -->
  <div class="card" style="padding:10px 14px;margin-bottom:12px">
    <div style="display:flex;justify-content:space-around;text-align:center">
      <div><div style="font-size:9px;color:var(--text-muted);margin-bottom:4px">🟢 Alta</div><div class="stat-value green" id="trendUp" style="font-size:18px">--</div></div>
      <div><div style="font-size:9px;color:var(--text-muted);margin-bottom:4px">🔴 Baixa</div><div class="stat-value red" id="trendDown" style="font-size:18px">--</div></div>
      <div><div style="font-size:9px;color:var(--text-muted);margin-bottom:4px">⚪ Neutro</div><div class="stat-value" id="trendNeutral" style="font-size:18px;color:var(--text-muted)">--</div></div>
    </div>
  </div>
  
  <!-- Search -->
  <div class="search-box">
    <span class="search-icon">🔍</span>
    <input type="text" id="searchInput" placeholder="Buscar ativo ou nome..." oninput="debouncedSearch()">
  </div>
  
  <!-- Filters -->
  <div class="chip-group" id="scanFilters">
    <button class="chip active" data-filter="all" onclick="setScanFilter('all',this)">Todos</button>
    <button class="chip" data-filter="up" onclick="setScanFilter('up',this)">🟢 Alta</button>
    <button class="chip" data-filter="down" onclick="setScanFilter('down',this)">🔴 Baixa</button>
    <button class="chip" data-filter="forex" onclick="setScanFilter('forex',this)">📈 Forex</button>
    <button class="chip" data-filter="crypto" onclick="setScanFilter('crypto',this)">₿ Cripto</button>
    <button class="chip" data-filter="comm" onclick="setScanFilter('comm',this)">🏅 Comm</button>
    <button class="chip" data-filter="idx" onclick="setScanFilter('idx',this)">📊 Índices</button>
  </div>
  
  <!-- Asset List with Virtual Scroll -->  <div class="card" style="padding:4px 14px">
    <div id="scannerList" class="virtual-container">
      <div class="virtual-content" id="scannerContent">
        <!-- Skeleton loading -->
        <div class="skeleton skeleton-row"></div>
        <div class="skeleton skeleton-row"></div>
        <div class="skeleton skeleton-row"></div>
      </div>
    </div>
  </div>
</div>

<!-- ═══ SINAIS ═══ -->
<div class="page" id="page-sig">
  <div class="section-header">
    <span class="section-title">🔔 Feed de Sinais</span>
    <div style="display:flex;align-items:center;gap:10px">
      <label class="signals-only-toggle"><input type="checkbox" id="signalsOnlyToggle" onchange="toggleSignalsOnly(this.checked)">Apenas Sinais</label>
      <button class="refresh-btn" onclick="loadSignals()">↻ Atualizar</button>
    </div>
  </div>
  <!-- MELHORIA 4: Contador de pendentes -->
  <div class="pending-counter" id="pendingCounter" style="display:none">
    🔔 Pendentes: <span class="count" id="pendingCount">0</span>
    <span style="font-size:10px;color:var(--text-muted);margin-left:auto">← swipe → para gerenciar</span>
  </div>
  
  <!-- NOVO: Calculadora de Risco/Lote -->
  <div class="calc-panel" id="calcPanel">
    <input type="number" class="calc-input" id="calcBal" placeholder="Saldo ($)" step="10">
    <input type="number" class="calc-input" id="calcRisk" placeholder="Risco (%)" step="0.5" value="2">
    <div class="calc-result" id="calcRes">Ajuste saldo/risco para calcular lote</div>
  </div>
  
  <!-- Signal Filters (com novo filtro "Executar Agora") -->
  <div class="chip-group" id="signalFilters">
    <button class="chip active" data-type="all" onclick="setSignalFilter('all',this)">Todos</button>
    <button class="chip" data-type="exec" onclick="setSignalFilter('exec',this)">🟢 Executar Agora</button>
    <button class="chip" data-type="sinal" onclick="setSignalFilter('sinal',this)">🎯 Sinal</button>
    <button class="chip" data-type="gatilho" onclick="setSignalFilter('gatilho',this)">🔔 Gatilho</button>
    <button class="chip" data-type="radar" onclick="setSignalFilter('radar',this)">⚠ Radar</button>
    <button class="chip" data-type="ct" onclick="setSignalFilter('ct',this)">⚡ CT</button>
    <button class="chip" data-type="close" onclick="setSignalFilter('close',this)">🏁 Fechados</button>
  </div>
  
  <!-- Signals List -->
  <div class="card" style="padding:0 14px">
    <div id="signalsList">
      <div class="empty-state"><span class="empty-icon">🔔</span><div class="empty-text">Nenhum sinal ainda.<br>Os sinais aparecerão aqui em tempo real.</div></div>
    </div>
  </div>
</div>

<!-- ═══ CT / NEWS ═══ -->
<div class="page" id="page-ct">
  <div class="sub-tabs">
    <button class="sub-tab active" id="tabCT" onclick="showSubPage('ct')">⚡ Contra-Tendência</button>
    <button class="sub-tab" id="tabNews" onclick="showSubPage('news')">📰 Notícias</button>  </div>
  
  <!-- Contra-Tendência -->
  <div id="subCT">
    <div class="section-header">
      <span class="section-title">⚡ Oportunidades CT (FOREX)</span>
      <button class="refresh-btn" onclick="loadCT()">↻</button>
    </div>
    <div class="card" style="background:var(--gold-soft);border-color:var(--gold-border);margin-bottom:12px;padding:10px 14px;font-size:11px;color:var(--gold);line-height:1.5">
      ⚠️ Sinais <b>contra tendência</b> no FOREX. Use gestão de risco reduzida e confirme com análise própria.
    </div>
    <div id="ctList">
      <div class="empty-state"><span class="empty-icon">⚡</span><div class="empty-text">Nenhuma oportunidade CT detectada no momento.</div></div>
    </div>
  </div>
  
  <!-- Notícias -->
  <div id="subNews" style="display:none">
    <div class="section-header">
      <span class="section-title">📰 Notícias do Mercado</span>
      <button class="refresh-btn" onclick="loadNews()">↻</button>
    </div>
    <div class="fg-card" id="fgCard">
      <div><div class="fg-label">Fear & Greed Index</div><div class="fg-value" id="fgValue">--</div></div>
      <div class="fg-score" id="fgScore">--</div>
    </div>
    <div class="card" style="padding:0 14px">
      <div id="newsList">
        <div class="empty-state"><span class="empty-icon">📰</span><div class="empty-text">Carregando notícias...</div></div>
      </div>
    </div>
  </div>
</div>

<!-- ═══ CONFIG ═══ -->
<div class="page" id="page-cfg">
  <!-- Market Selection -->
  <div class="config-section">
    <div class="config-label">Mercado Ativo</div>
    <div class="mode-grid">
      <button class="mode-btn" data-mode="FOREX" onclick="setMode('FOREX')"><span class="mode-icon">📈</span>FOREX</button>
      <button class="mode-btn" data-mode="CRYPTO" onclick="setMode('CRYPTO')"><span class="mode-icon">₿</span>CRIPTO</button>
      <button class="mode-btn" data-mode="COMMODITIES" onclick="setMode('COMMODITIES')"><span class="mode-icon">🏅</span>COMMODITIES</button>
      <button class="mode-btn" data-mode="INDICES" onclick="setMode('INDICES')"><span class="mode-icon">📊</span>ÍNDICES</button>
    </div>
    <button class="mode-btn" style="width:100%;margin-top:7px;padding:12px" data-mode="TUDO" onclick="setMode('TUDO')">🌍 TUDO (42 ativos)</button>
  </div>
  
  <!-- Timeframe Selection -->
  <div class="config-section">    <div class="config-label">Timeframe</div>
    <div class="tf-grid">
      <button class="tf-btn" data-tf="1m" onclick="setTimeframe('1m')"><span class="tf-value red">●</span>1m<div class="tf-label">Agressivo</div></button>
      <button class="tf-btn" data-tf="5m" onclick="setTimeframe('5m')"><span class="tf-value orange">●</span>5m<div class="tf-label">Alto</div></button>
      <button class="tf-btn" data-tf="15m" onclick="setTimeframe('15m')"><span class="tf-value gold">●</span>15m<div class="tf-label">Moderado</div></button>
      <button class="tf-btn" data-tf="30m" onclick="setTimeframe('30m')"><span class="tf-value green">●</span>30m<div class="tf-label">Conservador</div></button>
      <button class="tf-btn" data-tf="1h" onclick="setTimeframe('1h')"><span class="tf-value cyan">●</span>1h<div class="tf-label">Seguro</div></button>
      <button class="tf-btn" data-tf="4h" onclick="setTimeframe('4h')"><span class="tf-value blue">●</span>4h<div class="tf-label">Muito Seg.</div></button>
    </div>
  </div>
  
  <div class="divider"></div>
  
  <!-- Notifications -->
  <div class="config-section">
    <div class="config-label">Notificações Push</div>
    <div class="card" style="background:var(--blue-soft);border-color:var(--blue-border);margin-bottom:12px;padding:12px 14px">
      <div style="font-size:11px;font-weight:600;color:var(--blue);margin-bottom:4px">🔔 Alertas em tempo real</div>
      <div style="font-size:10px;color:var(--text-muted);line-height:1.5">Receba sinais, gatilhos e encerramentos diretamente no seu dispositivo, mesmo com o app em segundo plano.</div>
    </div>
    <button class="action-btn primary" id="notifBtn" onclick="toggleNotifications()">🔔 Ativar Notificações</button>
    <div id="notifStatus" style="font-size:10px;color:var(--text-muted);text-align:center;margin-top:6px"></div>
  </div>
  
  <!-- Actions -->
  <div class="config-section">
    <div class="config-label">Ações Rápidas</div>
    <button class="action-btn danger" onclick="resetCircuitBreaker()">⛔ Resetar Circuit Breaker</button>
    <button class="action-btn success" onclick="refreshAll()">↻ Atualizar Tudo Agora</button>
  </div>
  
  <!-- Risk Parameters -->
  <div class="config-section">
    <div class="config-label">Parâmetros de Risco</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div class="stat-box"><div class="stat-label">Stop Loss</div><div class="stat-value red" id="paramSL">--</div></div>
      <div class="stat-box"><div class="stat-label">Take Profit</div><div class="stat-value green" id="paramTP">--</div></div>
      <div class="stat-box"><div class="stat-label">Max Trades</div><div class="stat-value cyan" id="paramMax">--</div></div>
      <div class="stat-box"><div class="stat-label">Confluência</div><div class="stat-value gold" id="paramConf">--</div></div>
    </div>
  </div>
  
  <!-- PWA Install Hint -->
  <div class="card" style="background:rgba(0,212,255,0.04);border-color:rgba(0,212,255,0.15)">
    <div class="card-header" style="color:var(--cyan)">📱 Instalar como App</div>
    <div style="font-size:11px;color:var(--text-muted);line-height:1.7">
      <b style="color:var(--text)">Android Chrome:</b> ⋮ → "Adicionar à tela inicial"<br>
      <b style="color:var(--text)">iOS Safari:</b> 📤 → "Adicionar à Tela de Início"<br>
      <b style="color:var(--cyan)">Dica:</b> Ative notificações após instalar para alertas offline.
    </div>  </div>
</div>

</div>

<!-- MELHORIA 3: Botão flutuante para sair do modo Apenas Sinais -->
<button id="exitSignalsOnly" onclick="toggleSignalsOnly(false)" title="Sair do modo Apenas Sinais">✕</button>

<!-- Navigation -->
<nav id="nav">
  <button class="nav-btn active" onclick="navigate('dash',this)"><span class="icon">⬡</span>Dashboard</button>
  <button class="nav-btn" onclick="navigate('scan',this)"><span class="icon">📡</span>Scanner</button>
  <button class="nav-btn" id="navSig" onclick="navigate('sig',this)"><span class="icon">🔔</span>Sinais<span class="nav-badge" id="sigBadge">0</span></button>
  <button class="nav-btn" onclick="navigate('ct',this)"><span class="icon">⚡</span>CT/News</button>
  <button class="nav-btn" onclick="navigate('cfg',this)"><span class="icon">⚙</span>Config</button>
</nav>
</div>

<!-- NOVO: Toast para feedback de cópia -->
<div id="toast" class="toast">📋 Copiado!</div>

<script>
/* ═══════════════════════════════════════════════════════════ */
/* UTILITÁRIOS — Performance e UX */
/* ═══════════════════════════════════════════════════════════ */

// Formatador de preços inteligente
function fmtPrice(p) {
  if (p === undefined || p === null) return '--';
  if (p >= 10000) return p.toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
  if (p >= 1000) return p.toFixed(2);
  if (p >= 10) return p.toFixed(4);
  if (p >= 1) return p.toFixed(5);
  return p.toFixed(6);
}

// Debounce para evitar chamadas excessivas
function debounce(fn, delay) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn.apply(this, args), delay);
  };
}

// RequestAnimationFrame para updates suaves
function smoothUpdate(fn) {
  requestAnimationFrame(() => {
    if (document.visibilityState === 'visible') fn();
  });
}

// Highlight de texto para busca
function highlightText(text, query) {
  if (!query) return text;
  const regex = new RegExp(`(${query})`, 'gi');
  return text.replace(regex, '<span class="highlight">$1</span>');
}

// NOVO: Toast para feedback visual
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1200);
}

// NOVO: Copiar para clipboard com feedback
function copyToClipboard(text) {
  // Limpa o texto para copiar apenas números e ponto/vírgula
  const clean = String(text).replace(/[^0-9.,]/g, '').replace(',', '.');
  navigator.clipboard.writeText(clean).then(() => {
    // Vibração háptica se suportado
    if (navigator.vibrate) navigator.vibrate(50);
    showToast('📋 Valor copiado!');
    // Feedback visual no botão
    document.querySelectorAll('.copy-btn.copied').forEach(b => b.classList.remove('copied'));
    const btns = document.querySelectorAll(`.copy-btn[data-val="${clean}"]`);
    btns.forEach(b => b.classList.add('copied'));
  }).catch(() => {
    // Fallback para navegadores antigos
    const ta = document.createElement('textarea');
    ta.value = clean;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast('📋 Copiado!');
  });
}

// Cache inteligente no frontend
const FrontendCache = {
  data: {},
  ttl: 30000, // 30 segundos

  get(key) {
    const item = this.data[key];
    if (!item) return null;

    if (Date.now() - item.ts > this.ttl) {
      delete this.data[key];
      return null;
    }

    return item.value;
  },

  set(key, value) {
    this.data[key] = {
      value: value,
      ts: Date.now()
    };
  },

  clear() {
    this.data = {};
  }
};

/* ═══════════════════════════════════════════════════════════ */
/* NOVO: Calculadora de Risco/Lote (persistente) */
/* ═══════════════════════════════════════════════════════════ */
const Calc = {
  bal: parseFloat(localStorage.getItem('calc_bal') || '1000'),
  risk: parseFloat(localStorage.getItem('calc_risk') || '2'),
  execMode: false,
  executed: JSON.parse(localStorage.getItem('exec_sigs') || '[]'),
  
  update() {
    localStorage.setItem('calc_bal', this.bal);
    localStorage.setItem('calc_risk', this.risk);
    calcLot();
  },
  
  init() {
    document.getElementById('calcBal').value = this.bal || '';
    document.getElementById('calcRisk').value = this.risk || '';
    calcLot();
  }
};

function calcLot() {
  const bal = Calc.bal, risk = Calc.risk;
  if (!bal || !risk) return document.getElementById('calcRes').textContent = "Insira saldo e risco";
  const amt = (bal * risk / 100).toFixed(2);
  document.getElementById('calcRes').innerHTML = `💰 Risco: <b>$${amt}</b> | Ajuste lote na corretora conforme SL`;
}

// Listeners para calculadora
document.getElementById('calcBal')?.addEventListener('input', e => { Calc.bal = parseFloat(e.target.value) || 0; Calc.update(); });
document.getElementById('calcRisk')?.addEventListener('input', e => { Calc.risk = parseFloat(e.target.value) || 0; Calc.update(); });

/* ═══════════════════════════════════════════════════════════ */
/* API CLIENT — Comunicação com backend */
/* ═══════════════════════════════════════════════════════════ */

const API = {
  async fetch(path, options = {}) {
    try {
      const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        mode: 'same-origin',        ...options
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (err) {
      console.error(`API Error [${path}]:`, err);
      throw err;
    }
  },
  
  getStatus: () => API.fetch('/api/status'),
  getConfig: () => API.fetch('/api/config'),
  getSignals: () => API.fetch('/api/signals'),
  getTrends: () => API.fetch('/api/trends'),
  getReversals: () => API.fetch('/api/reversals'),
  getNews: () => API.fetch('/api/news'),
  
  setMode: (mode) => API.fetch('/api/mode', { method:'POST', body:JSON.stringify({mode}) }),
  setTimeframe: (tf) => API.fetch('/api/timeframe', { method:'POST', body:JSON.stringify({timeframe:tf}) }),
  resetPause: () => API.fetch('/api/resetpausa', { method:'POST' }),
  
  getVapidKey: () => API.fetch('/api/vapid-public-key'),
  subscribePush: (sub) => API.fetch('/api/subscribe', { method:'POST', body:JSON.stringify(sub) })
};

/* ═══════════════════════════════════════════════════════════ */
/* UI MANAGER — Renderização otimizada */
/* ═══════════════════════════════════════════════════════════ */

const UI = {
  // Estado da aplicação
  state: {
    currentFilter: 'all',
    signalFilter: 'all',
    showClosed: false,
    searchQuery: '',
    lastSignals: [],
    newSignalIds: new Set(),
    assetWR: {}  // NOVO: win rate por ativo
  },
  
  // Navegação entre páginas
  navigate(page, btn) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('page-' + page).classList.add('active');
    if (btn) btn.classList.add('active');
    
    // Carregar dados sob demanda
    if (page === 'scan') loadScanner();    if (page === 'sig') { loadSignals(); this.state.newSignalIds.clear(); updateBadge(); }
    if (page === 'ct') { loadCT(); loadNews(); }
    if (page === 'cfg') loadConfig();
  },
  
  // Renderizar trade card com sparkline visual
  renderTrade(trade) {
    const isCT = (trade.tipo || '').includes('CONTRA');
    const isBuy = trade.dir === 'BUY';
    const isPos = trade.pnl >= 0;
    const cardClass = isCT ? 'ct' : (isBuy ? 'buy' : 'sell');
    const badgeClass = isBuy ? 'buy' : 'sell';
    const progress = Math.min(Math.abs(trade.pnl) / 3 * 100, 100);
    
    // Sparkline simples baseada no P&L
    const sparkBars = Array.from({length: 12}, (_, i) => {
      const h = 4 + Math.random() * 16;
      const cls = isPos ? 'up' : 'down';
      return `<div class="spark-bar ${cls}" style="height:${h}%"></div>`;
    }).join('');
    
    return `
      <div class="trade-card ${cardClass}">
        <div class="trade-header">
          <div>
            <div class="trade-symbol">
              ${trade.symbol}
              ${isCT ? '<span class="ct-badge">CT</span>' : ''}
            </div>
            <div class="trade-name">${trade.name || ''} · ${trade.opened_at || ''}</div>
          </div>
          <span class="trade-badge ${badgeClass}">${isBuy ? '▲ BUY' : '▼ SELL'}</span>
        </div>
        <div class="sparkline">${sparkBars}</div>
        <div class="trade-levels">
          <div class="level-box"><div class="level-label">Entrada</div><div class="level-value">${fmtPrice(trade.entry)}<span class="copy-btn" data-val="${trade.entry}" onclick="copyToClipboard('${trade.entry}')">📋</span></div></div>
          <div class="level-box"><div class="level-label">SL 🛡</div><div class="level-value sl">${fmtPrice(trade.sl)}<span class="copy-btn" data-val="${trade.sl}" onclick="copyToClipboard('${trade.sl}')">📋</span></div></div>
          <div class="level-box"><div class="level-label">TP 🎯</div><div class="level-value tp">${fmtPrice(trade.tp)}<span class="copy-btn" data-val="${trade.tp}" onclick="copyToClipboard('${trade.tp}')">📋</span></div></div>
        </div>
        <div class="trade-footer">
          <span class="trade-pnl ${isPos ? 'pos' : 'neg'}">${trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}%</span>
          <span class="trade-current">Atual: ${fmtPrice(trade.current)}</span>
        </div>
        <div class="progress-bar"><div class="progress-fill ${isPos ? 'pos' : 'neg'}" style="width:${progress}%"></div></div>
      </div>
    `;
  },
  
  // Renderizar ativo no scanner com indicadores visuais
  renderAsset(asset) {    const trend = asset.cenario || 'NEUTRO';
    const icon = trend === 'ALTA' ? '↑' : trend === 'BAIXA' ? '↓' : '–';
    const iconClass = trend === 'ALTA' ? 'up' : trend === 'BAIXA' ? 'down' : 'neutral';
    const changeClass = asset.change_pct >= 0 ? 'pos' : 'neg';
    const rsiClass = asset.rsi > 70 ? 'rsi-bad' : asset.rsi < 30 ? 'rsi-ok' : 'rsi-warn';
    const adxClass = asset.adx > 25 ? 'adx-strong' : 'adx-weak';
    const catMap = { FOREX:'📈', CRYPTO:'₿', COMMODITIES:'🏅', INDICES:'📊' };
    
    // Destaque para busca
    const symbolHtml = UI.state.searchQuery ? highlightText(asset.symbol, UI.state.searchQuery) : asset.symbol;
    const nameHtml = UI.state.searchQuery ? highlightText(asset.name || '', UI.state.searchQuery) : (asset.name || '');
    
    return `
      <div class="asset-row" data-symbol="${asset.symbol}" data-category="${asset.category}">
        <div class="asset-icon ${iconClass}">${icon}</div>
        <div class="asset-info">
          <div class="asset-symbol">${symbolHtml}</div>
          <div class="asset-name">${nameHtml} · ${catMap[asset.category] || ''} ${asset.category || ''}</div>
          <div class="asset-meta">
            <span class="asset-tag ${changeClass}">${asset.change_pct >= 0 ? '+' : ''}${asset.change_pct.toFixed(2)}%</span>
            <span class="asset-tag gray">RSI: ${asset.rsi.toFixed(0)}</span>
            <span class="asset-tag gray">ADX: ${asset.adx.toFixed(0)}</span>
          </div>
          <div class="asset-indicators">
            <span class="indicator-dot ${rsiClass}" title="RSI"></span>
            <span class="indicator-dot ${adxClass}" title="ADX"></span>
            <span class="price-movement ${changeClass}">
              <span class="price-arrow">${asset.change_pct >= 0 ? '▲' : '▼'}</span>
              ${Math.abs(asset.change_pct).toFixed(2)}%
            </span>
          </div>
        </div>
        <div class="asset-price">
          <div class="asset-price-value">${fmtPrice(asset.price)}</div>
        </div>
      </div>
    `;
  },
  
  // MELHORADO: Extrair dados estruturados do texto do sinal
  parseSignalData(texto) {
    const data = {};
    // Extrair ativo
    const ativoMatch = texto.match(/(?:SINAL|GATILHO|CONFIRMADO)[^\n]*?([A-Z]{3,}[\/\-]?[A-Z]{2,})/i);
    if (ativoMatch) data.ativo = ativoMatch[1];
    // Extrair direção
    if (/\bBUY\b|\bCOMPRA\b|🟢/i.test(texto)) data.dir = 'BUY 🟢';
    else if (/\bSELL\b|\bVENDA\b|🔴/i.test(texto)) data.dir = 'SELL 🔴';
    // Extrair preços
    const entryMatch = texto.match(/Entrada[:\s]*([\d.,]+)/i);
    if (entryMatch) data.entry = entryMatch[1];
    const slMatch = texto.match(/Stop\s*Loss[:\s]*([\d.,]+)/i);
    if (slMatch) data.sl = slMatch[1];
    const tpMatch = texto.match(/Take\s*Profit[:\s]*([\d.,]+)/i);
    if (tpMatch) data.tp = tpMatch[1];
    return data;
  },

  // MELHORADO: Renderizar sinal com card de dados, timer melhorado e swipe
  renderSignal(signal, isNew = false) {
    const types = {
      radar: { icon:'⚠', cls:'radar', label:'RADAR', color:'var(--blue)' },
      gatilho: { icon:'🔔', cls:'gatilho', label:'GATILHO', color:'var(--cyan)' },
      sinal: { icon:'🎯', cls:'sinal', label:'SINAL', color:'var(--green)' },
      ct: { icon:'⚡', cls:'ct', label:'CONTRA-T', color:'var(--gold)' },
      insuf: { icon:'❌', cls:'insuf', label:'INSUF.', color:'var(--text-dim)' },
      close: { icon:'🏁', cls:'close', label:'FECHADO', color:'var(--text-muted)' },
      cb: { icon:'⛔', cls:'cb', label:'CIRCUIT BR.', color:'var(--red)' }
    };    const t = types[signal.tipo] || types.radar;
    const newClass = isNew ? 'new-signal' : '';
    
    const isExec = ['gatilho', 'sinal'].includes(signal.tipo);
    const isDone = Calc.executed.includes(signal.texto);
    const isDiscarded = (JSON.parse(localStorage.getItem('discarded_sigs') || '[]')).includes(signal.unix_ts);
    
    // Verificar expiração
    const now = Date.now() / 1000;
    const elapsed = now - (signal.unix_ts || 0);
    const isExpired = isExec && elapsed >= 900;
    const expiredClass = isExpired ? 'expired' : '';
    
    // MELHORIA 1: Card de dados para sinais executáveis
    let cardData = '';
    if (isExec && !isDone && !isDiscarded) {
      const parsed = this.parseSignalData(signal.texto);
      if (parsed.entry || parsed.sl || parsed.tp) {
        const safeTexto = signal.texto.replace(/'/g, "\\'");
        cardData = `
          <div class="signal-card-data">
            ${parsed.ativo ? `<div class="card-row"><span class="label">Ativo</span><span class="value">${parsed.ativo}</span></div>` : ''}
            ${parsed.dir ? `<div class="card-row"><span class="label">Direção</span><span class="value">${parsed.dir}</span></div>` : ''}
            ${parsed.entry ? `<div class="card-row"><span class="label">Entrada</span><span class="value">${parsed.entry}</span></div>` : ''}
            ${parsed.sl ? `<div class="card-row"><span class="label">Stop Loss</span><span class="value" style="color:var(--red)">${parsed.sl}</span></div>` : ''}
            ${parsed.tp ? `<div class="card-row"><span class="label">Take Profit</span><span class="value" style="color:var(--green)">${parsed.tp}</span></div>` : ''}
            <button class="signal-copy-btn" onclick="copySignalData(this, '${safeTexto}')">📋 Copiar Dados</button>
          </div>`;
      }
    }
    
    // MELHORIA 2: Timer melhorado com barra de progresso
    let timerHtml = '';
    if (isExec && !isDone && !isDiscarded) {
      if (isExpired) {
        timerHtml = '<div class="expired-badge">⚠️ Expirado</div>';
      } else {
        timerHtml = `
          <div class="timer-container">
            <div class="timer-text" data-timer-text="${signal.unix_ts || 0}">⏱️ --:--</div>
            <div class="timer-bar-bg"><div class="timer-bar" data-timer-bar="${signal.unix_ts || 0}"></div></div>
          </div>`;
      }
    }
    
    // MELHORIA 4: Swipe hints para sinais pendentes
    const isPending = isExec && !isDone && !isDiscarded && !isExpired;
    const swipeHints = isPending ? `
      <div class="swipe-hint swipe-hint-right">✅ Executado</div>
      <div class="swipe-hint swipe-hint-left">❌ Ignorar</div>` : '';
    
    return `
      <div class="signal-item ${newClass} ${expiredClass}" data-id="${signal.unix_ts || ''}" data-tipo="${signal.tipo}" data-pending="${isPending}" ${isDone || isDiscarded ? 'style="opacity:0.5"' : ''}>
        ${swipeHints}
        <div class="signal-icon ${t.cls}">${t.icon}</div>
        <div class="signal-body">
          <div class="signal-type ${signal.tipo}" style="color:${t.color}">${t.label}</div>
          <div class="signal-text">${signal.texto}</div>
          ${timerHtml}
          ${cardData}
          ${isExec && !isDone && !isDiscarded && !isExpired ? `<button class="exec-done-btn" onclick="markExecuted(this, '${signal.texto.replace(/'/g, "\\'")}')">✅ Já operei (esconder)</button>` : ''}
        </div>
        ${isDone ? '<div class="exec-overlay"><span>✅ Já operado</span></div>' : ''}
        ${isDiscarded ? '<div class="exec-overlay"><span>❌ Ignorado</span></div>' : ''}
      </div>
    `;
  },
  
  // Virtual scroll para listas longas (otimização de performance)
  virtualScroll(containerId, items, renderItem, itemHeight = 56) {
    const container = document.getElementById(containerId);
    const content = container.querySelector('.virtual-content');
    if (!container || !content) return;
    
    const visibleCount = Math.ceil(container.clientHeight / itemHeight) + 4;
    const scrollTop = container.scrollTop;
    const startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - 2);
    const endIndex = Math.min(items.length, startIndex + visibleCount);
    
    content.style.height = `${items.length * itemHeight}px`;
    content.style.transform = `translateY(${startIndex * itemHeight}px)`;
    
    const fragment = document.createDocumentFragment();
    for (let i = startIndex; i < endIndex; i++) {
      const div = document.createElement('div');
      div.innerHTML = renderItem(items[i], i);
      fragment.appendChild(div.firstElementChild || div);
    }    
    content.innerHTML = '';
    content.appendChild(fragment);
  }
};

/* ═══════════════════════════════════════════════════════════ */
/* WRAPPERS GLOBAIS — Ponte entre onclick HTML e objeto UI     */
/* ═══════════════════════════════════════════════════════════ */

// Navigate — controle direto de pages SEM style.display inline
function navigate(page, btn) {
  // SEMPRE sair do modo Apenas Sinais ao navegar manualmente
  const app = document.getElementById('app');
  if (app && app.classList.contains('signals-only-mode')) {
    app.classList.remove('signals-only-mode');
    const toggle = document.getElementById('signalsOnlyToggle');
    if (toggle) toggle.checked = false;
    savePreferences('signalsOnly', false);
  }
  
  // Esconder todas as pages
  document.querySelectorAll('.page').forEach(function(p) {
    p.classList.remove('active');
  });
  // Desativar todos os botões nav
  document.querySelectorAll('.nav-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  
  // Mostrar a page destino
  var target = document.getElementById('page-' + page);
  if (target) {
    target.classList.add('active');
  }
  // Ativar o botão clicado
  if (btn) btn.classList.add('active');
  
  // Carregar dados da página
  try {
    if (page === 'scan') loadScanner();
    if (page === 'sig') { 
      loadSignals(); 
      if(UI && UI.state) UI.state.newSignalIds.clear(); 
      updateBadge(); 
    }
    if (page === 'ct')  { 
      loadCT(); 
      loadNews(); 
      // Garantir que a sub-página correta esteja visível
      showSubPage('ct'); 
    }
    if (page === 'cfg') loadConfig();
  } catch(e) { 
    console.warn('navigate load error:', e); 
  }
}



// NOVO: Marcar sinal como executado
function markExecuted(btn, text) {
  Calc.executed.push(text);
  localStorage.setItem('exec_sigs', JSON.stringify(Calc.executed));
  btn.closest('.signal-item').style.opacity = '0.5';
  btn.textContent = '✅ Marcado';
  btn.disabled = true;
}

// MELHORADO: Atualizar timers com barra de progresso e cores dinâmicas
function updateTimers() {
  const now = Date.now() / 1000;
  // Atualizar textos dos timers
  document.querySelectorAll('[data-timer-text]').forEach(el => {
    const uts = parseFloat(el.dataset.timerText);
    if (!uts) return;
    const left = 900 - (now - uts);
    if (left <= 0) {
      el.textContent = '⚠️ Expirado';
      el.className = 'timer-text red';
      // Marcar o signal-item como expirado
      const item = el.closest('.signal-item');
      if (item && !item.classList.contains('expired')) {
        item.classList.add('expired');
        // Substituir timer por badge
        const container = el.closest('.timer-container');
        if (container) container.outerHTML = '<div class="expired-badge">⚠️ Expirado</div>';
      }
    } else {
      const m = Math.floor(left / 60);
      const s = Math.floor(left % 60);
      el.textContent = `⏱️ ${m}:${s.toString().padStart(2, '0')}`;
      // Cores dinâmicas: verde > amarelo > vermelho
      const pct = left / 900;
      if (pct > 0.5) el.className = 'timer-text green';
      else if (pct > 0.2) el.className = 'timer-text yellow';
      else el.className = 'timer-text red';
    }
  });
  // Atualizar barras de progresso
  document.querySelectorAll('[data-timer-bar]').forEach(bar => {
    const uts = parseFloat(bar.dataset.timerBar);
    if (!uts) return;
    const left = 900 - (now - uts);
    const pct = Math.max(0, Math.min(100, (left / 900) * 100));
    bar.style.width = pct + '%';
    if (pct > 50) { bar.className = 'timer-bar green'; }
    else if (pct > 20) { bar.className = 'timer-bar yellow'; }
    else { bar.className = 'timer-bar red'; }
  });
  // Também atualizar timers legados (.exec-timer)
  document.querySelectorAll('.exec-timer').forEach(el => {
    const uts = parseFloat(el.dataset.uts);    if (!uts) return;
    const left = 900 - (now - uts);
    if (left <= 0) { el.textContent = '⚠️ Expirado'; el.style.color = 'var(--red)'; }
    else { const m = Math.floor(left / 60); const s = Math.floor(left % 60); el.textContent = `⏱️ ${m}:${s.toString().padStart(2, '0')}`; el.style.color = 'var(--cyan)'; }
  });
}
setInterval(updateTimers, 1000);

/* ═══════════════════════════════════════════════════════════ */
/* LÓGICA PRINCIPAL DO APP */
/* ═══════════════════════════════════════════════════════════ */

// Carregar dashboard principal
async function loadDashboard() {
  try {
    document.getElementById('errorBanner').style.display = 'none';
    const status = await API.getStatus();
    
    // Stats
    document.getElementById('statWins').textContent = status.wins;
    document.getElementById('statLosses').textContent = status.losses;
    document.getElementById('statWR').textContent = `${status.winrate}% WR`;
    document.getElementById('statSeq').textContent = `Seq: ${status.consecutive_losses}`;
    document.getElementById('statActive').textContent = `${status.active_trades.length}/3`;
    document.getElementById('statMode').textContent = `${status.mode} ${status.timeframe}`;
    
    // NOVO: Win rate por ativo
    UI.state.assetWR = status.asset_wr || {};
    
    // Circuit breaker
    const cbBanner = document.getElementById('cbBanner');
    if (status.paused) {
      cbBanner.style.display = 'flex';
      document.getElementById('cbTimer').textContent = `${status.cb_mins}m`;
    } else {
      cbBanner.style.display = 'none';
    }
    
    // Trades ativos
    const tradesContainer = document.getElementById('tradesContainer');
    const trades = UI.state.showClosed ? status.active_trades : status.active_trades.filter(t => !t.closed);
    if (trades.length) {
      tradesContainer.innerHTML = trades.map(UI.renderTrade).join('');    } else {
      tradesContainer.innerHTML = '<div class="empty-state"><span class="empty-icon">📭</span><div class="empty-text">Nenhum trade aberto</div></div>';
    }
    
    // Mercados
    const markets = { FOREX:'📈 FOREX', CRYPTO:'₿ Cripto', COMMODITIES:'🏅 Commodities', INDICES:'📊 Índices' };
    document.getElementById('marketsContainer').innerHTML = 
      Object.entries(status.markets).map(([k, v]) => `
        <div class="market-item">
          <span class="market-name">${markets[k] || k}</span>
          <span class="market-status ${v ? 'open' : 'closed'}">${v ? 'Aberto' : 'Fechado'}</span>
        </div>
      `).join('');
    
    // Timestamp
    document.getElementById('lastUpdate').textContent = 'Atualizado ' + new Date().toLocaleTimeString('pt-BR');
    
    // Atualizar botões de config
    updateConfigButtons();
    
  } catch (e) {
    document.getElementById('errorBanner').style.display = 'block';
    console.error('Dashboard load error:', e);
  }
}

// Carregar scanner com filtros e busca
async function loadScanner() {
  try {
    // Usar cache se disponível e recente
    let trends = FrontendCache.get('trends');
    if (!trends) {
      trends = await API.getTrends();
      FrontendCache.set('trends', trends);
    }
    
    // Contadores de tendência
    const up = trends.filter(x => x.cenario === 'ALTA').length;
    const down = trends.filter(x => x.cenario === 'BAIXA').length;
    const neutral = trends.filter(x => !x.cenario || x.cenario === 'NEUTRO').length;
    document.getElementById('trendUp').textContent = up;
    document.getElementById('trendDown').textContent = down;
    document.getElementById('trendNeutral').textContent = neutral;
    
    // Aplicar filtros
    let filtered = [...trends];
    const f = UI.state.currentFilter;
    if (f === 'up') filtered = filtered.filter(x => x.cenario === 'ALTA');
    else if (f === 'down') filtered = filtered.filter(x => x.cenario === 'BAIXA');
    else if (f === 'forex') filtered = filtered.filter(x => x.category === 'FOREX');    else if (f === 'crypto') filtered = filtered.filter(x => x.category === 'CRYPTO');
    else if (f === 'comm') filtered = filtered.filter(x => x.category === 'COMMODITIES');
    else if (f === 'idx') filtered = filtered.filter(x => x.category === 'INDICES');
    
    // Aplicar busca
    if (UI.state.searchQuery) {
      const q = UI.state.searchQuery.toLowerCase();
      filtered = filtered.filter(x => 
        x.symbol.toLowerCase().includes(q) || 
        (x.name || '').toLowerCase().includes(q)
      );
    }
    
    // Ordenar: tendência primeiro, depois por variação
    filtered.sort((a, b) => {
      const order = { ALTA: 0, BAIXA: 1, NEUTRO: 2 };
      return (order[a.cenario] ?? 2) - (order[b.cenario] ?? 2) || Math.abs(b.change_pct) - Math.abs(a.change_pct);
    });
    
    // Renderizar com virtual scroll
    const list = document.getElementById('scannerList');
    if (!filtered.length) {
      list.innerHTML = '<div class="virtual-content"></div><div class="empty-state"><span class="empty-icon">🔍</span><div class="empty-text">Nenhum ativo neste filtro.</div></div>';
    } else {
      ensureVirtualContainer('scannerList');
      UI.virtualScroll('scannerList', filtered, UI.renderAsset, 64);
      // Re-renderizar no scroll
      list.onscroll = debounce(() => UI.virtualScroll('scannerList', filtered, UI.renderAsset, 64), 16);
    }
    
  } catch (e) {
    document.getElementById('scannerList').innerHTML = '<div class="virtual-content"></div><div class="empty-state"><span class="empty-icon">⚠</span><div class="empty-text">Erro ao carregar dados</div></div>';
  }
}

// Debounced search para scanner
const debouncedSearch = debounce(() => {
  UI.state.searchQuery = document.getElementById('searchInput').value.trim();
  loadScanner();
}, 200);

// Filtros do scanner
function setScanFilter(filter, btn) {
  document.querySelectorAll('#scanFilters .chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  UI.state.currentFilter = filter;
  UI.state.searchQuery = '';
  document.getElementById('searchInput').value = '';
  loadScanner();
}
// Carregar sinais
async function loadSignals() {
  try {
    const signals = await API.getSignals();
    
    // Detectar novos sinais para animação
    const currentIds = signals.map(s => s.unix_ts).slice(0, 20);
    signals.forEach((s, i) => {
      if (!UI.state.lastSignals.includes(s.unix_ts) && i < 5) {
        UI.state.newSignalIds.add(s.unix_ts);
      }
    });
    UI.state.lastSignals = currentIds;
    
    // Filtrar
    let filtered = [...signals];
    
    // NOVO: Filtro "Executar Agora" — apenas gatilho/sinal com <15min
    if (UI.state.signalFilter === 'exec') {
      filtered = filtered.filter(s => 
        ['gatilho', 'sinal'].includes(s.tipo) && 
        (s.unix_ts > (Date.now()/1000 - 900))
      );
    } else if (UI.state.signalFilter !== 'all') {
      filtered = filtered.filter(s => s.tipo === UI.state.signalFilter);
    }
    
    // Renderizar
    const container = document.getElementById('signalsList');
    if (!filtered.length) {
      container.innerHTML = '<div class="empty-state"><span class="empty-icon">🔔</span><div class="empty-text">Nenhum sinal neste filtro.</div></div>';
    } else {
      container.innerHTML = filtered.map(s => UI.renderSignal(s, UI.state.newSignalIds.has(s.unix_ts))).reverse().join('');
      setTimeout(() => UI.state.newSignalIds.clear(), 1000);
      // MELHORIA 2: Atualizar timers imediatamente
      updateTimers();
      // MELHORIA 4: Atualizar pendentes e inicializar swipe
      updatePendingCounter();
      initSwipe();
    }
    
    // Atualizar badge
    updateBadge();
    
  } catch (e) {
    console.error('Signals load error:', e);
  }
}

// Filtros de sinais
function setSignalFilter(type, btn) {
  document.querySelectorAll('#signalFilters .chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  UI.state.signalFilter = type;  loadSignals();
}

// MELHORIA 1: Copiar dados do sinal para clipboard
function copySignalData(btn, texto) {
  // Limpar HTML tags e extrair texto puro
  const tmp = document.createElement('div');
  tmp.innerHTML = texto;
  const clean = tmp.textContent || tmp.innerText || '';
  navigator.clipboard.writeText(clean).then(() => {
    if (navigator.vibrate) navigator.vibrate(50);
    btn.innerHTML = '✅ Copiado!';
    btn.classList.add('copied');
    showToast('📋 Dados copiados!');
    setTimeout(() => { btn.innerHTML = '📋 Copiar Dados'; btn.classList.remove('copied'); }, 2000);
  }).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = clean;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showToast('📋 Copiado!');
  });
}

// MELHORIA 3: Toggle modo Apenas Sinais
function toggleSignalsOnly(enabled) {
  const app = document.getElementById('app');
  const toggle = document.getElementById('signalsOnlyToggle');
  
  if (enabled) {
    app.classList.add('signals-only-mode');
    // Salvar página atual antes de entrar no modo
    const currentActive = document.querySelector('.page.active');
    if (currentActive) {
      localStorage.setItem('last_page_before_signals', currentActive.id.replace('page-', ''));
    }
    // Navegar para sinais
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-sig').classList.add('active');
    // Atualizar botão nav ativo
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('navSig')?.classList.add('active');
    loadSignals();
  } else {
    app.classList.remove('signals-only-mode');
    // RESTAURAR navegação anterior
    const lastPage = localStorage.getItem('last_page_before_signals') || 'dash';
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('page-' + lastPage)?.classList.add('active');
    // Restaurar botão nav correspondente
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    const navMap = {dash:0, scan:1, sig:2, ct:3, cfg:4};
    const navBtns = document.querySelectorAll('.nav-btn');
    if (navMap[lastPage] !== undefined && navBtns[navMap[lastPage]]) {
      navBtns[navMap[lastPage]].classList.add('active');
    }
    // Recarregar dados da página restaurada
    if (lastPage === 'dash') loadDashboard();
    if (lastPage === 'scan') loadScanner();
    if (lastPage === 'sig') loadSignals();
    if (lastPage === 'ct') { loadCT(); loadNews(); }
    if (lastPage === 'cfg') loadConfig();
  }
  if (toggle) toggle.checked = enabled;
  savePreferences('signalsOnly', enabled);
}


// MELHORIA 4: Descartar sinal (swipe left)
function discardSignal(unixTs) {
  const discarded = JSON.parse(localStorage.getItem('discarded_sigs') || '[]');
  if (!discarded.includes(unixTs)) {
    discarded.push(unixTs);
    localStorage.setItem('discarded_sigs', JSON.stringify(discarded));
  }
}

// MELHORIA 4: Atualizar contador de pendentes
function updatePendingCounter() {
  const items = document.querySelectorAll('.signal-item[data-pending="true"]');
  const counter = document.getElementById('pendingCounter');
  const countEl = document.getElementById('pendingCount');
  if (items.length > 0) {
    counter.style.display = 'flex';
    countEl.textContent = items.length;
  } else {
    counter.style.display = 'none';
  }
}

// MELHORIA 4: Inicializar swipe nos sinais pendentes
function initSwipe() {
  const container = document.getElementById('signalsList');
  if (!container) return;
  
  let startX = 0, startY = 0, currentItem = null, swiping = false;
  const THRESHOLD = 80;
  
  container.addEventListener('touchstart', function(e) {
    const item = e.target.closest('.signal-item[data-pending="true"]');
    if (!item) return;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    currentItem = item;
    swiping = false;
  }, { passive: true });
  
  container.addEventListener('touchmove', function(e) {
    if (!currentItem) return;
    const dx = e.touches[0].clientX - startX;
    const dy = e.touches[0].clientY - startY;
    
    // Só ativar swipe se movimento horizontal > vertical
    if (!swiping && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) {
      swiping = true;
      currentItem.classList.add('swiping');
    }
    
    if (swiping) {
      e.preventDefault();
      currentItem.style.transform = `translateX(${dx}px)`;
      currentItem.style.opacity = Math.max(0.3, 1 - Math.abs(dx) / 300);
    }
  }, { passive: false });
  
  container.addEventListener('touchend', function(e) {
    if (!currentItem || !swiping) { currentItem = null; return; }
    
    const dx = e.changedTouches[0].clientX - startX;
    currentItem.classList.remove('swiping');
    
    if (dx > THRESHOLD) {
      // Swipe direita = executado
      currentItem.classList.add('swipe-dismiss');
      const texto = currentItem.querySelector('.signal-text')?.textContent || '';
      Calc.executed.push(texto);
      localStorage.setItem('exec_sigs', JSON.stringify(Calc.executed));
      showToast('✅ Marcado como executado');
      if (navigator.vibrate) navigator.vibrate(50);
      setTimeout(() => { currentItem.remove(); updatePendingCounter(); }, 300);
    } else if (dx < -THRESHOLD) {
      // Swipe esquerda = descartar
      currentItem.classList.add('swipe-dismiss-left');
      const unixTs = parseFloat(currentItem.dataset.id);
      if (unixTs) discardSignal(unixTs);
      showToast('❌ Sinal ignorado');
      if (navigator.vibrate) navigator.vibrate([30, 30]);
      setTimeout(() => { currentItem.remove(); updatePendingCounter(); }, 300);
    } else {
      // Voltar ao lugar
      currentItem.style.transform = '';
      currentItem.style.opacity = '';
    }
    currentItem = null;
    swiping = false;
  }, { passive: true });
}

// Atualizar badge de notificação
function updateBadge() {
  const badge = document.getElementById('sigBadge');
  const unread = UI.state.newSignalIds.size;
  if (unread > 0) {
    badge.style.display = 'flex';
    badge.textContent = unread > 9 ? '9+' : unread;
  } else {
    badge.style.display = 'none';
  }
}

// Carregar oportunidades CT
async function loadCT() {
  const container = document.getElementById('ctList');
  container.innerHTML = '<div class="empty-state"><span class="empty-icon spin">⚡</span><div class="empty-text">Analisando oportunidades...</div></div>';
  
  try {
    const reversals = await API.getReversals();
    if (!reversals.length) {
      container.innerHTML = '<div class="empty-state"><span class="empty-icon">⚡</span><div class="empty-text">Nenhuma oportunidade CT detectada.</div></div>';
      return;
    }
    
    container.innerHTML = reversals.map(r => {
      const isBuy = r.direction === 'BUY';
      const reasons = (r.reasons || []).slice(0, 4).map(s => `<span class="asset-tag gray">${s}</span>`).join('');
      const rsiClass = r.rsi > 70 ? 'red' : r.rsi < 30 ? 'green' : '';
      
      return `
        <div class="trade-card ct">
          <div class="trade-header">
            <div>
              <div class="trade-symbol">${r.symbol} <span style="font-size:10px;color:var(--text-muted)">${r.name}</span></div>
            </div>
            <span class="trade-badge" style="background:var(--gold-soft);color:var(--gold);border:1px solid var(--gold-border)">${r.strength}%</span>
          </div>
          <div style="font-size:11px;font-weight:600;margin:8px 0;color:${isBuy ? 'var(--green)' : 'var(--red)'}">
            ${isBuy ? '▲ COMPRAR' : '▼ VENDER'} — ${isBuy ? 'Baixa→Alta' : 'Alta→Baixa'}
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">${reasons}</div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">
            <div style="text-align:center"><div style="font-size:8px;color:var(--text-muted)">Preço</div><div style="font-size:13px;font-family:var(--font-mono);font-weight:700">${fmtPrice(r.price)}</div></div>
            <div style="text-align:center"><div style="font-size:8px;color:var(--text-muted)">RSI</div><div style="font-size:13px;font-family:var(--font-mono);font-weight:700" class="${rsiClass}">${r.rsi.toFixed(1)}</div></div>
            <div style="text-align:center"><div style="font-size:8px;color:var(--text-muted)">Força</div><div style="font-size:13px;font-family:var(--font-mono);font-weight:700;color:var(--gold)">${r.strength}%</div></div>
          </div>
        </div>      `;
    }).join('');
    
  } catch (e) {
    container.innerHTML = '<div class="empty-state"><span class="empty-icon">⚠</span><div class="empty-text">Erro ao carregar</div></div>';
  }
}

// Carregar notícias
async function loadNews() {
  const container = document.getElementById('newsList');
  try {
    const data = await API.getNews();
    const fg = data.fg;
    
    // Fear & Greed
    if (fg && fg.value) {
      const val = parseInt(fg.value) || 0;
      document.getElementById('fgValue').textContent = `${fg.value} – ${fg.label}`;
      document.getElementById('fgScore').textContent = fg.value;
      document.getElementById('fgValue').style.color = val > 60 ? 'var(--green)' : val < 40 ? 'var(--red)' : 'var(--gold)';
    }
    
    // Notícias
    const articles = data.articles || [];
    if (!articles.length) {
      container.innerHTML = '<div class="empty-state"><span class="empty-icon">📰</span><div class="empty-text">Sem notícias no momento.</div></div>';
      return;
    }
    
    container.innerHTML = articles.map((a, i) => `
      <div style="display:flex;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)${i === articles.length-1 ? ';border-bottom:none' : ''}">
        <div style="width:24px;height:24px;border-radius:6px;background:var(--bg4);display:flex;align-items:center;justify-content:center;font-size:10px;font-family:var(--font-mono);color:var(--text-muted);flex-shrink:0;margin-top:2px">${i+1}</div>
        <div style="flex:1;min-width:0">
          <a href="${a.url || '#'}" target="_blank" style="font-size:12px;line-height:1.5;color:var(--text);text-decoration:none;display:block">${a.title || ''}</a>
          <div style="font-size:9px;color:var(--text-muted);margin-top:4px">${a.source || ''}</div>
        </div>
      </div>
    `).join('');
    
  } catch (e) {
    container.innerHTML = '<div class="empty-state"><span class="empty-icon">⚠</span><div class="empty-text">Erro ao carregar notícias</div></div>';
  }
}

// Sub-páginas (CT/News)
function showSubPage(page) {
  const subCT = document.getElementById('subCT');
  const subNews = document.getElementById('subNews');
  const tabCT = document.getElementById('tabCT');
  const tabNews = document.getElementById('tabNews');
  
  if (page === 'ct') {
    if (subCT) subCT.style.setProperty('display', 'block', 'important');
    if (subNews) subNews.style.setProperty('display', 'none', 'important');
  } else {
    if (subCT) subCT.style.setProperty('display', 'none', 'important');
    if (subNews) subNews.style.setProperty('display', 'block', 'important');
  }
  
  if (tabCT) tabCT.classList.toggle('active', page === 'ct');
  if (tabNews) tabNews.classList.toggle('active', page === 'news');
  
  if (page === 'news') loadNews();
}


// Carregar config
async function loadConfig() {
  try {
    const cfg = await API.getConfig();
    document.getElementById('paramSL').textContent = `${cfg.atm_sl}×ATR`;
    document.getElementById('paramTP').textContent = `${cfg.atr_tp}×ATR`;
    document.getElementById('paramMax').textContent = cfg.max_trades;
    document.getElementById('paramConf').textContent = `${cfg.min_conf}/7`;
  } catch (_) {}
  updateConfigButtons();
  updateNotificationButton();
}

// Atualizar botões de config
function updateConfigButtons() {
  // Modo
  document.querySelectorAll('[data-mode]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === window._status?.mode);
  });
  // Timeframe
  document.querySelectorAll('[data-tf]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tf === window._status?.timeframe);
  });
}

// Setar modo
async function setMode(mode) {
  try {
    await API.setMode(mode);
    await loadDashboard();
  } catch (e) { alert('Erro: ' + e.message); }
}

// Setar timeframe
async function setTimeframe(tf) {
  try {
    await API.setTimeframe(tf);
    await loadDashboard();
  } catch (e) { alert('Erro: ' + e.message); }
}

// Reset circuit breaker
async function resetCircuitBreaker() {
  if (!confirm('Resetar Circuit Breaker?')) return;
  try {
    await API.resetPause();    await loadDashboard();
  } catch (e) { alert('Erro: ' + e.message); }
}

// Toggle trades fechados
function toggleClosedTrades() {
  UI.state.showClosed = document.getElementById('toggleClosed').checked;
  loadDashboard();
}

// Refresh global
async function refreshAll() {
  const btn = document.getElementById('refreshBtn');
  btn.classList.add('refreshing');
  FrontendCache.clear();
  
  try {
    await loadDashboard();
    const activePage = document.querySelector('.page.active').id;
    if (activePage === 'page-scan') await loadScanner();
    if (activePage === 'page-sig') await loadSignals();
  } finally {
    btn.classList.remove('refreshing');
  }
}

/* ═══════════════════════════════════════════════════════════ */
/* NOTIFICAÇÕES PUSH */
/* ═══════════════════════════════════════════════════════════ */

let swRegistration = null;

async function initServiceWorker() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  try {
    swRegistration = await navigator.serviceWorker.register('/sw.js');
    console.log('[SniperBot] SW registrado');
  } catch (e) { console.warn('[SniperBot] SW error:', e); }
}

async function toggleNotifications() {
  if (!('Notification' in window)) {
    alert('Seu navegador não suporta notificações push.');
    return;
  }
  
  if (Notification.permission === 'denied') {
    alert('Notificações bloqueadas. Habilite nas configurações do navegador.');
    return;
  }  
  if (Notification.permission === 'granted') {
    await subscribeUser();
    return;
  }
  
  const perm = await Notification.requestPermission();
  if (perm === 'granted') await subscribeUser();
  updateNotificationButton();
}

async function subscribeUser() {
  if (!swRegistration) {
    alert('Service worker não disponível. Recarregue a página.');
    return;
  }
  
  try {
    const vapid = await API.getVapidKey();
    if (!vapid.key) {
      alert('VAPID não configurado no servidor.\nAdicione VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY nas variáveis de ambiente.');
      return;
    }
    
    const subscription = await swRegistration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapid.key)
    });
    
    await API.subscribePush(subscription);
    document.getElementById('notifStatus').textContent = '✅ Notificações ativadas!';
    document.getElementById('notifBtn').textContent = '🔕 Gerenciar Notificações';
    
  } catch (e) {
    document.getElementById('notifStatus').textContent = 'Erro: ' + e.message;
  }
  updateNotificationButton();
}

function updateNotificationButton() {
  const btn = document.getElementById('notifBtn');
  const status = document.getElementById('notifStatus');
  
  if (!('Notification' in window) || !('PushManager' in window)) {
    btn.textContent = '❌ Push não suportado';
    btn.disabled = true;
    return;
  }
  
  if (Notification.permission === 'denied') {    btn.textContent = '🚫 Notificações bloqueadas';
    btn.disabled = true;
    return;
  }
  
  if (Notification.permission === 'granted') {
    btn.textContent = '✅ Notificações Ativas';
  } else {
    btn.textContent = '🔔 Ativar Notificações Push';
  }
  btn.disabled = false;
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

/* ═══════════════════════════════════════════════════════════ */
/* INICIALIZAÇÃO */
/* ═══════════════════════════════════════════════════════════ */

// Manifest dinâmico para PWA
const manifest = {
  name: 'Sniper Bot',
  short_name: 'SniperBot',
  start_url: '/',
  display: 'standalone',
  orientation: 'portrait',
  background_color: '#06090f',
  theme_color: '#06090f',
  icons: [
    { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any maskable' },
    { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' }
  ]
};
const manifestBlob = new Blob([JSON.stringify(manifest)], { type: 'application/json' });
const manifestLink = document.createElement('link');
manifestLink.rel = 'manifest';
manifestLink.href = URL.createObjectURL(manifestBlob);
document.head.appendChild(manifestLink);

// Carregar preferências salvas
function loadPreferences() {
  const saved = localStorage.getItem('sniper_prefs');
  if (!saved) return;

  try {
    const prefs = JSON.parse(saved);

    if (prefs.theme) {
      document.documentElement.setAttribute('data-theme', prefs.theme);
    }

    if (prefs.signalFilter) {
      UI.state.signalFilter = prefs.signalFilter;
      const btn = document.querySelector(`#signalFilters .chip[data-type="${prefs.signalFilter}"]`);
      if (btn) {
        document.querySelectorAll('#signalFilters .chip').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
      }
    }

    if (prefs.signalsOnly) {
      setTimeout(() => toggleSignalsOnly(true), 100);
    }
  } catch (e) {
    console.warn('Erro ao carregar preferências:', e);
  }
}

function savePreferences(key, value) {
  const prefs = JSON.parse(localStorage.getItem('sniper_prefs') || '{}');
  prefs[key] = value;
  localStorage.setItem('sniper_prefs', JSON.stringify(prefs));
}

// Init
window.addEventListener('load', async () => {
  try {
    initServiceWorker();

    // Carregar preferências primeiro
    loadPreferences();

    // Inicializar calculadora
    if (typeof Calc !== 'undefined' && Calc && typeof Calc.init === 'function') {
      Calc.init();
    }

    // Evita ativação automática do modo Apenas Sinais no carregamento
    const prefs = JSON.parse(localStorage.getItem('sniper_prefs') || '{}');
    if (prefs.signalsOnly) {
      const toggle = document.getElementById('signalsOnlyToggle');
      if (toggle) toggle.checked = false;
      savePreferences('signalsOnly', false);
    }

    // Carregar dados iniciais
    await loadDashboard();

    window._status = await API.getStatus();

    // Garantir que a página dashboard está ativa por padrão
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const dash = document.getElementById('page-dash');
    if (dash) dash.classList.add('active');

    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.nav-btn')?.classList.add('active');

    // Auto-refresh a cada 30s
    setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadDashboard();
        if (document.querySelector('.page.active')?.id === 'page-sig') {
          loadSignals();
        }
      }
    }, 30000);

    // Listener para visibilidade
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        loadDashboard();
        if (document.querySelector('.page.active')?.id === 'page-sig') {
          loadSignals();
        }
      }
    });

  } catch (err) {
    console.error('Erro na inicialização:', err);
  }
});

  // ================================
  // AUTO-REFRESH DASHBOARD
  // ================================

  setInterval(() => {

    try {

      if (document.visibilityState === 'visible') {

        if (typeof loadDashboard === "function") {
          loadDashboard();
        }

        const activePage =
          document.querySelector('.page.active');

        if (
          activePage &&
          activePage.id === 'page-sig'
        ) {
          if (typeof loadSignals === "function") {
            loadSignals();
          }
        }

      }

    } catch (err) {

      console.error(
        "Erro no auto-refresh:",
        err
      );

    }

  }, 30000);



  // ================================
  // VISIBILITY LISTENER
  // ================================

  document.addEventListener(
    'visibilitychange',
    () => {

      try {

        if (
          document.visibilityState === 'visible'
        ) {

          if (typeof loadDashboard === "function") {
            loadDashboard();
          }

          const activePage =
            document.querySelector('.page.active');

          if (
            activePage &&
            activePage.id === 'page-sig'
          ) {

            if (typeof loadSignals === "function") {
              loadSignals();
            }

          }

        }

      } catch (err) {

        console.error(
          "Erro ao voltar para aba:",
          err
        );

      }

    }
  );



  // ================================
  // INICIALIZAÇÃO FINAL
  // ================================

  window.addEventListener(
    'load',
    () => {

      try {

        console.log(
          "🚀 Dashboard inicializado"
        );

        if (typeof loadDashboard === "function") {
          loadDashboard();
        }

        if (typeof loadSignals === "function") {
          loadSignals();
        }

      } catch (err) {

        console.error(
          "Erro na inicialização:",
          err
        );

      }

    }
  );
  


  
  
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
# FLASK API (COM MELHORIAS ADICIONADAS)
# ═══════════════════════════════════════════════════════════════
def create_api(bot):
    app = Flask(__name__)
    CORS(app)

    @app.after_request
    def cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"]  = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    @app.route("/")
    def index(): return Response(DASHBOARD_HTML, mimetype="text/html")

    @app.route("/sw.js")
    def sw(): return Response(SW_JS, mimetype="application/javascript")

    @app.route("/icon-192.png")
    @app.route("/icon-512.png")
    def icon():
        size = 192 if "192" in request.path else 512
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" rx="{size//6}" fill="#06090f"/><text x="{size//2}" y="{int(size*.72)}" font-size="{int(size*.55)}" text-anchor="middle" fill="#00e676" font-family="monospace" font-weight="700">S</text></svg>'
        return Response(svg, mimetype="image/svg+xml")

    @app.route("/api/health")
    def api_health(): return jsonify({"status": "ok", "version": "7.2"})

    @app.route("/api/status")
    def api_status():
        total = bot.wins + bot.losses
        wr    = round(bot.wins/total*100, 1) if total > 0 else 0
        trades_out = []
        for t in bot.active_trades:
            try: res = get_analysis(t["symbol"], bot.timeframe); cur = res["price"] if res else t["entry"]
            except: cur = t["entry"]
            pnl = (cur-t["entry"])/t["entry"]*100
            if t["dir"] == "SELL": pnl = -pnl
            trades_out.append({"symbol": t["symbol"], "name": t.get("name",""), "dir": t["dir"],
                "tipo": t.get("tipo",""), "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
                "current": cur, "pnl": round(pnl,2), "opened_at": t.get("opened_at","")})
                # NOVO: Calcular win rate por ativo para exibir no frontend
        asset_wr = {}
        for h in bot.history:
            s = h["symbol"]
            if s not in asset_wr: asset_wr[s] = {"w":0, "l":0}
            asset_wr[s]["w" if h["result"]=="WIN" else "l"] += 1
        asset_wr_out = {k: f"{int(v['w']/(v['w']+v['l'])*100) if v['w']+v['l']>0 else 0}%" for k,v in asset_wr.items()}
        
        return jsonify({
            "wins": bot.wins, "losses": bot.losses, "winrate": wr,
            "consecutive_losses": bot.consecutive_losses, "mode": bot.mode, "timeframe": bot.timeframe,
            "paused": bot.is_paused(), "cb_mins": max(0,int((bot.paused_until-time.time())/60)) if bot.is_paused() else 0,
            "active_trades": trades_out,
            "markets": {cat: mkt_open(cat) for cat in Config.MARKET_CATEGORIES.keys()},
            "asset_wr": asset_wr_out  # ← NOVO: win rate por ativo
        })

    @app.route("/api/config")
    def api_config():
        return jsonify({"atm_sl": Config.ATR_MULT_SL, "atr_tp": Config.ATR_MULT_TP,
                        "max_trades": Config.MAX_TRADES, "min_conf": Config.MIN_CONFLUENCE})

    @app.route("/api/history")
    def api_history(): return jsonify(list(reversed(bot.history[-50:])))

    @app.route("/api/signals")
    def api_signals(): return jsonify(list(reversed(bot.signals_feed)))

    @app.route("/api/news")
    def api_news():
        now = time.time()
        if now - bot.news_cache_ts > 600 or not bot.news_cache:
            try:
                bot.news_cache    = {"fg": get_fear_greed(), "articles": get_news(15)}
                bot.news_cache_ts = now
            except Exception as e: log(f"[NEWS] {e}")
        return jsonify(bot.news_cache if bot.news_cache else {"fg": {}, "articles": []})

    @app.route("/api/trends")
    def api_trends():
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            d = entry["data"]
            out.append({"symbol": sym, "name": d["name"], "category": asset_cat(sym),
                "price": d["price"], "cenario": d["cenario"], "rsi": round(d["rsi"],1),
                "adx": round(d["adx"],1), "change_pct": round(d["change_pct"],2),
                "macd_bull": d["macd_bull"], "macd_bear": d["macd_bear"],
                "h1_bull": d["h1_bull"], "h1_bear": d["h1_bear"]})
        out.sort(key=lambda x: ({"ALTA":0,"BAIXA":1,"NEUTRO":2}.get(x["cenario"],9), -abs(x["change_pct"])))
        return jsonify(out)

    @app.route("/api/reversals")
    def api_reversals():
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            rev = entry.get("reversal", {})
            if rev.get("has"):
                d = entry["data"]
                out.append({"symbol": sym, "name": d["name"], "price": d["price"],
                    "rsi": round(d["rsi"],1), "adx": round(d["adx"],1),
                    "direction": rev["dir"], "strength": rev["strength"], "reasons": rev["reasons"]})
        out.sort(key=lambda x: -x["strength"])
        return jsonify(out)

    @app.route("/api/mode", methods=["POST","OPTIONS"])
    def api_mode():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        mode = data.get("mode","")
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]: return jsonify({"error":"inválido"}),400
        bot.set_mode(mode); return jsonify({"ok": True})

    @app.route("/api/timeframe", methods=["POST","OPTIONS"])
    def api_timeframe():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        tf = data.get("timeframe","")
        if tf not in Config.TIMEFRAMES: return jsonify({"error":"inválido"}),400
        bot.set_timeframe(tf); return jsonify({"ok": True})

    @app.route("/api/resetpausa", methods=["POST","OPTIONS"])
    def api_reset():
        if request.method == "OPTIONS": return jsonify({}), 200
        bot.reset_pause(); return jsonify({"ok": True})

    @app.route("/api/vapid-public-key")
    def api_vapid_key():
        key = os.getenv("VAPID_PUBLIC_KEY","")
        return jsonify({"key": key})

    @app.route("/api/subscribe", methods=["POST","OPTIONS"])
    def api_subscribe():
        if request.method == "OPTIONS": return jsonify({}), 200
        sub = request.get_json(force=True)
        if sub and sub not in _push_subscriptions:
            _push_subscriptions.append(sub)
            log(f"[PUSH] Nova inscrição. Total: {len(_push_subscriptions)}")
        return jsonify({"ok": True})
    return app


def run_api(bot):
    port = int(os.getenv("PORT", 8080))
    app  = create_api(bot)
    log(f"🌐 Flask rodando na porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


# ═══════════════════════════════════════════════════════════════
# LOOP DO BOT (thread separada - INALTERADO)
# ═══════════════════════════════════════════════════════════════
def bot_loop(bot):
    bot.build_menu()
    if bot._restore_msg: bot.send(bot._restore_msg); bot._restore_msg = None
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
                        txt = u["message"].get("text","").strip().lower()
                        if txt in ("/noticias","/news"): bot.send_news()
                        elif txt == "/status":           bot.send_status()
                        elif txt in ("/placar","/score"):bot.send_placar()
                        elif txt in ("/menu","/start"):  bot.build_menu()
                        elif txt == "/resetpausa":       bot.reset_pause()
                    if "callback_query" in u:
                        cb = u["callback_query"]["data"]; cid = u["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery",
                                      json={"callback_query_id": cid}, timeout=5)
                        if cb.startswith("set_tf_"):  bot.set_timeframe(cb.replace("set_tf_",""))
                        elif cb.startswith("set_"):   bot.set_mode(cb.replace("set_",""))
                        elif cb == "tf_menu":         bot.build_tf_menu()
                        elif cb == "main_menu":       bot.build_menu()
                        elif cb == "news":            bot.send_news()
                        elif cb == "status":          bot.send_status()
                        elif cb == "placar":          bot.send_placar()
            bot.update_trends_cache()
            bot.maybe_send_news()
            bot.scan()
            bot.scan_reversal_forex()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)
        except Exception as e:
            log(f"Erro loop: {e}"); time.sleep(10)


# ═══════════════════════════════════════════════════════════════
# MAIN (INALTERADO)
# ═══════════════════════════════════════════════════════════════
def main():
    log("🔌 Bot Sniper v7.2 — Visual + Performance + Real-Time Optimized")
    try: requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=8)
    except: pass

    bot = TradingBot()
    load_state(bot)

    t = threading.Thread(target=bot_loop, args=(bot,), daemon=True)
    t.start()

    run_api(bot)


if __name__ == "__main__":
    main()
