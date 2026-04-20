# -*- coding: utf-8 -*-
"""
BOT SNIPER v7.3 PRO — Tendências em Tempo Real + Cópia Individual SL/TP + Calculadora de Risco
═══════════════════════════════════════════════════════════════════════════════
MELHORIAS APLICADAS:
✅ Aba "📈 Tendências" com atualização automática (10s)
✅ Botões "📋 SL" e "📋 TP" independentes nas operações pendentes
✅ Aba "🧮 Calculadora de Risco" (client-side, instantânea)
✅ Layout mobile-first otimizado, badges dinâmicos, feedback visual
✅ API /api/trends integrada ao cache do bot
✅ Persistência e reconexão estáveis
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
        "FOREX": {"label": "FOREX", "assets": {
            "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
            "USDCAD": "USD/CAD", "USDCHF": "USD/CHF", "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
            "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY"}},
        "CRYPTO": {"label": "CRIPTO", "assets": {
            "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana", "BNB-USD": "BNB",
            "XRP-USD": "XRP", "ADA-USD": "Cardano", "DOGE-USD": "Dogecoin", "AVAX-USD": "Avalanche",
            "LINK-USD": "Chainlink", "DOT-USD": "Polkadot", "POL-USD": "Polygon", "LTC-USD": "Litecoin"}},
        "COMMODITIES": {"label": "COMMODITIES", "assets": {
            "GC=F": "Ouro", "SI=F": "Prata", "CL=F": "Petróleo WTI", "BZ=F": "Petróleo Brent",
            "NG=F": "Gás Natural", "HG=F": "Cobre", "ZC=F": "Milho", "ZW=F": "Trigo",
            "ZS=F": "Soja", "PL=F": "Platina"}},
        "INDICES": {"label": "ÍNDICES", "assets": {
            "ES=F": "S&P 500", "NQ=F": "Nasdaq 100", "YM=F": "Dow Jones", "RTY=F": "Russell 2000",
            "^GDAXI": "DAX", "^FTSE": "FTSE 100", "^N225": "Nikkei", "^BVSP": "IBOVESPA",
            "^HSI": "Hang Seng", "^STOXX50E": "Euro Stoxx 50"}}
    }

    ATR_MULT_SL = 1.5
    ATR_MULT_TP = 3.0
    ATR_MULT_TRAIL = 1.2
    MAX_CONSECUTIVE_LOSSES = 2
    PAUSE_DURATION = 3600
    ADX_MIN = 22
    MAX_TRADES = 3
    ASSET_COOLDOWN = 3600
    MIN_CONFLUENCE = 5
    MIN_CONFLUENCE_CT = 4
    REVERSAL_COOLDOWN = 2700
    RADAR_COOLDOWN = 1800
    GATILHO_COOLDOWN = 300
    TRENDS_INTERVAL = 120
    NEWS_INTERVAL = 7200
    SCAN_INTERVAL = 30

    TIMEFRAMES = {
        "1m": ("Agressivo", "7d"), "5m": ("Alto", "5d"), "15m": ("Moderado", "5d"),
        "30m": ("Conservador", "5d"), "1h": ("Seguro", "60d"), "4h": ("Muito Seguro", "60d")
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
    if cat == "COMMODITIES": return Config.COMM_OPEN_UTC <= h < Config.COMM_CLOSE_UTC
    if cat == "INDICES":     return Config.IDX_OPEN_UTC <= h < Config.IDX_CLOSE_UTC
    return True

# ═══════════════════════════════════════════════════════════════
# PERSISTÊNCIA
# ═══════════════════════════════════════════════════════════════
def save_state(bot):
    data = {
        "mode": bot.mode, "timeframe": bot.timeframe,
        "wins": bot.wins, "losses": bot.losses, "consecutive_losses": bot.consecutive_losses,
        "paused_until": bot.paused_until, "active_trades": bot.active_trades,
        "pending_operations": bot.pending_operations, "radar_list": bot.radar_list,
        "gatilho_list": bot.gatilho_list, "reversal_list": bot.reversal_list,
        "asset_cooldown": bot.asset_cooldown, "history": bot.history,
    }
    try:
        with open(Config.STATE_FILE, "w") as f: json.dump(data, f, indent=2)
    except Exception as e: log(f"[STATE] {e}")

def load_state(bot):
    if not os.path.exists(Config.STATE_FILE): return
    try:
        with open(Config.STATE_FILE) as f: data = json.load(f)
        bot.mode = data.get("mode", "CRYPTO")
        bot.timeframe = data.get("timeframe", Config.TIMEFRAME)
        bot.wins = data.get("wins", 0)
        bot.losses = data.get("losses", 0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until = data.get("paused_until", 0)
        bot.active_trades = data.get("active_trades", [])
        bot.pending_operations = data.get("pending_operations", [])
        bot.radar_list = data.get("radar_list", {})
        bot.gatilho_list = data.get("gatilho_list", {})
        bot.reversal_list = data.get("reversal_list", {})
        bot.asset_cooldown = data.get("asset_cooldown", {})
        bot.history = data.get("history", [])
        for t in bot.active_trades: t["session_alerted"] = False
        pend_count = len([o for o in bot.pending_operations if o["status"] == "PENDING"])
        log(f"[STATE] {bot.wins}W/{bot.losses}L | {len(bot.active_trades)} trade(s) | {pend_count} pendente(s)")
        bot._restore_msg = None
        if bot.active_trades or pend_count > 0:
            lines = ["♻️ BOT REINICIADO\n"]
            if bot.active_trades:
                for t in bot.active_trades:
                    dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                    lines.append(f"📌 {t['symbol']} {dl} | Entrada: `{fmt(t['entry'])}` | TP: `{fmt(t['tp'])}` | SL: `{fmt(t['sl'])}`")
            if pend_count > 0:
                lines.append(f"⏳ {pend_count} operação(ões) pendente(s) aguardando confirmação.")
            bot._restore_msg = "\n".join(lines)
    except Exception as e: log(f"[STATE] Erro: {e}")

# ═══════════════════════════════════════════════════════════════
# NOTÍCIAS / FEAR & GREED
# ═══════════════════════════════════════════════════════════════
RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Yahoo Finance", "https://finance.yahoo.com/rss/topfinstories"),
]

def _parse_rss(url, src, mx=3):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        out = []
        for item in items[:mx]:
            title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or " ").strip()
            link = (item.findtext("link") or item.findtext("{http://www.w3.org/2005/Atom}link") or " ").strip()
            if title and link: out.append({"title": title, "url": link, "source": src})
        return out
    except: return []

def get_news(mx=15):
    arts = []
    for name, url in RSS_FEEDS:
        if len(arts) >= mx: break
        try: arts.extend(_parse_rss(url, name, 4))
        except: pass
    return arts[:mx]

def get_fear_greed():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6).json()["data"][0]
        return {"value": d["value"], "label": d["value_classification"]}
    except: return {"value": "N/D", "label": ""}

def build_news_msg():
    arts = get_news(5); fg = get_fear_greed()
    lines = ["📰 NOTÍCIAS\n"]
    for i, a in enumerate(arts, 1):
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else " ")
        lines.append(f"{i}. <a href='{a['url']}' >{t} ({a['source']})")
    lines.append(f"\n😱 F&G: {fg['value']} – {fg['label']}")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
# MOTOR DE ANÁLISE PRINCIPAL
# ═══════════════════════════════════════════════════════════════
def get_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, (" ", "5d"))[1]
    use_vol = vol_reliable(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 50: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]; volume = df["Volume"]
        ema9 = closes.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]
        w = min(20, len(closes)-1)
        sma20 = closes.rolling(w).mean().iloc[-1]; std20 = closes.rolling(w).std().iloc[-1]
        upper = sma20 + std20 * 2; lower = sma20 - std20 * 2
        delta = closes.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = (100 - 100/(1 + gain/loss)).iloc[-1]
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        ml = ema12 - ema26; mh = ml - ml.ewm(span=9, adjust=False).mean()
        macd_bull = bool(mh.iloc[-1] > 0 and mh.iloc[-1] > mh.iloc[-2])
        macd_bear = bool(mh.iloc[-1] < 0 and mh.iloc[-1] < mh.iloc[-2])
        if use_vol and volume.sum() > 0:
            va = volume.rolling(20).mean().iloc[-1]; vc = volume.iloc[-1]
            vol_ok = bool(vc > va) if va > 0 else False; vol_ratio = float(vc/va) if va > 0 else 0
        else: vol_ok = True; vol_ratio = 0
        tr = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd > 0) & (hd > -ld), 0.0)
        mdm = (-ld).where((-ld > 0) & (-ld > hd), 0.0)
        as_ = tr.ewm(alpha=1/14, adjust=False).mean()
        pdi = 100 * pdm.ewm(alpha=1/14, adjust=False).mean() / (as_+1e-10)
        mdi = 100 * mdm.ewm(alpha=1/14, adjust=False).mean() / (as_+1e-10)
        dx = 100*(pdi-mdi).abs()/(pdi+mdi+1e-10)
        adx = float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
        price = float(closes.iloc[-1])
        chg = float((closes.iloc[-1]-closes.iloc[-10])/closes.iloc[-10]*100) if len(closes) >= 10 else 0
        cen = "NEUTRO"
        if price > ema200 and ema9 > ema21: cen = "ALTA"
        elif price < ema200 and ema9 < ema21: cen = "BAIXA"
        h1b = h1r = False
        sup_tf = "1h" if timeframe in ("1m","5m","15m","30m") else "1d"
        sup_per = "60d" if sup_tf == "1h" else "2y"
        try:
            dh = yf.Ticker(yf_symbol).history(period=sup_per, interval=sup_tf)
            if len(dh) >= 50:
                ch = dh["Close"]; e21h = ch.ewm(span=21, adjust=False).mean().iloc[-1]
                e200h = ch.ewm(span=min(200,len(ch)-1), adjust=False).mean().iloc[-1]
                ph = ch.iloc[-1]
                h1b = bool(ph > e21h and e21h > e200h)
                h1r = bool(ph < e21h and e21h < e200h)
        except: pass
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price, "cenario": cen,
            "rsi": float(rsi), "atr": atr, "adx": adx, "ema9": float(ema9), "ema21": float(ema21),
            "ema200": float(ema200), "upper": float(upper), "lower": float(lower),
            "macd_bull": macd_bull, "macd_bear": macd_bear, "macd_hist": float(mh.iloc[-1]),
            "vol_ok": vol_ok, "vol_ratio": vol_ratio, "t_buy": float(highs.tail(5).max()),
            "t_sell": float(lows.tail(5).min()), "h1_bull": h1b, "h1_bear": h1r, "change_pct": chg,
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}"); return None

# ═══════════════════════════════════════════════════════════════
# CONFLUÊNCIA
# ═══════════════════════════════════════════════════════════════
def calc_confluence(res, d):
    if d == "BUY":
        checks = [
            ("EMA 200 acima", res["price"] > res["ema200"]), ("EMA 9 > 21", res["ema9"] > res["ema21"]),
            ("MACD Alta", res["macd_bull"]), ("Volume OK", res["vol_ok"]), ("RSI < 65", res["rsi"] < 65),
            ("TF Superior Alta", res["h1_bull"]), ("ADX tendência", res["adx"] > Config.ADX_MIN),
        ]
    else:
        checks = [
            ("EMA 200 abaixo", res["price"] < res["ema200"]), ("EMA 9 < 21", res["ema9"] < res["ema21"]),
            ("MACD Baixa", res["macd_bear"]), ("Volume OK", res["vol_ok"]), ("RSI > 35", res["rsi"] > 35),
            ("TF Superior Baixa", res["h1_bear"]), ("ADX tendência", res["adx"] > Config.ADX_MIN),
        ]
    sc = sum(1 for _, ok in checks if ok)
    return sc, len(checks), checks
def cbar(sc, tot):
    f = math.floor(sc/tot*5)
    return "█" * f + "░" * (5-f)

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
    if (c0>o0) and (c1<o1) and c0>o1 and o0<c1: pb=True; nm="Engolfo de Alta"
    elif (c0<o0) and (c1>o1) and c0<c1 and o0>l1: pb2=True; nm="Engolfo de Baixa"
    elif lw>body0*2 and uw<body0*0.5 and body0<rng0*0.4: pb=True; nm="Martelo"
    elif uw>body0*2 and lw<body0*0.5 and body0<rng0*0.4: pb2=True; nm="Estrela Cadente"
    elif body0 < rng0*0.1: pb=pb2=True; nm="Doji"
    elif lw>rng0*0.6 and body0<rng0*0.25: pb=True; nm="Pin Bar Alta"
    elif uw>rng0*0.6 and body0<rng0*0.25: pb2=True; nm="Pin Bar Baixa"
    return pb, pb2, nm

def get_reversal_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, (" ", "5d"))[1]
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 30: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]
        price = float(closes.iloc[-1])
        w = min(20, len(closes)-1)
        sma = closes.rolling(w).mean(); std = closes.rolling(w).std()
        ub = float((sma+std*2).iloc[-1]); lb = float((sma-std*2).iloc[-1])
        delta = closes.diff()
        gain = delta.where(delta>0,0).rolling(14).mean(); loss = (-delta.where(delta<0,0)).rolling(14).mean()
        rsi_s = 100-100/(1+gain/loss); rsi = float(rsi_s.iloc[-1])
        ema12 = closes.ewm(span=12,adjust=False).mean(); ema26 = closes.ewm(span=26,adjust=False).mean()
        mh = (ema12-ema26)-(ema12-ema26).ewm(span=9,adjust=False).mean()
        tr = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()],axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd>0)&(hd>-ld),0.0); mdm = (-ld).where((-ld>0)&(-ld>hd),0.0)
        as_ = tr.ewm(alpha=1/14,adjust=False).mean()
        pdi = 100*pdm.ewm(alpha=1/14,adjust=False).mean()/(as_+1e-10)
        mdi = 100*mdm.ewm(alpha=1/14,adjust=False).mean()/(as_+1e-10)
        adx = float((100*(pdi-mdi).abs()/(pdi+mdi+1e-10)).ewm(alpha=1/14,adjust=False).mean().iloc[-1])
        lb10 = 10; rh = closes.tail(lb10).max(); rl = closes.tail(lb10).min()
        ph = closes.iloc[-lb10*2:-lb10].max(); pl = closes.iloc[-lb10*2:-lb10].min()
        div_bear = bool(rh>ph and rsi<rsi_s.iloc[-lb10*2:-lb10].max() and rsi>55)
        div_bull = bool(rl<pl and rsi>rsi_s.iloc[-lb10*2:-lb10].min() and rsi<45)
        mdiv_bear = bool(closes.iloc[-1]>closes.iloc[-3] and mh.iloc[-1]<mh.iloc[-3])
        mdiv_bull = bool(closes.iloc[-1]<closes.iloc[-3] and mh.iloc[-1]>mh.iloc[-3])
        rng0 = highs.iloc[-1]-lows.iloc[-1] or 1e-10
        uw = highs.iloc[-1]-max(closes.iloc[-1],df["Open"].iloc[-1])
        lw = min(closes.iloc[-1],df["Open"].iloc[-1])-lows.iloc[-1]
        pb, pb2, pnm = detect_candle_patterns(df)
        near_up = price >= ub*0.998; near_dn = price <= lb*1.002
        rsi_ob = rsi > 75; rsi_os = rsi < 25
        sig_sell = near_up or rsi_ob or div_bear or mdiv_bear
        sig_buy = near_dn or rsi_os or div_bull or mdiv_bull
        if not (sig_sell or sig_buy): return None
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price, "rsi": rsi, "atr": atr, "adx": adx, "adx_mature": adx>30,
            "upper_band": ub, "lower_band": lb, "near_upper": near_up, "near_lower": near_dn,
            "rsi_overbought": rsi_ob, "rsi_oversold": rsi_os, "div_bear": div_bear, "div_bull": div_bull,
            "macd_div_bear": mdiv_bear, "macd_div_bull": mdiv_bull, "wick_bear": bool(uw>rng0*0.5),
            "wick_bull": bool(lw>rng0*0.5), "pat_bull": pb, "pat_bear": pb2, "pat_name": pnm,
            "signal_sell_ct": sig_sell, "signal_buy_ct": sig_buy,
        }
    except Exception as e: log(f"[CT] {symbol}: {e}"); return None

def calc_reversal_conf(res, d):
    if d == "SELL":
        checks = [
            ("RSI sobrecomprado", res["rsi_overbought"]), ("Banda Superior BB", res["near_upper"]),
            ("RSI div. bearish", res["div_bear"]), ("MACD div. bearish", res["macd_div_bear"]),
            ("Candle de baixa", res["pat_bear"]), ("Wick superior", res["wick_bear"]), ("ADX maduro", res["adx_mature"]),
        ]
    else:
        checks = [
            ("RSI sobrevendido", res["rsi_oversold"]), ("Banda Inferior BB", res["near_lower"]),
            ("RSI div. bullish", res["div_bull"]), ("MACD div. bullish", res["macd_div_bull"]),
            ("Candle de alta", res["pat_bull"]), ("Wick inferior", res["wick_bull"]), ("ADX maduro", res["adx_mature"]),
        ]
    sc = sum(1 for _, ok in checks if ok)
    return sc, len(checks), checks

def detect_reversal(res):
    if not res: return (False, None, 0, [])
    motivos = []; forca = 0; dir_rev = None
    rsi = res["rsi"]; price = res["price"]; cen = res["cenario"]
    if cen == "ALTA" or res["ema9"] > res["ema21"]:
        if rsi >= 70: motivos.append(f"RSI sobrecomprado ({rsi:.0f})"); forca += 30; dir_rev = "SELL"
        if rsi >= 75: motivos.append("RSI extremo"); forca += 15
        if price >= res["upper"]: motivos.append("Banda superior BB"); forca += 25; dir_rev = "SELL"
        if res["macd_hist"] < 0 and res["ema9"] > res["ema21"]: motivos.append("Div. MACD baixista"); forca += 20; dir_rev = "SELL"
        if res["adx"] < 20 and cen == "ALTA": motivos.append(f"ADX fraco ({res['adx']:.0f})"); forca += 10
    if cen == "BAIXA" or res["ema9"] < res["ema21"]:
        if rsi <= 30: motivos.append(f"RSI sobrevendido ({rsi:.0f})"); forca += 30; dir_rev = "BUY"
        if rsi <= 25: motivos.append("RSI extremo"); forca += 15
        if price <= res["lower"]: motivos.append("Banda inferior BB"); forca += 25; dir_rev = "BUY"
        if res["macd_hist"] > 0 and res["ema9"] < res["ema21"]: motivos.append("Div. MACD altista"); forca += 20; dir_rev = "BUY"
        if res["adx"] < 20 and cen == "BAIXA": motivos.append(f"ADX fraco ({res['adx']:.0f})"); forca += 10
    forca = min(forca, 100)
    return (forca >= 40 and dir_rev is not None, dir_rev, forca, motivos)

# ═══════════════════════════════════════════════════════════════
# PUSH NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════
_push_subscriptions = []
def send_push(title, body, icon="/icon-192.png"):
    try:
        from pywebpush import webpush, WebPushException
        priv_key = os.getenv("VAPID_PRIVATE_KEY", "")
        pub_key = os.getenv("VAPID_PUBLIC_KEY", "")
        email = os.getenv("VAPID_EMAIL", "mailto:admin@sniperbot.app")
        if not priv_key or not pub_key: return
        data = json.dumps({"title": title, "body": body, "icon": icon})
        dead = []
        for sub in _push_subscriptions:
            try:
                webpush(subscription_info=sub, data=data, vapid_private_key=priv_key,
                        vapid_claims={"sub": email, "aud": sub["endpoint"].split("/")[0]+"//"+sub["endpoint"].split("/")[2]})
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
        self.paused_until = 0; self.active_trades = []; self.pending_operations = []
        self.radar_list = {}; self.gatilho_list = {}; self.reversal_list = {}
        self.asset_cooldown = {}; self.history = []
        self.last_id = 0; self.last_news_ts = 0; self._restore_msg = None
        self.trend_cache = {}; self.last_trends_update = 0
        self.signals_feed = []

    def send(self, text, markup=None, disable_preview=False):
        import re
        clean = re.sub(r"<[^>]+>", "", text).strip()
        tipo = push_title = push_body = None
        if "RADAR" in text: tipo="radar"; push_title="⚠ RADAR"
        elif "GATILHO ATINGIDO" in text: tipo="gatilho"; push_title="🔔 GATILHO ATINGIDO!"
        elif "OPERAÇÃO PENDENTE" in text: tipo="pending"; push_title="⏳ Operação Pendente"
        elif "SINAL CONFIRMADO" in text: tipo="sinal"; push_title="🎯 SINAL CONFIRMADO!"
        elif "CONTRA-TENDÊNCIA" in text: tipo="ct"; push_title="⚡ Contra-Tendência!"
        elif "CONFLUÊNCIA INSUF" in text: tipo="insuf"
        elif "OPERAÇÃO ENCERRADA" in text: tipo="close"; push_title="🏁 Operação Encerrada"; push_body=clean[:80]
        elif "CIRCUIT BREAKER" in text: tipo="cb"; push_title="⛔ Circuit Breaker Ativado"
        if tipo:
            self.signals_feed.append({"tipo": tipo, "texto": clean[:300], "ts": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")})
            self.signals_feed = self.signals_feed[-50:]
            if push_title:
                body = push_body or clean[:100]
                threading.Thread(target=send_push, args=(push_title, body), daemon=True).start()
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": disable_preview}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=8)
        except Exception as e: log(f"[SEND] {e}")

    def build_menu(self):
        tfl = Config.TIMEFRAMES.get(self.timeframe, ("?", " "))[0]
        ml = Config.MARKET_CATEGORIES[self.mode]["label"] if self.mode != "TUDO" else "TUDO"
        pend_count = len([o for o in self.pending_operations if o["status"] == "PENDING"])
        markup = {"inline_keyboard": [
            [{"text": f"Mercado: {ml}", "callback_data": "ignore"}],
            [{"text": "FOREX", "callback_data": "set_FOREX"}, {"text": "CRIPTO", "callback_data": "set_CRYPTO"}],
            [{"text": "COMM.", "callback_data": "set_COMMODITIES"}, {"text": "INDICES", "callback_data": "set_INDICES"}],
            [{"text": "TUDO", "callback_data": "set_TUDO"}],
            [{"text": f"TF: {self.timeframe} {tfl}", "callback_data": "tf_menu"}],
            [{"text": "Status", "callback_data": "status"}, {"text": "Placar", "callback_data": "placar"}],
            [{"text": f"Pendentes ({pend_count})", "callback_data": "pending"}, {"text": "Noticias", "callback_data": "news"}],
        ]}
        tot = self.wins + self.losses; wr = (self.wins/tot*100) if tot > 0 else 0
        cb = f"\n⛔ CB – retoma em {int((self.paused_until-time.time())/60)}min " if self.is_paused() else ""
        pend_info = f"\n⏳ {pend_count} pendente(s) " if pend_count > 0 else ""
        self.send(f"<b>BOT SNIPER v7.3</b>\n{self.wins}W / {self.losses}L ({wr:.1f}%)\nModo: {ml} | TF: {self.timeframe}{cb}{pend_info}", markup)

    def build_tf_menu(self):
        rows = [[{"text": f"{tf} {lb}{'✅' if tf==self.timeframe else ''}", "callback_data": f"set_tf_{tf}"}] for tf, (lb, _) in Config.TIMEFRAMES.items()]
        rows.append([{"text": "« Voltar", "callback_data": "main_menu"}])
        self.send("Selecione o Timeframe", {"inline_keyboard": rows})

    def set_timeframe(self, tf):
        if tf not in Config.TIMEFRAMES: return
        old = self.timeframe; self.timeframe = tf; save_state(self); self.send(f"✅ TF: {old} → {tf}")

    def set_mode(self, mode):
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]: return
        self.mode = mode; save_state(self); self.send(f"✅ Modo: {mode}")

    def send_news(self): self.send(build_news_msg(), disable_preview=True); self.last_news_ts = time.time()
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
            lines.append(f"{'🟢' if pnl >=0 else '🔴'} {t['symbol']} {t['dir']} P&L: {pnl:+.2f}%")
        self.send("\n".join(lines))

    def send_placar(self):
        tot = self.wins+self.losses; wr = (self.wins/tot*100) if tot>0 else 0
        self.send(f"🏆 W/L: {self.wins}/{self.losses} ({wr:.1f}%)")

    def send_pending_count(self):
        count = len([o for o in self.pending_operations if o["status"] == "PENDING"])
        lines = [f"⏳ <b>OPERAÇÕES PENDENTES</b> ({count})"]
        if not count: lines.append("Nenhuma operação aguardando confirmação.")
        else:
            for op in [o for o in self.pending_operations if o["status"] == "PENDING"][:5]:
                dl = "BUY 🟢" if op["direction"] == "BUY" else "SELL 🔴"
                lines.append(f"<code>{op['symbol']}</code> {dl} | <code>{fmt(op['entry'])}</code> | SL: <code>{fmt(op['sl'])}</code> | TP: <code>{fmt(op['tp'])}</code>")
            if count > 5: lines.append(f"\n... +{count-5} mais no app")
        self.send("\n".join(lines))

    def is_paused(self): return time.time() < self.paused_until
    def reset_pause(self): self.paused_until = 0; self.consecutive_losses = 0; save_state(self); self.send("✅ Circuit Breaker resetado.")

    def update_trends_cache(self):
        if time.time() - self.last_trends_update < Config.TRENDS_INTERVAL: return
        log("📡 Atualizando cache tendências...")
        for s in all_syms():
            try:
                res = get_analysis(s, self.timeframe)
                if res:
                    rev = detect_reversal(res)
                    self.trend_cache[s] = {"data": res, "reversal": {"has": rev[0], "dir": rev[1], "strength": rev[2], "reasons": rev[3]}, "ts": time.time()}
            except Exception as e: log(f"[TRENDS] {s}: {e}")
        self.last_trends_update = time.time()

    def create_pending_operation(self, symbol, direction, price, sl, tp, res, confluence_data):
        op_id = f"{symbol}_{int(time.time()*1000)}"
        op = {
            "id": op_id, "symbol": symbol, "name": res["name"], "direction": direction, "entry": price,
            "sl": sl, "tp": tp, "atr": res["atr"], "rsi": res["rsi"], "adx": res["adx"],
            "created_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M:%S"), "status": "PENDING", "confluence": confluence_data,
        }
        self.pending_operations.append(op)
        log(f"[PENDENTE] {symbol} {direction} criada")
        self._send_pending_alert(op)
        save_state(self)
        return op

    def _send_pending_alert(self, op):
        sl_pct = abs(op["entry"]-op["sl"])/op["entry"]*100
        tp_pct = abs(op["tp"]-op["entry"])/op["entry"]*100
        ratio = f"1:{tp_pct/sl_pct:.1f}" if sl_pct > 0 else "1:0"
        dl = "COMPRAR (BUY) 🟢" if op["direction"]=="BUY" else "VENDER (SELL) 🔴"
        cat = asset_cat(op["symbol"]); cl_lbl = Config.MARKET_CATEGORIES.get(cat, {}).get("label", cat)
        self.send(
            f"⏳ <b>OPERAÇÃO PENDENTE – {op['symbol']}</b> ({op['name']})\n{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
            f"╔══════════════════╗\n  ▶️   <b>{dl}</b>\n╚══════════════════╝\n\n"
            f"💰 <b>Entrada:</b>      <code>{fmt(op['entry'])}</code>\n🛡 <b>Stop Loss:</b>    <code>{fmt(op['sl'])}</code> ({-sl_pct:.2f}%)\n"
            f"🎯 <b>Take Profit:</b>  <code>{fmt(op['tp'])}</code> ({tp_pct:+.2f}%)\n⚖️ <b>Ratio:</b>        <b>{ratio}</b>\n\n"
            f"ATR: <code>{fmt(op['atr'])}</code> | ADX: <code>{op['adx']:.1f}</code> | RSI: <code>{op['rsi']:.1f}</code>\n\n"
            f"<i>Confirme ou rejeite no app (⏳ aba Pendentes)</i>"
        )

    def confirm_pending_operation(self, op_id):
        op = next((o for o in self.pending_operations if o["id"] == op_id), None)
        if not op: return False
        op["status"] = "CONFIRMED"; op["confirmed_at"] = datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M:%S")
        trade = {"symbol": op["symbol"], "name": op["name"], "entry": op["entry"], "tp": op["tp"], "sl": op["sl"],
                 "dir": op["direction"], "peak": op["entry"], "atr": op["atr"], "opened_at": op["created_at"],
                 "session_alerted": True, "pending_id": op_id}
        self.active_trades.append(trade)
        self.radar_list[op["symbol"]] = self.gatilho_list[op["symbol"]] = time.time()
        log(f"[CONFIRM] {op['symbol']} {op['direction']} confirmada")
        self.send(f"✅ <b>OPERAÇÃO CONFIRMADA</b>\n{op['symbol']} {op['direction']}\nEntrada: <code>{fmt(op['entry'])}</code>")
        save_state(self)
        return True

    def ignore_pending_operation(self, op_id):
        op = next((o for o in self.pending_operations if o["id"] == op_id), None)
        if not op: return False
        op["status"] = "IGNORED"; op["ignored_at"] = datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M:%S")
        log(f"[IGNORE] {op['symbol']} {op['direction']} rejeitada")
        save_state(self)
        return True

    def scan(self):
        if self.is_paused() or len(self.active_trades) >= Config.MAX_TRADES: return
        universe = all_syms() if self.mode == "TUDO" else list(Config.MARKET_CATEGORIES[self.mode]["assets"].keys())
        for s in universe:
            cat = asset_cat(s)
            if not mkt_open(cat) or any(t["symbol"]==s for t in self.active_trades): continue
            if any(o["symbol"]==s and o["status"]=="PENDING" for o in self.pending_operations): continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
            res = self.trend_cache.get(s, {}).get("data") or get_analysis(s, self.timeframe)
            if not res: continue
            if s not in self.trend_cache:
                rev = detect_reversal(res)
                self.trend_cache[s] = {"data": res, "reversal": {"has":rev[0],"dir":rev[1],"strength":rev[2],"reasons":rev[3]}, "ts": time.time()}
            if res["cenario"] == "NEUTRO": continue
            price = res["price"]; atr = res["atr"]; cen = res["cenario"]
            cl = asset_cat(s); cl_lbl = Config.MARKET_CATEGORIES.get(cl, {}).get("label", cl)
            if cen == "ALTA":
                gatilho = res["t_buy"]; dir_s = "BUY"
                sl_est = gatilho - Config.ATR_MULT_SL * atr; tp_est = gatilho + Config.ATR_MULT_TP * atr
                preco_ok = price >= gatilho and price < res["upper"] and res["rsi"] < 70
            else:
                gatilho = res["t_sell"]; dir_s = "SELL"
                sl_est = gatilho + Config.ATR_MULT_SL * atr; tp_est = gatilho - Config.ATR_MULT_TP * atr
                preco_ok = price <= gatilho and price > res["lower"] and res["rsi"] > 30
            sl_p = abs(gatilho-sl_est)/gatilho*100; tp_p = abs(tp_est-gatilho)/gatilho*100
            ratio = f"1:{Config.ATR_MULT_TP/Config.ATR_MULT_SL:.1f}"
            if not preco_ok:
                if time.time() - self.radar_list.get(s, 0) > Config.RADAR_COOLDOWN:
                    dist = abs(price-gatilho)/price*100
                    dl = "COMPRA" if dir_s=="BUY" else "VENDA"
                    self.send(f"⚠️ <b>RADAR – {s}</b> ({res['name']})\n{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
                              f"Tendência de <b>{cen}</b> detectada\nAguardando gatilho de <b>{dl}</b>\n\n"
                              f"🎯 Gatilho: <code>{fmt(gatilho)}</code>\n📍 Atual: <code>{fmt(price)}</code> ({dist:.2f}% de distância)\n"
                              f"🛡 SL est.: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n🎯 TP est.: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n"
                              f"⚖️ Ratio: <b>{ratio}</b>\nRSI: <code>{res['rsi']:.1f}</code> | ADX: <code>{res['adx']:.1f}</code>")
                    self.radar_list[s] = time.time()
                continue
            if time.time() - self.gatilho_list.get(s, 0) > Config.GATILHO_COOLDOWN:
                dl = "COMPRAR (BUY) 🟢" if dir_s=="BUY" else "VENDER (SELL) 🔴"
                self.send(f"🔔 <b>GATILHO ATINGIDO – {s}</b> ({res['name']})\n{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
                          f"✅ Preço chegou no nível de entrada!\n\n▶️ <b>AÇÃO: {dl}</b>\n\n"
                          f"💰 Entrada: <code>{fmt(price)}</code>\n🛡 Stop Loss: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n"
                          f"🎯 Take Profit: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n⚖️ Ratio: <b>{ratio}</b>\n\n"
                          f"⏳ <i>Verificando confluência…</i>")
                self.gatilho_list[s] = time.time()
            sc, tot_c, checks = calc_confluence(res, dir_s); bar = cbar(sc, tot_c)
            if sc < Config.MIN_CONFLUENCE:
                falhou = [nm for nm, ok in checks if not ok]
                self.send(f"⚡ <b>CONFLUÊNCIA INSUF. – {s}</b>\n\nGatilho atingido mas bot NÃO entrou.\n"
                          f"Score: <code>{sc}/{tot_c}</code> [{bar}] (min: {Config.MIN_CONFLUENCE})\n\n"
                          f"<b>Filtros que falharam:</b>\n" + "\n".join(f"   ❌ {nm}" for nm in falhou)); continue
            sl_final = price - Config.ATR_MULT_SL * atr if dir_s == "BUY" else price + Config.ATR_MULT_SL * atr
            tp_final = price + Config.ATR_MULT_TP * atr if dir_s == "BUY" else price - Config.ATR_MULT_TP * atr
            confluence_info = {"score": sc, "total": tot_c, "bar": bar, "checks": [{"name": nm, "passed": ok} for nm, ok in checks]}
            self.create_pending_operation(s, dir_s, price, sl_final, tp_final, res, confluence_info)

    def scan_reversal_forex(self):
        if self.is_paused() or not mkt_open("FOREX") or len(self.active_trades) >= Config.MAX_TRADES: return
        for s in Config.MARKET_CATEGORIES["FOREX"]["assets"].keys():
            if any(t["symbol"]==s for t in self.active_trades): continue
            if any(o["symbol"]==s and o["status"]=="PENDING" for o in self.pending_operations): continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
            if time.time() - self.reversal_list.get(s, 0) < Config.REVERSAL_COOLDOWN: continue
            res = get_reversal_analysis(s, self.timeframe)
            if not res: continue
            price = res["price"]; atr = res["atr"]; cands = []
            for d in (["SELL"] if res["signal_sell_ct"] else []) + (["BUY"] if res["signal_buy_ct"] else []):
                sc, tc, ch = calc_reversal_conf(res, d)
                if sc >= Config.MIN_CONFLUENCE_CT:
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
                    cands.append((sc, tc, ch, d, sinais))
            if not cands: continue
            cands.sort(key=lambda x: x[0], reverse=True)
            sc, tc, ch, dir_s, sinais = cands[0]; bar = cbar(sc, tc)
            sl_m = Config.ATR_MULT_SL; tp_m = Config.ATR_MULT_SL * 1.5
            sl = price - sl_m*atr if dir_s == "BUY" else price + sl_m*atr
            tp = price + tp_m*atr if dir_s == "BUY" else price - tp_m*atr
            confluence_info = {"score": sc, "total": tc, "bar": bar, "tipo": "CONTRA-TENDÊNCIA", "razoes": sinais}
            self.create_pending_operation(s, dir_s, price, sl, tp, res, confluence_info)

    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res: continue
            cur = res["price"]; atr = res["atr"]
            if not t.get("session_alerted", True):
                dl = "BUY 🟢" if t["dir"]=="BUY" else "SELL 🔴"
                sl_p = abs(t["entry"]-t["sl"])/t["entry"]*100; tp_p = abs(t["tp"]-t["entry"])/t["entry"]*100
                self.send(f"📌 <b>TRADE RESTAURADO – {t['symbol']}</b>\nAção: <b>{dl}</b> | Aberto: {t.get('opened_at','?')}\n"
                          f"Entrada: <code>{fmt(t['entry'])}</code> | Atual: <code>{fmt(cur)}</code>\n"
                          f"🎯 TP: <code>{fmt(t['tp'])}</code> ({tp_p:+.2f}%)\n🛡 SL: <code>{fmt(t['sl'])}</code> ({-sl_p:.2f}%)")
                t["session_alerted"] = True; changed = True
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur; nsl = cur - Config.ATR_MULT_TRAIL*atr
                if nsl > t["sl"]: t["sl"] = nsl; changed = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur; nsl = cur + Config.ATR_MULT_TRAIL*atr
                if nsl < t["sl"]: t["sl"] = nsl; changed = True
            is_win = (t["dir"]=="BUY" and cur>=t["tp"]) or (t["dir"]=="SELL" and cur<=t["tp"])
            is_loss = (t["dir"]=="BUY" and cur<=t["sl"]) or (t["dir"]=="SELL" and cur>=t["sl"])
            if is_win or is_loss:
                pnl = (cur-t["entry"])/t["entry"]*100
                if t["dir"] == "SELL": pnl = -pnl
                st = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                closed_at = datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")
                if is_win: self.wins += 1; self.consecutive_losses = 0
                else: self.losses += 1; self.consecutive_losses += 1; self.asset_cooldown[t["symbol"]] = time.time()
                self.history.append({"symbol": t["symbol"], "dir": t["dir"], "result": "WIN" if is_win else "LOSS", "pnl": round(pnl,2), "closed_at": closed_at})
                self.send(f"🏁 <b>OPERAÇÃO ENCERRADA</b>\nAtivo: <b>{t['symbol']}</b> ({t.get('name','')}) | {t['dir']}\n"
                          f"Resultado: <b>{st}</b>\n\n💰 Entrada: <code>{fmt(t['entry'])}</code>\n🔚 Saída: <code>{fmt(cur)}</code>\nP&L: <code>{pnl:+.2f}%</code>")
                self.active_trades.remove(t); changed = True
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    mins = Config.PAUSE_DURATION // 60
                    self.send(f"⛔ <b>CIRCUIT BREAKER ATIVADO</b>\n\n{self.consecutive_losses} losses consecutivos.\n"
                              f"Pausado por <b>{mins} minutos</b>.\n\nUse /resetpausa para retomar.")
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
 { url: '/' }
}));
});
self.addEventListener('notificationclick', e => {
e.notification.close();
e.waitUntil(clients.matchAll({type:'window'}).then(cs => {
if (cs.length) cs[0].focus();else clients.openWindow('/');
}));
});
"""

# ═══════════════════════════════════════════════════════════════
# DASHBOARD HTML (ATUALIZADO v7.3)
# ═══════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Sniper Bot v7.3</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{--bg:#06090f;--bg2:#0b1018;--bg3:#111827;--bg4:#192032;--border:#1e2d45;--text:#d4e4f7;--muted:#3d5575;--muted2:#5a7a9f;
--green:#00e676;--green2:#00c853;--g3:rgba(0,230,118,.12);--red:#ff1744;--red2:#d50000;--r3:rgba(255,23,68,.1);--gold:#ffca28;--y3:rgba(255,202,40,.12);
--blue:#448aff;--cyan:#00e5ff;--orange:#ff6d00;--mono:'JetBrains Mono',monospace;--sans:'DM Sans',sans-serif;--r:14px;--rsm:8px;--nav:62px;--safe:env(safe-area-inset-bottom,0px);--head:58px}
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
.ss{font-size:9px;color:var(--muted2);margin-top:3px}.g{color:var(--green)}.r{color:var(--red)}.go{color:var(--gold)}.cy{color:var(--cyan)}.bl{color:var(--blue)}.or{color:var(--orange)}
.tc{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:8px}
.tc.buy{border-left:3px solid var(--green)}.tc.sell{border-left:3px solid var(--red)}.tc.neutro{border-left:3px solid var(--blue)}
.tc-top{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px}
.tc-sym{font-size:17px;font-weight:700;font-family:var(--mono)}
.tc-nm{font-size:9px;color:var(--muted2);margin-top:2px}
.db{font-size:10px;font-weight:700;font-family:var(--mono);padding:5px 10px;border-radius:20px}
.dbu{background:var(--g3);color:var(--green)}.dbs{background:var(--r3);color:var(--red)}.dbn{background:rgba(68,138,255,.1);color:var(--blue)}
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
.rb:active{opacity:.7}/* Pending Cards */
.pending-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:10px}
.pending-card.buy{border-left:4px solid var(--green)}.pending-card.sell{border-left:4px solid var(--red)}
.pc-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.pc-sym{font-size:16px;font-weight:700;font-family:var(--mono)}
.pc-status{font-size:8px;padding:2px 8px;border-radius:20px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;background:var(--y3);color:var(--gold)}
.pc-lvls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px}
.pc-lv{background:var(--bg3);border-radius:var(--rsm);padding:8px;text-align:center;font-size:10px}
.pc-ll{font-size:7px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:2px}
.pc-val{font-family:var(--mono);font-weight:700;font-size:12px}
.pc-val.g{color:var(--green)}.pc-val.r{color:var(--red)}
.pc-actions{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.pc-btn{flex:1;min-width:80px;padding:8px 10px;border:none;border-radius:var(--rsm);font-size:11px;font-weight:600;cursor:pointer;font-family:var(--sans);transition:.15s;letter-spacing:.3px}
.pc-btn:active{transform:scale(.96)}
.pc-copy{background:var(--bg3);border:1px solid var(--border);color:var(--muted2)}
.pc-copy.copied{background:var(--g3);border-color:var(--green);color:var(--green)}
.pc-confirm{background:var(--g3);border:1px solid rgba(0,230,118,.3);color:var(--green)}
.pc-ignore{background:var(--r3);border:1px solid rgba(255,23,68,.3);color:var(--red)}
.pc-info{display:flex;align-items:center;justify-content:space-between;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);font-size:9px;color:var(--muted2)}
.pc-time{font-family:var(--mono)}
/* Config */
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
/* Calc */
.calc-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}
.cinp{background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:12px;font-family:var(--mono);color:var(--text);font-size:14px;width:100%}
.cinp:focus{outline:none;border-color:var(--green)}
.cres{background:var(--g3);border:1px solid rgba(0,230,118,.3);border-radius:var(--r);padding:14px;margin-top:10px}
.cres-row{display:flex;justify-content:space-between;margin-bottom:8px;font-size:12px}
.cres-val{font-family:var(--mono);font-weight:700}
.copy-sm{background:var(--bg3);border:1px solid var(--border);color:var(--muted2);padding:4px 8px;border-radius:6px;font-size:10px;cursor:pointer;margin-left:6px}
.copy-sm:hover{border-color:var(--green);color:var(--green)}
</style>
</head>
<body>
<div id="app">
  <div id="hdr">
    <div class="hdr-l"><div class="logo">S</div><div><div class="t1">Sniper Bot</div><div class="t2">v7.3 Manual Ops</div></div></div>
    <div class="hdr-r"><div class="lpill"><div class="ldot"></div>LIVE</div><div class="ibtn" id="refbtn" onclick="refreshAll()">↻</div></div>
  </div>
  <div id="pages">
    <div id="pg-dash" class="pg on">      <div class="chd"><span>📊 Dashboard</span><span class="ts" id="d-ts">--</span></div>
      <div id="cbbar" class="cbbar"><span class="cbtxt">⛔ CIRCUIT BREAKER</span><span class="cbmin" id="cbmin">--m</span></div>
      <div id="eb" class="eb">⚠ Erro de conexão. Tente novamente.</div>
      <div class="srow">
        <div class="sb"><div class="sl">Wins</div><div class="sv g" id="d-w">--</div><div class="ss" id="d-wr">--% WR</div></div>
        <div class="sb"><div class="sl">Losses</div><div class="sv r" id="d-l">--</div><div class="ss" id="d-sq">Seq --</div></div>
        <div class="sb"><div class="sl">Trades</div><div class="sv bl" id="d-t">--</div><div class="ss" id="d-mt">--</div></div>
      </div>
      <div class="sh"><span class="sttl">💼 Trades Abertos</span></div>
      <div id="d-trades"><div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto</div></div></div>
      <div class="dv"></div>
      <div class="sh"><span class="sttl">🌐 Mercados</span></div>
      <div id="d-mkts" class="mg"></div>
    </div>

    <div id="pg-pend" class="pg">
      <div class="chd"><span>⏳ Operações Pendentes</span><span class="ts" id="pend-ts">Auto: 10s</span></div>
      <div id="pending-list"><div class="empty"><span class="empi">✨</span><div class="empt">Nenhuma operação pendente</div></div></div>
    </div>

    <div id="pg-trends" class="pg">
      <div class="chd"><span>📈 Tendências em Tempo Real</span><span class="ts" id="trends-ts">Atualizando...</span></div>
      <div id="trends-list"><div class="empty"><span class="empi">⏳</span><div class="empt">Carregando dados de mercado...</div></div></div>
    </div>

    <div id="pg-calc" class="pg">
      <div class="chd"><span>🧮 Calculadora de Risco</span></div>
      <div class="card">
        <div class="cfgl">Entrada Rápida</div>
        <div class="calc-grid">
          <input type="number" id="calc-cap" class="cinp" placeholder="Capital ($)" oninput="updateCalc()">
          <input type="number" id="calc-risk" class="cinp" placeholder="Risco (%)" value="1" oninput="updateCalc()">
          <input type="number" id="calc-entry" class="cinp" placeholder="Preço Entrada" oninput="updateCalc()">
          <input type="number" id="calc-sl" class="cinp" placeholder="Preço SL" oninput="updateCalc()">
          <input type="number" id="calc-tp" class="cinp" placeholder="Preço TP (Opcional)" oninput="updateCalc()">
        </div>
        <div id="calc-res" class="cres" style="display:none">
          <div class="cres-row"><span>📏 Tamanho Posição:</span><span class="cres-val" id="res-size">--</span><button class="copy-sm" onclick="copyVal(document.getElementById('res-size').textContent, 'cp-size')">📋</button></div>
          <div class="cres-row"><span>💵 Valor em Risco:</span><span class="cres-val r" id="res-risk">--</span></div>
          <div class="cres-row"><span>🎯 Potencial Lucro:</span><span class="cres-val g" id="res-reward">--</span></div>
          <div class="cres-row"><span>⚖️ Ratio R:R:</span><span class="cres-val bl" id="res-rr">--</span></div>
        </div>
        <p style="font-size:10px;color:var(--muted);margin-top:10px">💡 Cálculo baseado na distância absoluta de preço. Ajuste conforme lote/pip da sua corretora.</p>
      </div>
    </div>

    <div id="pg-cfg" class="pg">
      <div class="chd"><span>⚙ Configurações</span></div>
      <div class="cfgsec">
        <div class="cfgl">Mercado</div>        <div class="mdg">
          <button class="mdb" data-mode="FOREX" onclick="setMode('FOREX')"><span class="mdi">📈</span>FOREX</button>
          <button class="mdb" data-mode="CRYPTO" onclick="setMode('CRYPTO')"><span class="mdi">₿</span>CRIPTO</button>
          <button class="mdb" data-mode="COMMODITIES" onclick="setMode('COMMODITIES')"><span class="mdi">🏅</span>COMM.</button>
          <button class="mdb" data-mode="INDICES" onclick="setMode('INDICES')"><span class="mdi">📊</span>ÍNDICES</button>
        </div>
      </div>
      <div class="cfgsec">
        <div class="cfgl">Timeframe</div>
        <div class="tfg">
          <button class="tfb" data-tf="1m" onclick="setTf('1m')"><span class="tfd">●</span>1m</button>
          <button class="tfb" data-tf="5m" onclick="setTf('5m')"><span class="tfd">●</span>5m</button>
          <button class="tfb" data-tf="15m" onclick="setTf('15m')"><span class="tfd">●</span>15m</button>
          <button class="tfb" data-tf="30m" onclick="setTf('30m')"><span class="tfd">●</span>30m</button>
          <button class="tfb" data-tf="1h" onclick="setTf('1h')"><span class="tfd">●</span>1h</button>
          <button class="tfb" data-tf="4h" onclick="setTf('4h')"><span class="tfd">●</span>4h</button>
        </div>
      </div>
      <div class="dv"></div>
      <button class="ab abd" onclick="resetPausa()">⛔ Resetar Circuit Breaker</button>
      <button class="ab abn" onclick="window.location.reload()">↻ Atualizar App</button>
      <div class="pgrid" id="p-stats">
        <div class="pbox"><div class="plbl">Stop Loss</div><div class="pval" id="p-sl">--</div></div>
        <div class="pbox"><div class="plbl">Take Profit</div><div class="pval" id="p-tp">--</div></div>
        <div class="pbox"><div class="plbl">Max Trades</div><div class="pval" id="p-mt">--</div></div>
        <div class="pbox"><div class="plbl">Confluência</div><div class="pval" id="p-mc">--</div></div>
      </div>
    </div>
  </div>
  <div id="nav">
    <button class="nb on" onclick="goTo('dash',this)"><span class="ni">⬡</span>Dashboard</button>
    <button class="nb" onclick="goTo('pend',this)"><span class="ni">⏳</span>Pendentes<span class="nbadge" id="nbadge-pend">0</span></button>
    <button class="nb" onclick="goTo('trends',this)"><span class="ni">📈</span>Tendências</button>
    <button class="nb" onclick="goTo('calc',this)"><span class="ni">🧮</span>Risco</button>
    <button class="nb" onclick="goTo('cfg',this)"><span class="ni">⚙</span>Config</button>
  </div>
</div>
<script>
let _st=null,_pend=[];
function fp(p){if(p===undefined||p===null)return'--';if(p>=10000)return p.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});if(p>=1000)return p.toFixed(2);if(p>=10)return p.toFixed(4);if(p>=1)return p.toFixed(5);return p.toFixed(6);}
async function apiFetch(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},mode:'same-origin',...opts});if(!r.ok)throw new Error(r.status);return r.json();}
function goTo(pg,btn){document.querySelectorAll('.pg').forEach(p=>{p.classList.remove('on');p.style.display='none';});document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));const t=document.getElementById('pg-'+pg);if(t){t.classList.add('on');t.style.display='block';}btn.classList.add('on');if(pg==='pend')loadPending();if(pg==='trends')loadTrends();if(pg==='cfg')loadCfg();}
async function refreshAll(){const b=document.getElementById('refbtn');b.classList.add('spin');try{await loadDash();if(document.querySelector('.pg.on').id==='pg-pend')await loadPending();if(document.querySelector('.pg.on').id==='pg-trends')await loadTrends();}finally{b.classList.remove('spin');}}
async function loadDash(){try{_st=await apiFetch('/api/status');document.getElementById('eb').style.display='none';document.getElementById('d-w').textContent=_st.wins;document.getElementById('d-l').textContent=_st.losses;document.getElementById('d-wr').textContent=_st.winrate+'% WR';document.getElementById('d-sq').textContent='Seq: '+_st.consecutive_losses;document.getElementById('d-t').textContent=_st.active_trades.length+'/3';document.getElementById('d-mt').textContent=_st.mode+' '+_st.timeframe;const cb=document.getElementById('cbbar');if(_st.paused){cb.style.display='flex';document.getElementById('cbmin').textContent=_st.cb_mins+'min';}else cb.style.display='none';document.getElementById('d-trades').innerHTML=_st.active_trades.length?_st.active_trades.map(renderTC).join(''):'<div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto</div></div>';const mn={FOREX:'📈 FOREX',CRYPTO:'₿ Cripto',COMMODITIES:'🏅 Commodities',INDICES:'📊 Índices'};document.getElementById('d-mkts').innerHTML=Object.entries(_st.markets).map(([k,v])=>`<div class="mkt"><span class="mktn">${mn[k]||k}</span><span class="mkts ${v?'mop':'mcl'}">${v?'Aberto':'Fechado'}</span></div>`).join('');document.getElementById('d-ts').textContent='Atualizado '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});updCfgBtns();updBadges();}catch(e){document.getElementById('eb').style.display='block';}}
function renderTC(t){const buy=t.dir==='BUY',pos=t.pnl>=0;const cls=buy?'buy':'sell';const dc=buy?'dbu':'dbs';const pct=Math.min(Math.abs(t.pnl)/3*100,100);return`<div class="tc ${cls}"><div class="tc-top"><div><div class="tc-sym">${t.symbol}</div><div class="tc-nm">${t.name||''} · ${t.opened_at||''}</div></div><div class="db ${dc}">${buy?'▲ BUY':'▼ SELL'}</div></div><div class="lvls"><div class="lv"><div class="lvl">Entrada</div><div class="lvv">${fp(t.entry)}</div></div><div class="lv"><div class="lvl">SL 🛡</div><div class="lvv r">${fp(t.sl)}</div></div><div class="lv"><div class="lvl">TP 🎯</div><div class="lvv g">${fp(t.tp)}</div></div></div><div class="tcft"><div class="pnl ${pos?'g':'r'}">${t.pnl>=0?'+':''}${t.pnl.toFixed(2)}%</div><div class="tcm">Atual: ${fp(t.current)}</div></div><div class="pbar"><div class="pbar-f ${pos?'pg-fill':'pr-fill'}" style="width:${pct}%"></div></div></div>`;}
async function loadPending(){try{_pend=await apiFetch('/api/pending');const cnt=_pend.filter(p=>p.status==='PENDING').length;document.getElementById('nbadge-pend').textContent=cnt>0?cnt:'';document.getElementById('nbadge-pend').style.display=cnt>0?'flex':'none';renderPending();}catch(e){console.error(e);}}
function renderPending(){const el=document.getElementById('pending-list');const active=_pend.filter(p=>p.status==='PENDING');if(!active.length){el.innerHTML='<div class="empty"><span class="empi">✨</span><div class="empt">Nenhuma operação pendente</div></div>';return;}el.innerHTML=active.map(op=>{const buy=op.direction==='BUY';const slp=Math.abs(op.entry-op.sl)/op.entry*100;const tpp=Math.abs(op.tp-op.entry)/op.entry*100;const ratio=tpp/slp;return`<div class="pending-card ${buy?'buy':'sell'}"><div class="pc-head"><div><div class="pc-sym">${op.symbol}</div><div style="font-size:9px;color:var(--muted2);margin-top:2px">${op.name}</div></div><div class="pc-status">⏳ Pendente</div></div><div style="text-align:center;margin-bottom:10px;font-size:18px;font-weight:700;color:${buy?'var(--green)':'var(--red)'}">${buy?'▲ BUY':'▼ SELL'}</div><div class="pc-lvls"><div class="pc-lv"><div class="pc-ll">Entrada</div><div class="pc-val">${fp(op.entry)}</div></div><div class="pc-lv"><div class="pc-ll">SL 🛡</div><div class="pc-val r">${fp(op.sl)}</div></div><div class="pc-lv"><div class="pc-ll">TP 🎯</div><div class="pc-val g">${fp(op.tp)}</div></div></div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px;font-size:10px;color:var(--muted2)"><div>ATR: <code style="color:var(--text)">${fp(op.atr)}</code></div><div>RSI: <code style="color:var(--text)">${op.rsi.toFixed(1)}</code></div><div>ADX: <code style="color:var(--text)">${op.adx.toFixed(1)}</code></div></div><div class="pc-actions"><button class="pc-btn pc-copy" id="sl_${op.id}" onclick="copyVal('${fp(op.sl)}','sl_${op.id}')">📋 SL</button><button class="pc-btn pc-copy" id="tp_${op.id}" onclick="copyVal('${fp(op.tp)}','tp_${op.id}')">📋 TP</button><button class="pc-btn pc-confirm" onclick="confirmPending('${op.id}')">✅ Entrar</button><button class="pc-btn pc-ignore" onclick="ignorePending('${op.id}')">❌ Ignorar</button></div><div class="pc-info"><span>Ratio: <strong>${ratio.toFixed(2)}:1</strong></span><span class="pc-time">${op.created_at}</span></div></div>`;}).join('');}
function copyVal(val,uid){navigator.clipboard.writeText(val).then(()=>{const btn=document.getElementById(uid);if(btn){btn.textContent='✅';btn.classList.add('copied');setTimeout(()=>{btn.textContent=uid.startsWith('sl')?'📋 SL':'📋 TP';btn.classList.remove('copied');},1200);}}).catch(()=>alert('Copie manualmente: '+val));}
async function confirmPending(opId){try{await apiFetch('/api/confirm',{method:'POST',body:JSON.stringify({op_id:opId})});await loadPending();await loadDash();}catch(e){alert('Erro: '+e.message);}}
async function ignorePending(opId){try{await apiFetch('/api/ignore',{method:'POST',body:JSON.stringify({op_id:opId})});await loadPending();}catch(e){alert('Erro: '+e.message);}}async function loadTrends(){try{const data=await apiFetch('/api/trends');const el=document.getElementById('trends-list');if(!data||data.length===0){el.innerHTML='<div class="empty"><span class="empi">📡</span><div class="empt">Nenhum sinal ativo no momento</div></div>';return;}el.innerHTML=data.slice(0,20).map(t=>{const cls=t.dir==='ALTA'?'buy':t.dir==='BAIXA'?'sell':'neutro';const dc=t.dir==='ALTA'?'dbu':t.dir==='BAIXA'?'dbs':'dbn';return`<div class="tc ${cls}"><div class="tc-top"><div><div class="tc-sym">${t.symbol}</div><div class="tc-nm">${t.name} · Preço: ${t.price}</div></div><div class="db ${dc}">${t.dir}</div></div><div class="lvls"><div class="lv"><div class="lvl">Score</div><div class="lvv">${t.score}/7</div></div><div class="lv"><div class="lvl">RSI</div><div class="lvv">${t.rsi.toFixed(1)}</div></div><div class="lv"><div class="lvl">ADX</div><div class="lvv">${t.adx.toFixed(1)}</div></div></div></div>`;}).join('');document.getElementById('trends-ts').textContent='Atualizado '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});}catch(e){console.error(e);}}
function updateCalc(){const cap=parseFloat(document.getElementById('calc-cap').value)||0;const risk=parseFloat(document.getElementById('calc-risk').value)||0;const entry=parseFloat(document.getElementById('calc-entry').value)||0;const sl=parseFloat(document.getElementById('calc-sl').value)||0;const tp=parseFloat(document.getElementById('calc-tp').value)||0;if(cap&&risk&&entry&&sl){const riskAmt=cap*(risk/100);const slDist=Math.abs(entry-sl);const size=riskAmt/slDist;const tpDist=tp?Math.abs(tp-entry):0;const reward=tp?size*tpDist:0;const rr=tp?(tpDist/slDist).toFixed(2):'--';document.getElementById('res-size').textContent=size.toFixed(2);document.getElementById('res-risk').textContent='$'+riskAmt.toFixed(2);document.getElementById('res-reward').textContent=tp?'$'+reward.toFixed(2):'--';document.getElementById('res-rr').textContent=rr;document.getElementById('calc-res').style.display='block';}}
function updBadges(){const pend=_pend?_pend.filter(p=>p.status==='PENDING').length:0;document.getElementById('nbadge-pend').textContent=pend>0?pend:'';document.getElementById('nbadge-pend').style.display=pend>0?'flex':'none';}
async function loadCfg(){try{const c=await apiFetch('/api/config');document.getElementById('p-sl').textContent=c.atm_sl+'×ATR';document.getElementById('p-tp').textContent=c.atr_tp+'×ATR';document.getElementById('p-mt').textContent=c.max_trades;document.getElementById('p-mc').textContent=c.min_conf+'/7';}catch(_){}updCfgBtns();}
function updCfgBtns(){if(!_st)return;document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('on',b.dataset.mode===_st.mode));document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('on',b.dataset.tf===_st.timeframe));}
async function setMode(m){try{await apiFetch('/api/mode',{method:'POST',body:JSON.stringify({mode:m})});await loadDash();}catch(e){alert('Erro: '+e.message);}}
async function setTf(t){try{await apiFetch('/api/timeframe',{method:'POST',body:JSON.stringify({timeframe:t})});await loadDash();}catch(e){alert('Erro: '+e.message);}}
async function resetPausa(){if(!confirm('Resetar Circuit Breaker?'))return;try{await apiFetch('/api/resetpausa',{method:'POST'});await loadDash();}catch(e){alert('Erro: '+e.message);}}
window.addEventListener('load',()=>{loadDash();loadPending();loadTrends();setInterval(()=>{loadDash();},30000);setInterval(()=>{if(document.querySelector('.pg.on').id==='pg-pend')loadPending();if(document.querySelector('.pg.on').id==='pg-trends')loadTrends();},10000);});
</script>
</body>
</html>
"""

# ═══════════════════════════════════════════════════════════════
# FLASK API
# ═══════════════════════════════════════════════════════════════
def create_api(bot):
    app = Flask(__name__)
    CORS(app)
    @app.after_request
    def cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
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
    def api_health(): return jsonify({"status": "ok", "version": "7.3"})

    @app.route("/api/status")
    def api_status():
        total = bot.wins + bot.losses
        wr    = round(bot.wins/total*100, 1) if total > 0 else 0
        trades_out = []
        for t in bot.active_trades:
            try: 
                res = get_analysis(t["symbol"], bot.timeframe); cur = res["price"] if res else t["entry"]            
            except: 
                cur = t["entry"]
            pnl = (cur-t["entry"])/t["entry"]*100
            if t["dir"] == "SELL": pnl = -pnl
            trades_out.append({"symbol": t["symbol"], "name": t.get("name", ""), "dir": t["dir"],
                 "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
                 "current": cur, "pnl": round(pnl,2), "opened_at": t.get("opened_at", "")})
        return jsonify({
            "wins": bot.wins, "losses": bot.losses, "winrate": wr,
            "consecutive_losses": bot.consecutive_losses, "mode": bot.mode, "timeframe": bot.timeframe,
            "paused": bot.is_paused(), "cb_mins": max(0,int((bot.paused_until-time.time())/60)) if bot.is_paused() else 0,
            "active_trades": trades_out,
            "markets": {cat: mkt_open(cat) for cat in Config.MARKET_CATEGORIES.keys()},
            "pending_count": len([o for o in bot.pending_operations if o["status"] == "PENDING"]),
        })

    @app.route("/api/config")
    def api_config():
        return jsonify({"atm_sl": Config.ATR_MULT_SL, "atr_tp": Config.ATR_MULT_TP,
                         "max_trades": Config.MAX_TRADES, "min_conf": Config.MIN_CONFLUENCE})

    @app.route("/api/pending")
    def api_pending():
        return jsonify(bot.pending_operations)

    @app.route("/api/trends")
    def api_trends():
        trends = []
        for sym, cache in bot.trend_cache.items():
            if cache.get("data"):
                d = cache["data"]
                sc, _, _ = calc_confluence(d, d["cenario"].replace("NEUTRO","ALTA"))
                trends.append({
                    "symbol": sym, "name": asset_name(sym), "price": fmt(d["price"]),
                    "dir": d["cenario"], "rsi": d["rsi"], "adx": d["adx"],
                    "score": sc, "ts": cache["ts"]
                })
        trends.sort(key=lambda x: x["ts"], reverse=True)
        return jsonify(trends[:20])

    @app.route("/api/confirm", methods=["POST", "OPTIONS"])
    def api_confirm():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        bot.confirm_pending_operation(data.get("op_id", ""))
        return jsonify({"ok": True})

    @app.route("/api/ignore", methods=["POST", "OPTIONS"])
    def api_ignore():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}        
        bot.ignore_pending_operation(data.get("op_id", ""))
        return jsonify({"ok": True})

    @app.route("/api/mode", methods=["POST", "OPTIONS"])
    def api_mode():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        mode = data.get("mode", "")
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]: return jsonify({"error": "inválido"}),400
        bot.set_mode(mode); return jsonify({"ok": True})

    @app.route("/api/timeframe", methods=["POST", "OPTIONS"])
    def api_timeframe():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        tf = data.get("timeframe", "")
        if tf not in Config.TIMEFRAMES: return jsonify({"error": "inválido"}),400
        bot.set_timeframe(tf); return jsonify({"ok": True})

    @app.route("/api/resetpausa", methods=["POST", "OPTIONS"])
    def api_reset():
        if request.method == "OPTIONS": return jsonify({}), 200
        bot.reset_pause(); return jsonify({"ok": True})

    @app.route("/api/vapid-public-key")
    def api_vapid_key():
        key = os.getenv("VAPID_PUBLIC_KEY", "")
        return jsonify({"key": key})

    @app.route("/api/subscribe", methods=["POST", "OPTIONS"])
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
# LOOP DO BOT & MAIN
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
                        txt = u["message"].get("text", "").strip().lower()
                        if txt in ("/noticias", "/news"): bot.send_news()
                        elif txt == "/status": bot.send_status()
                        elif txt in ("/placar", "/score"): bot.send_placar()
                        elif txt in ("/menu", "/start"): bot.build_menu()
                        elif txt == "/resetpausa": bot.reset_pause()
                        elif txt == "/pending": bot.send_pending_count()
                    if "callback_query" in u:
                        cb = u["callback_query"]["data"]; cid = u["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery",
                                      json={"callback_query_id": cid}, timeout=5)
                        if cb.startswith("set_tf_"): bot.set_timeframe(cb.replace("set_tf_", ""))
                        elif cb.startswith("set_"): bot.set_mode(cb.replace("set_", ""))
                        elif cb == "tf_menu": bot.build_tf_menu()
                        elif cb == "main_menu": bot.build_menu()
                        elif cb == "news": bot.send_news()
                        elif cb == "status": bot.send_status()
                        elif cb == "placar": bot.send_placar()
                        elif cb == "pending": bot.send_pending_count()
            bot.update_trends_cache()
            bot.maybe_send_news()
            bot.scan()
            bot.scan_reversal_forex()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)
        except Exception as e:
            log(f"Erro loop: {e}"); time.sleep(10)

def main():
    log("🔌 Bot Sniper v7.3 — Tendências RT + Cópia Individual + Calculadora")
    try: requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=8)
    except: pass
    bot = TradingBot()
    load_state(bot)
    t = threading.Thread(target=bot_loop, args=(bot,), daemon=True)
    t.start()
    run_api(bot)

if __name__ == "__main__":
    main()
