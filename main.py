# -*- coding: utf-8 -*-
"""
BOT SNIPER v7.1 — Multi-mercado + API HTTP + Dashboard PWA + Push Notifications
═══════════════════════════════════════════════════════════════════════════════
ARQUITETURA: Flask serve o HTML/API direto (1 único app no Railway)
NOVIDADES v7.1 (sobre v7):
  • Scan em 4 fases restaurado: RADAR → GATILHO → SINAL → INSUF.
  • Scan de Contra-Tendência FOREX (CT) restaurado
  • Feed de sinais (/api/signals) restaurado
  • Notícias (/api/news) com cache
  • Push Notifications via Web Push API (funciona mesmo com app fechado)
  • Dashboard com 5 abas completas
  • MATIC-USD → POL-USD corrigido
  • Feeds RSS funcionais
"""
import os, time, json, math, threading, requests
import pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
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
                "LINK-USD": "Chainlink", "DOT-USD":  "Polkadot",
                "POL-USD":  "Polygon",   "LTC-USD":  "Litecoin",
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
# HELPERS DE MERCADO
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
    for c in Config.MARKET_CATEGORIES.values(): out.extend(c["assets"].keys())
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
# PERSISTÊNCIA
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
        bot.history            = data.get("history", [])
        for t in bot.active_trades: t["session_alerted"] = False
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
# NOTÍCIAS / FEAR & GREED
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
    arts = get_news(5); fg = get_fear_greed()
    lines = ["📰 <b>NOTÍCIAS</b>\n"]
    for i, a in enumerate(arts, 1):
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else "")
        lines.append(f"{i}. <a href='{a['url']}'>{t}</a> <i>({a['source']})</i>")
    lines.append(f"\n😱 F&amp;G: <b>{fg['value']} – {fg['label']}</b>")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# MOTOR DE ANÁLISE PRINCIPAL
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
# CONFLUÊNCIA
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
    else:
        checks = [
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
# MOTOR DE CONTRA-TENDÊNCIA (FOREX)
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
            ("RSI sobrecomprado",  res["rsi_overbought"]),
            ("Banda Superior BB",  res["near_upper"]),
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
# PUSH NOTIFICATIONS
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
# BOT PRINCIPAL
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
            self.signals_feed.append({
                "tipo": tipo, "texto": clean[:300],
                "ts": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
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
                        f"⚠️ <b>RADAR – {s}</b> ({res['name']})\n"
                        f"{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
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
            sl_pct = abs(price-sl)/price*100; tp_pct = abs(tp-price)/price*100
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
# SERVICE WORKER JS
# ═══════════════════════════════════════════════════════════════
SW_JS = """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => clients.claim());
self.addEventListener('push', e => {
  let data = {title: 'Sniper Bot', body: 'Novo sinal!', icon: '/icon-192.png'};
  try { data = JSON.parse(e.data.text()); } catch(_) {}
  e.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, icon: data.icon || '/icon-192.png',
    badge: '/icon-192.png', vibrate: [200, 100, 200],
    data: { url: '/' }
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({type:'window'}).then(cs => {
    if (cs.length) cs[0].focus();
    else clients.openWindow('/');
  }));
});
"""

# ═══════════════════════════════════════════════════════════════
# DASHBOARD HTML (embutido)
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
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{--bg:#06090f;--bg2:#0b1018;--bg3:#111827;--bg4:#192032;--border:#1e2d45;--text:#d4e4f7;--muted:#3d5575;--muted2:#5a7a9f;--green:#00e676;--green2:#00c853;--g3:rgba(0,230,118,.12);--red:#ff1744;--red2:#d50000;--r3:rgba(255,23,68,.1);--gold:#ffca28;--y3:rgba(255,202,40,.12);--blue:#448aff;--cyan:#00e5ff;--orange:#ff6d00;--mono:'JetBrains Mono',monospace;--sans:'DM Sans',sans-serif;--r:14px;--rsm:8px;--nav:62px;--safe:env(safe-area-inset-bottom,0px);--head:58px}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:var(--sans);-webkit-font-smoothing:antialiased}
body::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:9998;background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,0,0,.04) 3px,rgba(0,0,0,.04) 4px)}
#app{display:flex;flex-direction:column;height:100%;max-width:500px;margin:0 auto}
#hdr{height:var(--head);flex-shrink:0;background:linear-gradient(135deg,var(--bg2),#080d16);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 18px;z-index:100}
.hdr-l{display:flex;align-items:center;gap:11px}
.logo{width:36px;height:36px;border-radius:9px;background:linear-gradient(135deg,#00c853,#00e5ff);display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:17px;font-weight:700;color:#000;box-shadow:0 0 18px rgba(0,230,118,.3)}
.t1{font-size:16px;font-weight:700}.t2{font-size:9px;color:var(--muted2);letter-spacing:1.5px;text-transform:uppercase;margin-top:1px}
.hdr-r{display:flex;align-items:center;gap:8px}
.lpill{display:flex;align-items:center;gap:5px;background:var(--bg3);border:1px solid var(--border);border-radius:20px;padding:4px 10px;font-size:9px;color:var(--muted2);letter-spacing:1px;text-transform:uppercase}
.ldot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:blink 2s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.ibtn{width:34px;height:34px;border-radius:9px;border:1px solid var(--border);background:var(--bg3);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:15px;transition:.15s;color:var(--muted2)}
.ibtn:active{background:var(--border);transform:scale(.92)}
#pages{flex:1;overflow:hidden;position:relative}
.pg{position:absolute;inset:0;display:none;overflow-y:auto;padding:14px 14px calc(var(--nav) + var(--safe) + 10px);opacity:0;transform:translateY(5px);transition:opacity .2s,transform .2s}
.pg.on{display:block;opacity:1;transform:translateY(0)}
.pg::-webkit-scrollbar{width:2px}
.pg::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
#nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:500px;height:var(--nav);background:var(--bg2);border-top:1px solid var(--border);display:flex;z-index:200;padding-bottom:var(--safe)}
.nb{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:none;background:none;cursor:pointer;font-size:9px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase;padding:0;transition:.2s;position:relative}
.nb .ni{font-size:18px;transition:.2s}
.nb.on{color:var(--green)}.nb.on .ni{transform:scale(1.1)}
.nb:active{opacity:.7}
.nbadge{position:absolute;top:6px;right:calc(50% - 17px);width:15px;height:15px;border-radius:50%;background:var(--red);color:#fff;font-size:8px;display:none;align-items:center;justify-content:center;font-family:var(--mono);font-weight:700}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:10px}
.chd{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);margin-bottom:12px;display:flex;align-items:center;justify-content:space-between}
.srow{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px}
.sb{background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:12px 10px}
.sl{font-size:8px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:5px}
.sv{font-size:22px;font-weight:700;font-family:var(--mono);line-height:1}
.ss{font-size:9px;color:var(--muted2);margin-top:3px}
.g{color:var(--green)}.r{color:var(--red)}.go{color:var(--gold)}.cy{color:var(--cyan)}.bl{color:var(--blue)}.or{color:var(--orange)}
.tc{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:8px}
.tc.buy{border-left:3px solid var(--green)}.tc.sell{border-left:3px solid var(--red)}
.tc.ctb{border-left:3px solid var(--gold)}.tc.cts{border-left:3px solid var(--orange)}
.tc-top{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px}
.tc-sym{font-size:17px;font-weight:700;font-family:var(--mono)}
.tc-nm{font-size:9px;color:var(--muted2);margin-top:2px}
.db{font-size:10px;font-weight:700;font-family:var(--mono);padding:5px 10px;border-radius:20px}
.dbu{background:var(--g3);color:var(--green)}.dbs{background:var(--r3);color:var(--red)}
.lvls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px}
.lv{background:var(--bg3);border-radius:var(--rsm);padding:8px 6px;text-align:center}
.lvl{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px}
.lvv{font-size:11px;font-family:var(--mono);font-weight:700}
.tcft{display:flex;align-items:center;justify-content:space-between}
.pnl{font-size:16px;font-weight:700;font-family:var(--mono)}
.tcm{font-size:9px;color:var(--muted2)}
.pbar{height:3px;background:var(--bg4);border-radius:2px;margin-top:8px;overflow:hidden}
.pbar-f{height:100%;border-radius:2px;transition:width .5s}
.pg-fill{background:linear-gradient(90deg,var(--green2),var(--green))}.pr-fill{background:linear-gradient(90deg,var(--red2),var(--red))}
.mg{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.mkt{background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:9px 12px;display:flex;align-items:center;justify-content:space-between}
.mktn{font-size:11px;font-weight:500}
.mkts{font-size:8px;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px;font-family:var(--mono)}
.mop{background:var(--g3);color:var(--green)}.mcl{background:var(--r3);color:var(--red)}
.fchips{display:flex;gap:6px;margin-bottom:12px;overflow-x:auto;padding-bottom:4px}
.fchips::-webkit-scrollbar{display:none}
.fc{flex-shrink:0;padding:5px 12px;border-radius:20px;border:1px solid var(--border);background:var(--bg3);font-size:11px;cursor:pointer;transition:.15s;color:var(--muted2);white-space:nowrap}
.fc.on{background:var(--g3);border-color:var(--green);color:var(--green)}.fc:active{transform:scale(.96)}
.si{display:flex;align-items:center;gap:10px;padding:11px 0;border-bottom:1px solid var(--border)}
.si:last-child{border-bottom:none}
.sico{width:38px;height:38px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;font-family:var(--mono);flex-shrink:0}
.siA{background:var(--g3);color:var(--green)}.siB{background:var(--r3);color:var(--red)}.siN{background:var(--bg4);color:var(--muted2)}
.sinf{flex:1;min-width:0}
.ssym{font-size:13px;font-weight:700;font-family:var(--mono)}
.snm{font-size:9px;color:var(--muted2);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.srgt{text-align:right;flex-shrink:0}
.spr{font-size:12px;font-family:var(--mono);font-weight:600}
.stags{display:flex;gap:4px;margin-top:3px;justify-content:flex-end;flex-wrap:wrap}
.tag{font-size:8px;font-family:var(--mono);padding:1px 5px;border-radius:3px}
.tg{background:var(--g3);color:var(--green)}.tr{background:var(--r3);color:var(--red)}.tn{background:var(--bg4);color:var(--muted2)}
.tbar{display:flex;align-items:center;gap:6px;margin-bottom:12px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:8px 12px}
.tbl{font-size:9px;color:var(--muted2);letter-spacing:.8px;text-transform:uppercase;flex:1}
.tbc{font-size:12px;font-family:var(--mono)}
.sigit{border-bottom:1px solid var(--border);padding:12px 0;display:flex;gap:10px;align-items:flex-start}
.sigit:last-child{border-bottom:none}
.sgico{width:34px;height:34px;border-radius:9px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:15px}
.iradar{background:rgba(68,138,255,.12);color:var(--blue)}.igatilho{background:rgba(0,229,255,.12);color:var(--cyan)}
.isinal{background:var(--g3);color:var(--green)}.ict{background:var(--y3);color:var(--gold)}
.iinsuf{background:var(--bg4);color:var(--muted2)}.iclose{background:var(--bg4);color:var(--muted2)}.icb{background:var(--r3);color:var(--red)}
.sgbody{flex:1;min-width:0}
.sgtipo{font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:3px}
.sgtxt{font-size:11px;color:var(--muted2);line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.sgts{font-size:9px;color:var(--muted);margin-top:4px;font-family:var(--mono)}
.ctc{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:8px;border-left:3px solid var(--gold)}
.cttop{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.ctsym{font-size:15px;font-weight:700;font-family:var(--mono)}
.ctsc{font-size:10px;font-family:var(--mono);font-weight:700;padding:4px 10px;border-radius:20px;background:var(--y3);color:var(--gold)}
.ctdir{font-size:11px;font-weight:600;margin-bottom:8px}
.ctsigs{display:flex;flex-wrap:wrap;gap:4px}
.ctag{font-size:9px;padding:3px 8px;border-radius:4px;background:var(--bg4);color:var(--muted2);border:1px solid var(--border)}
.ctm2{display:flex;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
.ctmb{text-align:center;flex:1}
.ctml{font-size:8px;color:var(--muted);letter-spacing:1px;text-transform:uppercase}
.ctmv{font-size:13px;font-family:var(--mono);font-weight:700;margin-top:2px}
.fgb{background:linear-gradient(135deg,var(--bg3),var(--bg4));border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;margin-bottom:12px;display:flex;align-items:center;justify-content:space-between}
.fgl{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);margin-bottom:4px}
.fgv{font-size:18px;font-weight:700}
.fgn{font-size:36px;font-weight:700;font-family:var(--mono);opacity:.15}
.ni2{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)}
.ni2:last-child{border-bottom:none}
.nnum{width:24px;height:24px;border-radius:6px;background:var(--bg4);display:flex;align-items:center;justify-content:center;font-size:10px;font-family:var(--mono);color:var(--muted2);flex-shrink:0;margin-top:1px}
.nbody{flex:1;min-width:0}
.ntitle{font-size:12px;line-height:1.5;color:var(--text);text-decoration:none;display:block}
.ntitle:hover{color:var(--cyan)}
.nsrc{font-size:9px;color:var(--muted2);margin-top:4px}
.cfgsec{margin-bottom:18px}
.cfgl{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);margin-bottom:10px}
.mdg{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.mdb{background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:12px 8px;cursor:pointer;font-size:12px;font-family:var(--sans);color:var(--text);text-align:center;transition:.15s;line-height:1.4;border:none}
.mdb:active{transform:scale(.97)}.mdb.on{background:var(--g3);border:1px solid var(--green);color:var(--green)}
.mdi{font-size:20px;display:block;margin-bottom:3px}
.tfg{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
.tfb{background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:10px 6px;cursor:pointer;font-size:11px;font-family:var(--mono);color:var(--text);text-align:center;transition:.15s;border:none}
.tfb.on{background:rgba(0,229,255,.1);border:1px solid var(--cyan);color:var(--cyan)}.tfb:active{transform:scale(.97)}
.tfd{font-size:14px;display:block;margin-bottom:2px}.tfl2{font-size:8px;color:var(--muted2);margin-top:1px}
.ab{width:100%;padding:15px;border-radius:var(--r);border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:var(--sans);margin-bottom:8px;transition:.15s;letter-spacing:.3px}
.ab:active{transform:scale(.98)}
.abd{background:var(--r3);color:var(--red);border:1px solid rgba(255,23,68,.2)}
.abp{background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.abn{background:rgba(68,138,255,.1);color:var(--blue);border:1px solid rgba(68,138,255,.2)}
.pgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pbox{background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:12px}
.plbl{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.pval{font-size:16px;font-family:var(--mono);font-weight:700}
.cbbar{background:var(--r3);border:1px solid rgba(255,23,68,.2);border-radius:var(--rsm);padding:10px 14px;margin-bottom:10px;display:none;align-items:center;justify-content:space-between}
.cbtxt{font-size:11px;color:var(--red);font-weight:600}.cbmin{font-size:18px;font-family:var(--mono);font-weight:700;color:var(--red)}
.eb{background:var(--r3);border:1px solid rgba(255,23,68,.2);border-radius:var(--rsm);padding:10px 12px;margin-bottom:10px;font-size:11px;color:var(--red);display:none}
.empty{text-align:center;padding:40px 20px;color:var(--muted)}
.empi{font-size:40px;margin-bottom:10px;display:block}
.empt{font-size:12px;line-height:1.6;color:var(--muted2)}
.ts{font-size:9px;color:var(--muted);text-align:center;padding:8px 0;letter-spacing:.5px;font-family:var(--mono)}
.dv{height:1px;background:var(--border);margin:14px 0}
.spin{animation:spin 1s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}
.sh{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.sttl{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);display:flex;align-items:center;gap:6px}
.rb{font-size:11px;color:var(--muted2);cursor:pointer;padding:2px 6px;border-radius:4px;border:1px solid var(--border);background:var(--bg3)}
.rb:active{opacity:.7}
.stab{flex:1;padding:10px;border:none;background:transparent;color:var(--muted2);font-size:12px;cursor:pointer;font-family:var(--sans);font-weight:600;transition:.15s}
.stab.on{color:var(--green)}
.ntf-banner{background:rgba(68,138,255,.08);border:1px solid rgba(68,138,255,.2);border-radius:var(--rsm);padding:12px 14px;margin-bottom:12px}
.ntf-ttl{font-size:11px;font-weight:600;color:var(--blue);margin-bottom:4px}
.ntf-txt{font-size:10px;color:var(--muted2);line-height:1.5}

/* ═══════════════════════════════════════════════════════════ */
/* MELHORIA 1: Card de Sinal com Copiar */
/* ═══════════════════════════════════════════════════════════ */
.action-card { background: var(--bg2); border: 2px solid var(--border); border-radius: var(--r); padding: 14px; margin-bottom: 10px; position: relative; overflow: hidden; transition: transform .15s; }
.action-card:active { transform: scale(.99); }
.action-card.buy  { border-color: rgba(0,230,118,.5); }
.action-card.sell { border-color: rgba(255,23,68,.4); }
.action-card.ct   { border-color: rgba(255,202,40,.4); }
.action-card .ac-stripe { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
.action-card.buy  .ac-stripe { background: var(--green); }
.action-card.sell .ac-stripe { background: var(--red); }
.action-card.ct   .ac-stripe { background: var(--gold); }
.ac-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; padding-left: 8px; }
.ac-symbol { font-size: 20px; font-weight: 700; font-family: var(--font-mono); }
.ac-dir { font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 20px; letter-spacing: .5px; }
.ac-dir.buy  { background: var(--g3); color: var(--green); }
.ac-dir.sell { background: var(--r3); color: var(--red); }
.ac-dir.ct   { background: var(--y3); color: var(--gold); }
.ac-levels { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; padding-left: 8px; margin-bottom: 10px; }
.ac-lv { background: var(--bg3); border-radius: var(--rsm); padding: 8px; text-align: center; }
.ac-ll { font-size: 8px; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); margin-bottom: 4px; }
.ac-lv-val { font-size: 13px; font-weight: 700; font-family: var(--font-mono); }
.ac-footer { display: flex; align-items: center; justify-content: space-between; padding-left: 8px; }
.ac-copy-btn { display: flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; padding: 7px 14px; border-radius: 8px; background: var(--bg3); border: 1px solid var(--border); cursor: pointer; color: var(--text-muted); transition: .15s; }
.ac-copy-btn:active { background: var(--border); transform: scale(.97); }
.ac-copy-btn.copied { color: var(--green); border-color: rgba(0,230,118,.4); }
.ac-tipo { font-size: 9px; letter-spacing: 1px; text-transform: uppercase; color: var(--muted); }

/* ═══════════════════════════════════════════════════════════ */
/* MELHORIA 2: Timer de Expiração */
/* ═══════════════════════════════════════════════════════════ */
.sig-timer { display: inline-flex; align-items: center; gap: 4px; font-size: 10px; font-family: var(--font-mono); font-weight: 600; padding: 3px 8px; border-radius: 20px; }
.sig-timer.fresh  { background: rgba(0,230,118,.15); color: var(--green); }
.sig-timer.aging  { background: rgba(255,202,40,.15); color: var(--gold); }
.sig-timer.old    { background: rgba(255,23,68,.12);  color: var(--red); }
.sig-timer.closed { background: var(--bg4); color: var(--muted); }

/* ═══════════════════════════════════════════════════════════ */
/* MELHORIA 3: Modo Apenas Sinais */
/* ═══════════════════════════════════════════════════════════ */
.simple-mode #hdr { display: none !important; }
.simple-mode #nav { display: none !important; }
.simple-mode .page { padding: 12px 12px 20px; }
.simple-mode #page-sig { display: block !important; }
.simple-mode .exit-simple { display: flex !important; }
.exit-simple { display: none; position: fixed; top: 12px; right: 12px; z-index: 9999; width: 36px; height: 36px; border-radius: 18px; background: var(--bg3); border: 1px solid var(--border); align-items: center; justify-content: center; cursor: pointer; font-size: 18px; box-shadow: 0 2px 12px rgba(0,0,0,.4); }
.simple-mode-header { display: none; padding: 16px 0 8px; }
.simple-mode .simple-mode-header { display: flex; align-items: center; justify-content: space-between; }

/* ═══════════════════════════════════════════════════════════ */
/* MELHORIA 4: Fila de Pendentes com Swipe */
/* ═══════════════════════════════════════════════════════════ */
.pending-section { margin-bottom: 14px; }
.pending-hdr { font-size: 9px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--muted2); margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; }
.pending-count { background: var(--bg4); border: 1px solid var(--border); border-radius: 20px; padding: 1px 8px; font-family: var(--font-mono); font-size: 10px; color: var(--muted2); }
.swipe-wrap { position: relative; overflow: hidden; border-radius: var(--rsm); margin-bottom: 6px; }
.swipe-behind { position: absolute; inset: 0; display: flex; align-items: center; border-radius: var(--rsm); }
.swipe-behind .ok  { flex: 1; background: rgba(0,230,118,.25); display: flex; align-items: center; padding-left: 18px; gap: 6px; font-size: 12px; font-weight: 600; color: var(--green); }
.swipe-behind .ng  { flex: 1; background: rgba(255,23,68,.18); display: flex; align-items: center; justify-content: flex-end; padding-right: 18px; gap: 6px; font-size: 12px; font-weight: 600; color: var(--red); }
.swipe-card { position: relative; background: var(--bg2); border: 1px solid var(--border); border-radius: var(--rsm); padding: 11px 14px; display: flex; align-items: center; gap: 10px; cursor: pointer; touch-action: pan-y; user-select: none; transition: transform .15s ease, opacity .2s; }
.swipe-card.done { opacity: 0; transform: translateX(110%); }
.swipe-card.skip { opacity: 0; transform: translateX(-110%); }
.swipe-card .sc-sym { font-size: 14px; font-weight: 700; font-family: var(--font-mono); flex-shrink: 0; }
.swipe-card .sc-info { flex: 1; min-width: 0; }
.swipe-card .sc-txt { font-size: 11px; color: var(--muted2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.swipe-card .sc-ts  { font-size: 9px; color: var(--muted); margin-top: 2px; }
.swipe-card .sc-act { display: flex; gap: 6px; }
.sc-btn { font-size: 11px; padding: 5px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg3); cursor: pointer; color: var(--text-muted); font-family: var(--font-sans); font-weight: 600; }
.sc-btn.ok  { background: rgba(0,230,118,.12); color: var(--green); border-color: rgba(0,230,118,.3); }
.sc-btn.nk  { background: rgba(255,23,68,.1);  color: var(--red);   border-color: rgba(255,23,68,.25); }
.sc-btn:active { transform: scale(.96); }
.empty-pending { text-align: center; padding: 14px; color: var(--muted); font-size: 12px; }
</style>
</head>
<body>
<div id="app">
<div id="hdr">
  <div class="hdr-l">
    <div class="logo">S</div>
    <div><div class="t1">Sniper Bot</div><div class="t2">Multi-Mercado v7.1</div></div>
  </div>
  <div class="hdr-r">
    <div class="lpill"><div class="ldot"></div>LIVE</div>
    <div class="ibtn" onclick="refreshAll()" id="refbtn">↻</div>
  </div>
</div>
<div id="pages">

<!-- ═══ DASHBOARD ═══ -->
<div class="pg on" id="pg-dash">
  <div class="eb" id="eb">⚠ Erro de conexão. Tente novamente.</div>
  <div class="cbbar" id="cbbar">
    <div><div class="cbtxt">⛔ CIRCUIT BREAKER</div><div style="font-size:10px;color:var(--red);margin-top:2px">Bot pausado</div></div>
    <div class="cbmin" id="cbmin">--m</div>
  </div>
  <div class="srow">
    <div class="sb"><div class="sl">Wins</div><div class="sv g" id="d-w">--</div><div class="ss" id="d-wr">--% WR</div></div>
    <div class="sb"><div class="sl">Losses</div><div class="sv r" id="d-l">--</div><div class="ss" id="d-sq">Seq --</div></div>
    <div class="sb"><div class="sl">Trades</div><div class="sv cy" id="d-t">--</div><div class="ss" id="d-mt">--</div></div>
  </div>
  <div class="sh"><div class="sttl">💼 Trades Abertos</div></div>
  <div id="d-trades"><div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto</div></div></div>
  <div class="sh" style="margin-top:14px"><div class="sttl">🌐 Mercados</div></div>
  <div class="mg" id="d-mkts"></div>
  <div class="ts" id="d-ts">--</div>
</div>

<!-- ═══ SCANNER ═══ -->
<div class="pg" id="pg-scan">
  <div class="sh"><div class="sttl">📡 Scanner Tempo Real</div><span class="rb" onclick="loadScanner()">↻</span></div>
  <div class="tbar">
    <span class="tbl">Alta</span><span class="tbc g" id="sc-a">--</span>
    <span style="color:var(--border);margin:0 6px">|</span>
    <span class="tbl">Baixa</span><span class="tbc r" id="sc-b">--</span>
    <span style="color:var(--border);margin:0 6px">|</span>
    <span class="tbl">Neutro</span><span class="tbc" style="color:var(--muted2)" id="sc-n">--</span>
  </div>
  <div class="fchips" id="sfil">
    <div class="fc on" data-cat="TODOS" onclick="setSF('TODOS',this)">Todos</div>
    <div class="fc" data-cat="ALTA" onclick="setSF('ALTA',this)">🟢 Alta</div>
    <div class="fc" data-cat="BAIXA" onclick="setSF('BAIXA',this)">🔴 Baixa</div>
    <div class="fc" data-cat="FOREX" onclick="setSF('FOREX',this)">📈 Forex</div>
    <div class="fc" data-cat="CRYPTO" onclick="setSF('CRYPTO',this)">₿ Cripto</div>
    <div class="fc" data-cat="COMMODITIES" onclick="setSF('COMMODITIES',this)">🏅 Comm.</div>
    <div class="fc" data-cat="INDICES" onclick="setSF('INDICES',this)">📊 Índices</div>
  </div>
  <div class="card" style="padding:4px 14px"><div id="scan-list"><div class="empty"><span class="empi">📡</span><div class="empt">Aguardando dados do scanner…</div></div></div></div>
</div>

<!-- ═══ SINAIS ═══ -->
<div class="pg" id="pg-sig">
  <!-- Melhoria 3: botão de saída do modo simples -->
  <div class="exit-simple" onclick="toggleSimpleMode(false)">✕</div>
  <div class="sh"><div class="sttl">🔔 Feed de Sinais</div><span class="rb" onclick="loadSigs()">↻</span></div>
  <!-- Melhoria 4: Fila de Pendentes -->
  <div class="pending-section">
    <div class="pending-hdr">⏳ Pendentes<span class="pending-count" id="pendingCount">0</span></div>
    <div id="pendingQueue"><div class="empty-pending">Nenhum pendente</div></div>
  </div>
  <div class="fchips" id="sigfil">
    <div class="fc on" data-sf="todos" onclick="setSigF('todos',this)">Todos</div>
    <div class="fc" data-sf="sinal" onclick="setSigF('sinal',this)">🎯 Sinal</div>
    <div class="fc" data-sf="gatilho" onclick="setSigF('gatilho',this)">🔔 Gatilho</div>
    <div class="fc" data-sf="radar" onclick="setSigF('radar',this)">⚠ Radar</div>
    <div class="fc" data-sf="ct" onclick="setSigF('ct',this)">⚡ CT</div>
    <div class="fc" data-sf="close" onclick="setSigF('close',this)">🏁 Fechados</div>
  </div>
  <div class="card" style="padding:0 14px"><div id="sig-list"><div class="empty"><span class="empi">🔔</span><div class="empt">Nenhum sinal ainda.<br>Aparecem aqui junto com o Telegram.</div></div></div></div>
</div>

<!-- ═══ CT / NEWS ═══ -->
<div class="pg" id="pg-ct">
  <div style="display:flex;gap:0;margin-bottom:14px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--r);overflow:hidden">
    <button class="stab on" id="st-ct" onclick="showSub('ct')">⚡ Contra-T</button>
    <button class="stab" id="st-nw" onclick="showSub('news')">📰 Notícias</button>
  </div>
  <div id="sub-ct">
    <div class="sh"><div class="sttl">⚡ Oportunidades CT (FOREX)</div><span class="rb" onclick="loadCT()">↻</span></div>
    <div style="background:var(--y3);border:1px solid rgba(255,202,40,.2);border-radius:var(--rsm);padding:10px 12px;margin-bottom:12px;font-size:11px;color:var(--gold);line-height:1.5">⚠️ Sinais <b>contra tendência</b> detectados no FOREX. Use gestão de risco reduzida.</div>
    <div id="ct-list"><div class="empty"><span class="empi">⚡</span><div class="empt">Nenhuma oportunidade CT detectada.</div></div></div>
  </div>
  <div id="sub-nw" style="display:none">
    <div class="sh"><div class="sttl">📰 Notícias</div><span class="rb" onclick="loadNews()">↻</span></div>
    <div class="fgb" id="fgb">
      <div><div class="fgl">Fear &amp; Greed</div><div class="fgv" id="fgv">--</div></div>
      <div class="fgn" id="fgn">--</div>
    </div>
    <div class="card" style="padding:0 14px"><div id="news-list"><div class="empty"><span class="empi">📰</span><div class="empt">Carregando…</div></div></div></div>
  </div>
</div>

<!-- ═══ CONFIG ═══ -->
<div class="pg" id="pg-cfg">
  <div class="cfgsec">
    <div class="cfgl">Mercado</div>
    <div class="mdg">
      <button class="mdb" data-mode="FOREX" onclick="setMode('FOREX')"><span class="mdi">📈</span>FOREX</button>
      <button class="mdb" data-mode="CRYPTO" onclick="setMode('CRYPTO')"><span class="mdi">₿</span>CRIPTO</button>
      <button class="mdb" data-mode="COMMODITIES" onclick="setMode('COMMODITIES')"><span class="mdi">🏅</span>COMMODITIES</button>
      <button class="mdb" data-mode="INDICES" onclick="setMode('INDICES')"><span class="mdi">📊</span>ÍNDICES</button>
    </div>
    <button class="mdb" style="width:100%;margin-top:7px;display:block;padding:12px" data-mode="TUDO" onclick="setMode('TUDO')">🌍 TUDO (42 ativos)</button>
  </div>
  <div class="cfgsec">
    <div class="cfgl">Timeframe</div>
    <div class="tfg">
      <button class="tfb" data-tf="1m" onclick="setTf('1m')"><span class="tfd r">●</span>1m<div class="tfl2">Agressivo</div></button>
      <button class="tfb" data-tf="5m" onclick="setTf('5m')"><span class="tfd or">●</span>5m<div class="tfl2">Alto</div></button>
      <button class="tfb" data-tf="15m" onclick="setTf('15m')"><span class="tfd go">●</span>15m<div class="tfl2">Moderado</div></button>
      <button class="tfb" data-tf="30m" onclick="setTf('30m')"><span class="tfd g">●</span>30m<div class="tfl2">Conservador</div></button>
      <button class="tfb" data-tf="1h" onclick="setTf('1h')"><span class="tfd cy">●</span>1h<div class="tfl2">Seguro</div></button>
      <button class="tfb" data-tf="4h" onclick="setTf('4h')"><span class="tfd bl">●</span>4h<div class="tfl2">Muito Seg.</div></button>
    </div>
  </div>
  <div class="dv"></div>
  <div class="cfgsec">
    <div class="cfgl">Notificações Push</div>
    <div class="ntf-banner" id="ntf-banner">
      <div class="ntf-ttl">🔔 Receba alertas mesmo com o app fechado</div>
      <div class="ntf-txt">Ative para receber notificações de sinais, gatilhos e encerramentos diretamente no seu celular.</div>
    </div>
    <button class="ab abn" id="ntf-btn" onclick="toggleNotifs()">🔔 Ativar Notificações Push</button>
    <div id="ntf-status" style="font-size:10px;color:var(--muted2);text-align:center;margin-top:4px"></div>
  </div>
  <div class="cfgsec">
    <div class="cfgl">Ações</div>
    <!-- Melhoria 3: Modo Apenas Sinais -->
    <button class="ab abn" id="simpleModeBtn" onclick="toggleSimpleMode(true)">🔔 Modo Apenas Sinais</button>
    <div style="font-size:10px;color:var(--muted2);text-align:center;margin-bottom:8px">Foco total nos sinais — ideal ao operar</div>
    <button class="ab abd" onclick="resetPausa()">⛔ Resetar Circuit Breaker</button>
    <button class="ab abp" onclick="refreshAll()">↻ Atualizar Agora</button>
  </div>
  <div class="cfgsec">
    <div class="cfgl">Parâmetros de Risco</div>
    <div class="pgrid">
      <div class="pbox"><div class="plbl">Stop Loss</div><div class="pval r" id="p-sl">--</div></div>
      <div class="pbox"><div class="plbl">Take Profit</div><div class="pval g" id="p-tp">--</div></div>
      <div class="pbox"><div class="plbl">Max Trades</div><div class="pval cy" id="p-mt">--</div></div>
      <div class="pbox"><div class="plbl">Confluência</div><div class="pval go" id="p-mc">--</div></div>
    </div>
  </div>
  <div class="card" style="background:rgba(0,229,255,.04);border-color:rgba(0,229,255,.15)">
    <div class="chd" style="color:var(--cyan)">📱 Instalar como App</div>
    <div style="font-size:11px;color:var(--muted2);line-height:1.7">Android Chrome: <b style="color:var(--text)">⋮ → Adicionar à tela inicial</b><br>APK gratuito: <b style="color:var(--cyan)">pwabuilder.com</b></div>
  </div>
</div>

</div>
<nav id="nav">
  <button class="nb on" onclick="goTo('dash',this)"><span class="ni">⬡</span>Dashboard</button>
  <button class="nb" onclick="goTo('scan',this)"><span class="ni">📡</span>Scanner</button>
  <button class="nb" id="nb-sig" onclick="goTo('sig',this)"><span class="ni">🔔</span>Sinais<span class="nbadge" id="nbadge">0</span></button>
  <button class="nb" onclick="goTo('ct',this)"><span class="ni">⚡</span>CT/News</button>
  <button class="nb" onclick="goTo('cfg',this)"><span class="ni">⚙</span>Config</button>
</nav>
</div>

<script>
let _st=null,_scan=[],_sigs=[],_sf='TODOS',_sigf='todos',_unread=0,_lastSigLen=0;

function fp(p){
  if(p===undefined||p===null)return'--';
  if(p>=10000)return p.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(p>=1000)return p.toFixed(2);if(p>=10)return p.toFixed(4);
  if(p>=1)return p.toFixed(5);return p.toFixed(6);
}
async function apiFetch(path,opts={}){
  const r=await fetch(path,{headers:{'Content-Type':'application/json'},mode:'same-origin',...opts});
  if(!r.ok)throw new Error(r.status);return r.json();
}
function goTo(pg,btn){
  document.querySelectorAll('.pg').forEach(p=>{ p.classList.remove('on'); p.style.display='none'; });
  document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));
  const target=document.getElementById('pg-'+pg);
  if(target){ target.classList.add('on'); target.style.display='block'; }
  btn.classList.add('on');
  if(pg==='scan')loadScanner();
  if(pg==='sig'){loadSigs();_unread=0;updBadge();}
  if(pg==='ct'){loadCT();loadNews();}
  if(pg==='cfg')loadCfg();
}
function showSub(s){
  document.getElementById('sub-ct').style.display=s==='ct'?'':'none';
  document.getElementById('sub-nw').style.display=s==='news'?'':'none';
  document.getElementById('st-ct').classList.toggle('on',s==='ct');
  document.getElementById('st-nw').classList.toggle('on',s==='news');
}
async function refreshAll(){
  const b=document.getElementById('refbtn');b.classList.add('spin');
  try{await loadDash();const a=document.querySelector('.pg.on');
    if(a.id==='pg-scan')await loadScanner();
    if(a.id==='pg-sig')await loadSigs();
  }finally{b.classList.remove('spin');}
}
async function loadDash(){
  try{
    _st=await apiFetch('/api/status');
    document.getElementById('eb').style.display='none';
    document.getElementById('d-w').textContent=_st.wins;
    document.getElementById('d-l').textContent=_st.losses;
    document.getElementById('d-wr').textContent=_st.winrate+'% WR';
    document.getElementById('d-sq').textContent='Seq: '+_st.consecutive_losses;
    document.getElementById('d-t').textContent=_st.active_trades.length+'/3';
    document.getElementById('d-mt').textContent=_st.mode+' '+_st.timeframe;
    const cb=document.getElementById('cbbar');
    if(_st.paused){cb.style.display='flex';document.getElementById('cbmin').textContent=_st.cb_mins+'min';}
    else cb.style.display='none';
    document.getElementById('d-trades').innerHTML=_st.active_trades.length?_st.active_trades.map(renderTC).join(''):'<div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto</div></div>';
    const mn={FOREX:'📈 FOREX',CRYPTO:'₿ Cripto',COMMODITIES:'🏅 Commodities',INDICES:'📊 Índices'};
    document.getElementById('d-mkts').innerHTML=Object.entries(_st.markets).map(([k,v])=>`<div class="mkt"><span class="mktn">${mn[k]||k}</span><span class="mkts ${v?'mop':'mcl'}">${v?'Aberto':'Fechado'}</span></div>`).join('');
    document.getElementById('d-ts').textContent='Atualizado '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
    updCfgBtns();
  }catch(e){document.getElementById('eb').style.display='block';}
}
function renderTC(t){
  const ct=(t.tipo||'').includes('CONTRA'),buy=t.dir==='BUY',pos=t.pnl>=0;
  const cls=ct?(buy?'ctb':'cts'):(buy?'buy':'sell');
  const dc=buy?'dbu':'dbs'; const pct=Math.min(Math.abs(t.pnl)/3*100,100);
  return`<div class="tc ${cls}"><div class="tc-top">
    <div><div class="tc-sym">${t.symbol}${ct?'<span style="font-size:9px;background:var(--y3);color:var(--gold);padding:1px 5px;border-radius:3px;margin-left:5px;vertical-align:middle">CT</span>':''}</div><div class="tc-nm">${t.name||''} · ${t.opened_at||''}</div></div>
    <div class="db ${dc}">${buy?'▲ BUY':'▼ SELL'}</div></div>
    <div class="lvls">
      <div class="lv"><div class="lvl">Entrada</div><div class="lvv">${fp(t.entry)}</div></div>
      <div class="lv"><div class="lvl">SL 🛡</div><div class="lvv r">${fp(t.sl)}</div></div>
      <div class="lv"><div class="lvl">TP 🎯</div><div class="lvv g">${fp(t.tp)}</div></div>
    </div>
    <div class="tcft"><div class="pnl ${pos?'g':'r'}">${t.pnl>=0?'+':''}${t.pnl.toFixed(2)}%</div><div class="tcm">Atual: ${fp(t.current)}</div></div>
    <div class="pbar"><div class="pbar-f ${pos?'pg-fill':'pr-fill'}" style="width:${pct}%"></div></div>
  </div>`;
}
async function loadScanner(){
  try{
    _scan=await apiFetch('/api/trends');
    const a=_scan.filter(x=>x.cenario==='ALTA').length,b=_scan.filter(x=>x.cenario==='BAIXA').length,n=_scan.filter(x=>!x.cenario||x.cenario==='NEUTRO').length;
    document.getElementById('sc-a').textContent=a;document.getElementById('sc-b').textContent=b;document.getElementById('sc-n').textContent=n;
    let data=[..._scan];
    if(_sf==='ALTA')data=data.filter(x=>x.cenario==='ALTA');
    else if(_sf==='BAIXA')data=data.filter(x=>x.cenario==='BAIXA');
    else if(['FOREX','CRYPTO','COMMODITIES','INDICES'].includes(_sf))data=data.filter(x=>x.category===_sf);
    data.sort((a,b)=>({ALTA:0,BAIXA:1,NEUTRO:2}[a.cenario]??2)-({ALTA:0,BAIXA:1,NEUTRO:2}[b.cenario]??2));
    if(!data.length){document.getElementById('scan-list').innerHTML='<div class="empty"><span class="empi">🔍</span><div class="empt">Nenhum ativo neste filtro.</div></div>';return;}
    document.getElementById('scan-list').innerHTML=data.map(x=>{
      const t=x.cenario||'NEUTRO',ic=t==='ALTA'?'↑':t==='BAIXA'?'↓':'–',icc=t==='ALTA'?'siA':t==='BAIXA'?'siB':'siN';
      const rc=x.rsi>70?'tr':x.rsi<30?'tg':'tn',ac=x.adx>25?'tg':'tn';
      const chgC=x.change_pct>0?'g':x.change_pct<0?'r':'';
      return`<div class="si"><div class="sico ${icc}">${ic}</div>
        <div class="sinf"><div class="ssym">${x.symbol}</div><div class="snm">${x.name||''} · ${x.category||''}</div></div>
        <div class="srgt"><div class="spr">${fp(x.price)}</div>
        <div class="stags"><span class="tag ${chgC?'t'+chgC:'tn'}">${x.change_pct>=0?'+':''}${x.change_pct.toFixed(2)}%</span><span class="tag ${rc}">RSI ${x.rsi.toFixed(0)}</span><span class="tag ${ac}">ADX ${x.adx.toFixed(0)}</span></div></div>
      </div>`;
    }).join('');
  }catch(e){document.getElementById('scan-list').innerHTML='<div class="empty"><span class="empi">⚠</span><div class="empt">Erro ao carregar</div></div>';}
}
function setSF(cat,el){document.querySelectorAll('[data-cat]').forEach(c=>c.classList.remove('on'));el.classList.add('on');_sf=cat;loadScanner();}
async function loadSigs(){
  try{
    const d=await apiFetch('/api/signals');
    // Detectar novos e adicionar à fila de pendentes
    if(d.length>_lastSigLen){
      const novos=d.slice(0, d.length-_lastSigLen);
      novos.forEach(s=>addToPending(s));
      _unread+=d.length-_lastSigLen;
      updBadge();
    }
    _lastSigLen=d.length;_sigs=d;renderSigs();
  }catch(e){}
}
function setSigF(f,el){document.querySelectorAll('[data-sf]').forEach(x=>x.classList.remove('on'));el.classList.add('on');_sigf=f;renderSigs();}
const SM={radar:{icon:'⚠',cls:'iradar',lbl:'RADAR',c:'var(--blue)'},gatilho:{icon:'🔔',cls:'igatilho',lbl:'GATILHO',c:'var(--cyan)'},sinal:{icon:'🎯',cls:'isinal',lbl:'SINAL',c:'var(--green)'},ct:{icon:'⚡',cls:'ict',lbl:'CONTRA-T',c:'var(--gold)'},insuf:{icon:'❌',cls:'iinsuf',lbl:'INSUF.',c:'var(--muted2)'},close:{icon:'🏁',cls:'iclose',lbl:'FECHADO',c:'var(--muted2)'},cb:{icon:'⛔',cls:'icb',lbl:'CIRCUIT BR.',c:'var(--red)'}};
/* ── MELHORIA 2: timer de expiração ── */
function sigTimer(ts){
  try{const parts=ts.split(' ');const[d,m]=parts[0].split('/');const[hh,mm]=parts[1].split(':');
    const now=new Date();const sig=new Date(now.getFullYear(),+m-1,+d,+hh,+mm);
    const mins=Math.floor((now-sig)/60000);
    if(mins<0||mins>1440)return{cls:'closed',txt:''};
    if(mins<15)return{cls:'fresh',txt:mins+'m'};
    if(mins<60)return{cls:'aging',txt:mins+'m'};
    return{cls:'old',txt:Math.floor(mins/60)+'h'+(mins%60?mins%60+'m':'')};
  }catch(e){return{cls:'closed',txt:''};}}

/* ── MELHORIA 1: card de sinal com botão copiar ── */
function renderSignalCard(s,m){
  const timer=sigTimer(s.ts);
  const timerHtml=timer.txt?`<span class="sig-timer ${timer.cls}">⏱ ${timer.txt}</span>`:'';
  if(['sinal','gatilho','ct'].includes(s.tipo)){
    const isBuy=s.texto.includes('BUY')||s.texto.includes('COMPRAR');
    const isSell=s.texto.includes('SELL')||s.texto.includes('VENDER');
    const dir=s.tipo==='ct'?'ct':isBuy?'buy':isSell?'sell':'';
    const dirLabel=s.tipo==='ct'?'⚡ CT':isBuy?'▲ BUY':'▼ SELL';
    const sym=s.texto.match(/[A-Z]{2,8}[-=^]?[A-Z0-9]*/)?.[0]||'';
    const uid='cp'+Math.random().toString(36).slice(2,7);
    const copyTxt=s.texto;
    return `<div class="action-card ${dir}" style="margin-bottom:10px">
      <div class="ac-stripe"></div>
      <div class="ac-header">
        <div class="ac-symbol">${sym} <span class="ac-tipo">${m.lbl}</span></div>
        <div style="display:flex;align-items:center;gap:6px">
          ${timerHtml}
          ${dir?`<span class="ac-dir ${dir}">${dirLabel}</span>`:''}
        </div>
      </div>
      <div class="sgtxt" style="padding:0 0 10px 8px">${s.texto}</div>
      <div class="ac-footer">
        <span class="sgts">${s.ts}</span>
        <button class="ac-copy-btn" id="${uid}"
          onclick="(function(id,txt){navigator.clipboard.writeText(txt).then(()=>{const b=document.getElementById(id);if(b){b.textContent='✅ Copiado!';b.classList.add('copied');setTimeout(()=>{b.textContent='📋 Copiar';b.classList.remove('copied');},2000);}}).catch(()=>alert(txt));}('${uid}',\`${copyTxt.replace(/`/g,"'").replace(/\n/g,'\\n')}\`))">📋 Copiar</button>
      </div>
    </div>`;}
  return `<div class="sigit"><div class="sgico ${m.cls}">${m.icon}</div><div class="sgbody"><div class="sgtipo" style="color:${m.c}">${m.lbl} ${timerHtml}</div><div class="sgtxt">${s.texto}</div><div class="sgts">${s.ts}</div></div></div>`;}

function renderSigs(){
  let d=[..._sigs];if(_sigf!=='todos')d=d.filter(x=>x.tipo===_sigf);
  const el=document.getElementById('sig-list');
  if(!d.length){el.innerHTML='<div class="empty"><span class="empi">🔔</span><div class="empt">Nenhum sinal neste filtro.</div></div>';return;}
  el.innerHTML=d.map(s=>{const m=SM[s.tipo]||SM.radar;return renderSignalCard(s,m);}).join('');}
function updBadge(){const b=document.getElementById('nbadge');if(_unread>0){b.style.display='flex';b.textContent=_unread>9?'9+':_unread;}else b.style.display='none';}
async function loadCT(){
  const el=document.getElementById('ct-list');
  el.innerHTML='<div class="empty"><span class="empi spin">⚡</span><div class="empt">Analisando…</div></div>';
  try{
    const d=await apiFetch('/api/reversals');
    if(!d.length){el.innerHTML='<div class="empty"><span class="empi">⚡</span><div class="empt">Nenhuma oportunidade CT detectada.</div></div>';return;}
    el.innerHTML=d.map(x=>{const buy=x.direction==='BUY';return`<div class="ctc">
      <div class="cttop"><span class="ctsym">${x.symbol} <span style="font-size:10px;color:var(--muted2)">${x.name}</span></span><span class="ctsc">${x.strength}%</span></div>
      <div class="ctdir ${buy?'g':'r'}">${buy?'▲ COMPRAR':'▼ VENDER'} — ${buy?'Baixa→Alta':'Alta→Baixa'}</div>
      <div class="ctsigs">${(x.reasons||[]).map(s=>`<span class="ctag">${s}</span>`).join('')}</div>
      <div class="ctm2">
        <div class="ctmb"><div class="ctml">Preço</div><div class="ctmv">${fp(x.price)}</div></div>
        <div class="ctmb"><div class="ctml">RSI</div><div class="ctmv ${x.rsi>70?'r':x.rsi<30?'g':''}">${x.rsi.toFixed(1)}</div></div>
        <div class="ctmb"><div class="ctml">Força</div><div class="ctmv go">${x.strength}%</div></div>
      </div></div>`;}).join('');
  }catch(e){el.innerHTML='<div class="empty"><span class="empi">⚠</span><div class="empt">Erro ao carregar</div></div>';}
}
async function loadNews(){
  const el=document.getElementById('news-list');
  try{
    const d=await apiFetch('/api/news');
    const fg=d.fg,arts=d.articles||[];
    if(fg){
      document.getElementById('fgv').textContent=fg.value+' – '+fg.label;
      const n=parseInt(fg.value)||0;
      document.getElementById('fgn').textContent=n;
      document.getElementById('fgv').style.color=n>60?'var(--green)':n<40?'var(--red)':'var(--gold)';
    }
    if(!arts.length){el.innerHTML='<div class="empty"><span class="empi">📰</span><div class="empt">Sem notícias.</div></div>';return;}
    el.innerHTML=arts.map((a,i)=>`<div class="ni2"><div class="nnum">${i+1}</div><div class="nbody"><a class="ntitle" href="${a.url||'#'}" target="_blank">${a.title||''}</a><div class="nsrc">${a.source||''}</div></div></div>`).join('');
  }catch(e){el.innerHTML='<div class="empty"><span class="empi">⚠</span><div class="empt">Erro ao carregar</div></div>';}
}
async function loadCfg(){
  try{
    const c=await apiFetch('/api/config');
    document.getElementById('p-sl').textContent=c.atm_sl+'×ATR';
    document.getElementById('p-tp').textContent=c.atr_tp+'×ATR';
    document.getElementById('p-mt').textContent=c.max_trades;
    document.getElementById('p-mc').textContent=c.min_conf+'/7';
  }catch(_){}
  updCfgBtns();updNtfBtn();
}
function updCfgBtns(){
  if(!_st)return;
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('on',b.dataset.mode===_st.mode));
  document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('on',b.dataset.tf===_st.timeframe));
}
async function setMode(m){try{await apiFetch('/api/mode',{method:'POST',body:JSON.stringify({mode:m})});await loadDash();}catch(e){alert('Erro: '+e.message);}}
async function setTf(t){try{await apiFetch('/api/timeframe',{method:'POST',body:JSON.stringify({timeframe:t})});await loadDash();}catch(e){alert('Erro: '+e.message);}}
async function resetPausa(){if(!confirm('Resetar Circuit Breaker?'))return;try{await apiFetch('/api/resetpausa',{method:'POST'});await loadDash();}catch(e){alert('Erro: '+e.message);}}

/* ── Push Notifications ───────────────────────────────────── */
let _swReg = null;
async function initSW(){
  if(!('serviceWorker' in navigator)||!('PushManager' in window))return;
  try{
    _swReg = await navigator.serviceWorker.register('/sw.js');
    log('SW registrado');
  }catch(e){console.warn('SW:',e);}
}
function log(m){console.log('[SniperBot]',m);}
async function toggleNotifs(){
  if(!('Notification' in window)){alert('Seu navegador não suporta notificações.');return;}
  if(Notification.permission==='denied'){alert('Notificações bloqueadas. Habilite nas configurações do navegador.');return;}
  if(Notification.permission==='granted'){
    await subscribeUser(); return;
  }
  const perm = await Notification.requestPermission();
  if(perm==='granted') await subscribeUser();
  updNtfBtn();
}
async function subscribeUser(){
  if(!_swReg){alert('Service worker não disponível.');return;}
  try{
    const r = await apiFetch('/api/vapid-public-key');
    if(!r.key){alert('VAPID não configurado no servidor.\nAdicione VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY nas variáveis de ambiente do Railway.');return;}
    const sub = await _swReg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(r.key)
    });
    await apiFetch('/api/subscribe',{method:'POST',body:JSON.stringify(sub)});
    document.getElementById('ntf-status').textContent='✅ Notificações ativadas!';
    document.getElementById('ntf-btn').textContent='🔕 Desativar Notificações';
  }catch(e){document.getElementById('ntf-status').textContent='Erro: '+e.message;}
  updNtfBtn();
}
function updNtfBtn(){
  const btn=document.getElementById('ntf-btn'),st=document.getElementById('ntf-status');
  if(!('Notification' in window)||!('PushManager' in window)){
    btn.textContent='❌ Push não suportado neste navegador';btn.disabled=true;return;
  }
  if(Notification.permission==='denied'){btn.textContent='🚫 Notificações bloqueadas';btn.disabled=true;return;}
  if(Notification.permission==='granted')btn.textContent='✅ Notificações Ativas – Toque para reativar';
  else btn.textContent='🔔 Ativar Notificações Push';
  btn.disabled=false;
}
function urlBase64ToUint8Array(base64String){
  const padding='='.repeat((4-base64String.length%4)%4);
  const base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');
  const raw=window.atob(base64);const out=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out;
}

/* ── Init ─────────────────────────────────────────────────── */
/* Manifest dinâmico */
const mf={name:'Sniper Bot',short_name:'SniperBot',start_url:'/',display:'standalone',orientation:'portrait',background_color:'#06090f',theme_color:'#06090f',
icons:[{src:'/icon-192.png',sizes:'192x192',type:'image/png',purpose:'any maskable'},{src:'/icon-512.png',sizes:'512x512',type:'image/png',purpose:'any maskable'}]};
const mfBlob=new Blob([JSON.stringify(mf)],{type:'application/json'});
const mfLink=document.createElement('link');mfLink.rel='manifest';mfLink.href=URL.createObjectURL(mfBlob);document.head.appendChild(mfLink);


/* ── MELHORIA 3: Modo Apenas Sinais ── */
function toggleSimpleMode(on){
  document.body.classList.toggle('simple-mode',on);
  document.querySelectorAll('.pg').forEach(p=>{p.style.display='none';p.classList.remove('on');});
  if(on){
    const sig=document.getElementById('pg-sig');
    if(sig){sig.style.display='block';sig.classList.add('on');}
    document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));
    loadSigs();
    localStorage.setItem('sniper_simple','1');
  } else {
    const dash=document.getElementById('pg-dash');
    if(dash){dash.style.display='block';dash.classList.add('on');}
    const nb0=document.querySelector('.nb');
    if(nb0){document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));nb0.classList.add('on');}
    localStorage.removeItem('sniper_simple');
    loadDash();
  }
}

/* ── MELHORIA 4: Fila de Pendentes com Swipe ── */
let _pending=[];
function renderPending(){
  const el=document.getElementById('pendingQueue');
  const cnt=document.getElementById('pendingCount');
  if(!el||!cnt)return;
  const active=_pending.filter(p=>!p.done&&!p.skipped);
  cnt.textContent=active.length;
  if(!active.length){el.innerHTML='<div class="empty-pending">Nenhum pendente</div>';return;}
  el.innerHTML=active.map(p=>{
    const m=SM[p.tipo]||SM.radar;
    const sym=p.texto.match(/[A-Z]{2,8}[-=^]?[A-Z0-9]*/)?.[0]||'';
    const clr=p.tipo==='sinal'?'var(--green)':p.tipo==='ct'?'var(--gold)':'var(--cyan)';
    return `<div class="swipe-wrap" id="sw_${p.id}">
      <div class="swipe-behind"><div class="ok">✅ Executado</div><div class="ng">❌ Ignorar</div></div>
      <div class="swipe-card" id="sc_${p.id}">
        <span class="sc-sym" style="color:${clr}">${m.icon}</span>
        <div class="sc-info">
          <div style="font-size:12px;font-weight:700;font-family:var(--mono)">${sym} <span style="font-size:9px;color:var(--muted2)">${m.lbl}</span></div>
          <div class="sc-txt">${p.texto.split('\n')[1]||p.texto.split('\n')[0]}</div>
          <div class="sc-ts">${p.ts}</div>
        </div>
        <div class="sc-act">
          <button class="sc-btn ok" onclick="pendingAction('${p.id}',true)">✅</button>
          <button class="sc-btn nk" onclick="pendingAction('${p.id}',false)">❌</button>
        </div>
      </div></div>`;
  }).join('');
  active.forEach(p=>initSwipe(p.id));
}
function pendingAction(id,exec){
  const p=_pending.find(x=>x.id===id);if(!p)return;
  p.done=exec;p.skipped=!exec;
  const card=document.getElementById('sc_'+id);
  if(card){card.classList.add(exec?'done':'skip');setTimeout(()=>renderPending(),300);}
  savePending();
}
function initSwipe(id){
  const card=document.getElementById('sc_'+id);if(!card)return;
  let sx=0,cx=0,drag=false;
  card.addEventListener('touchstart',e=>{sx=e.touches[0].clientX;drag=true;},{passive:true});
  card.addEventListener('touchmove',e=>{if(!drag)return;cx=e.touches[0].clientX-sx;card.style.transform=`translateX(${cx}px)`;card.style.transition='none';},{passive:true});
  card.addEventListener('touchend',()=>{drag=false;card.style.transition='';
    if(cx>60)pendingAction(id,true);else if(cx<-60)pendingAction(id,false);else card.style.transform='';cx=0;});
}
function savePending(){try{localStorage.setItem('sniper_pending',JSON.stringify(_pending.slice(-20)));}catch(e){}}
function loadPendingData(){
  try{const s=localStorage.getItem('sniper_pending');if(s){_pending=JSON.parse(s);renderPending();}}catch(e){_pending=[];}
}
function addToPending(sig){
  if(!['sinal','gatilho','ct'].includes(sig.tipo))return;
  const id=(sig.ts+sig.texto).replace(/\W/g,'').slice(0,20);
  if(_pending.find(p=>p.id===id))return;
  _pending.unshift({...sig,id,done:false,skipped:false});
  _pending=_pending.slice(0,10);
  savePending();renderPending();
}
/* Atualizar timers e pendentes a cada minuto */
setInterval(()=>{renderSigs();renderPending();},60000);

window.addEventListener('load',()=>{
  // Restaurar modo simples e pendentes
  if(localStorage.getItem('sniper_simple')==='1') toggleSimpleMode(true);
  loadPendingData();
  initSW();
  // Forçar display correto em todas as pages na carga
  document.querySelectorAll('.pg').forEach(p=>{ p.style.display=p.classList.contains('on')?'block':'none'; });
  loadDash();
  setInterval(()=>{loadDash();loadSigs();},30000);
});
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
# FLASK API
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
        # Ícone SVG inline convertido para resposta
        size = 192 if "192" in request.path else 512
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" rx="{size//6}" fill="#06090f"/><text x="{size//2}" y="{int(size*.72)}" font-size="{int(size*.55)}" text-anchor="middle" fill="#00e676" font-family="monospace" font-weight="700">S</text></svg>'
        return Response(svg, mimetype="image/svg+xml")

    @app.route("/api/health")
    def api_health(): return jsonify({"status": "ok", "version": "7.1"})

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
        return jsonify({
            "wins": bot.wins, "losses": bot.losses, "winrate": wr,
            "consecutive_losses": bot.consecutive_losses, "mode": bot.mode, "timeframe": bot.timeframe,
            "paused": bot.is_paused(), "cb_mins": max(0,int((bot.paused_until-time.time())/60)) if bot.is_paused() else 0,
            "active_trades": trades_out,
            "markets": {cat: mkt_open(cat) for cat in Config.MARKET_CATEGORIES.keys()},
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
# LOOP DO BOT (thread separada)
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
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    log("🔌 Bot Sniper v7.1 — All-in-One + Push Notifications")
    try: requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=8)
    except: pass

    bot = TradingBot()
    load_state(bot)

    t = threading.Thread(target=bot_loop, args=(bot,), daemon=True)
    t.start()

    run_api(bot)   # Flask na thread principal (Railway exige)


if __name__ == "__main__":
    main()
