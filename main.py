# -- coding: utf-8 --
"""
BOT SNIPER v7.1 PRO — Dashboard Profissional + Gestão de Trades em Tempo Real
═══════════════════════════════════════════════════════════════════════════════
MELHORIAS APLICADAS:
✅ Persistência de Sinais: signals_feed salvo/restaurado (corrige sinais sumindo)
✅ Tendências: Agrupadas por categoria + Cores ALTA/BAIXA
✅ Contra-Tendência: Cards organizados, força, motivos e visual profissional
✅ Notificações: Botão de ativação no Config + Lógica de inscrição
✅ Sinais: Feed visual melhorado com ícones e tipos
✅ Resto do programa 100% preservado
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
    ATR_MULT_SL = 1.5; ATR_MULT_TP = 3.0; ATR_MULT_TRAIL = 1.2
    MAX_CONSECUTIVE_LOSSES = 2; PAUSE_DURATION = 3600
    ADX_MIN = 22; MAX_TRADES = 3; ASSET_COOLDOWN = 3600; MIN_CONFLUENCE = 5
    MIN_CONFLUENCE_CT = 4; REVERSAL_COOLDOWN = 2700
    RADAR_COOLDOWN = 1800; GATILHO_COOLDOWN = 300
    TRENDS_INTERVAL = 120; NEWS_INTERVAL = 7200; SCAN_INTERVAL = 30
    TIMEFRAMES = { "1m": ("Agressivo", "7d"), "5m": ("Alto", "5d"), "15m": ("Moderado", "5d"),                   "30m": ("Conservador", "5d"), "1h": ("Seguro", "60d"), "4h": ("Muito Seguro", "60d") }
    TIMEFRAME = "15m"
    FOREX_OPEN_UTC = 7; FOREX_CLOSE_UTC = 17
    COMM_OPEN_UTC  = 7; COMM_CLOSE_UTC  = 21
    IDX_OPEN_UTC   = 7; IDX_CLOSE_UTC   = 21
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
        "pending_trades": bot.pending_trades,
        "pending_counter": bot.pending_counter,
        "radar_list": bot.radar_list, "gatilho_list": bot.gatilho_list,
        "reversal_list": bot.reversal_list, "asset_cooldown": bot.asset_cooldown,
        "history": bot.history,
        "signals_feed": bot.signals_feed  # ✅ ADICIONADO: Persistência de sinais
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
        bot.wins = data.get("wins", 0); bot.losses = data.get("losses", 0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until = data.get("paused_until", 0)
        bot.active_trades = data.get("active_trades", [])
        bot.pending_trades = data.get("pending_trades", [])
        bot.pending_counter = data.get("pending_counter", 0)
        bot.radar_list = data.get("radar_list", {}); bot.gatilho_list = data.get("gatilho_list", {})
        bot.reversal_list = data.get("reversal_list", {}); bot.asset_cooldown = data.get("asset_cooldown", {})
        bot.history = data.get("history", [])
        bot.signals_feed = data.get("signals_feed", [])  # ✅ ADICIONADO: Restaurar sinais
        
        for t in bot.active_trades: t["session_alerted"] = False
        for t in bot.pending_trades: t["session_alerted"] = False
        log(f"[STATE] {bot.wins}W/{bot.losses}L | {len(bot.active_trades)} trade(s) | {len(bot.pending_trades)} pendente(s) | {len(bot.signals_feed)} sinal(is)")
        if bot.active_trades:
            lines = ["♻️ BOT REINICIADO – TRADES ATIVOS\n"]
            for t in bot.active_trades:
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                lines.append(f"📌 {t['symbol']} {dl} | Entrada: `{fmt(t['entry'])}` | TP: `{fmt(t['tp'])}` | SL: `{fmt(t['sl'])}`")
            bot._restore_msg = "\n".join(lines)
        else: bot._restore_msg = None
    except Exception as e: log(f"[STATE] Erro: {e}")
# ═══════════════════════════════════════════════════════════════
# NOTÍCIAS / FEAR & GREED
# ═══════════════════════════════════════════════════════════════
RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"), ("Cointelegraph", "https://cointelegraph.com/rss"),
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
            title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "  ").strip()
            link  = (item.findtext("link")  or item.findtext("{http://www.w3.org/2005/Atom}link")  or "  ").strip()
            if title and link: out.append({"title": title, "url": link, "source": src})
        return out
    except: return []

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
    except: return {"value": "N/D", "label": " "}

def build_news_msg():
    arts = get_news(5); fg = get_fear_greed()
    lines = ["📰 NOTÍCIAS\n"]
    for i, a in enumerate(arts, 1):
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else " ")
        lines.append(f"{i}. <a href='{a['url']}'>{t} ({a['source']})")
    lines.append(f"\n😱 F&G: {fg['value']} – {fg['label']}")
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
# MOTOR DE ANÁLISE PRINCIPAL
# ═══════════════════════════════════════════════════════════════def get_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, (" ", "5d"))[1]
    use_vol = vol_reliable(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 50: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]; volume = df["Volume"]
        ema9   = closes.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]
        w = min(20, len(closes)-1)
        sma20 = closes.rolling(w).mean().iloc[-1]; std20 = closes.rolling(w).std().iloc[-1]
        upper = sma20 + std20*2; lower = sma20 - std20*2
        delta = closes.diff()
        gain  = delta.where(delta>0, 0).rolling(14).mean()
        loss  = (-delta.where(delta<0, 0)).rolling(14).mean()
        rsi   = (100 - 100/(1 + gain/loss)).iloc[-1]
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        ml    = ema12 - ema26; mh = ml - ml.ewm(span=9, adjust=False).mean()
        macd_bull = bool(mh.iloc[-1] > 0 and mh.iloc[-1] > mh.iloc[-2])
        macd_bear = bool(mh.iloc[-1] < 0 and mh.iloc[-1] < mh.iloc[-2])
        if use_vol and volume.sum() > 0:
            va = volume.rolling(20).mean().iloc[-1]; vc = volume.iloc[-1]
            vol_ok = bool(vc > va) if va > 0 else False; vol_ratio = float(vc/va) if va > 0 else 0
        else: vol_ok = True; vol_ratio = 0
        tr  = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd>0)&(hd>-ld), 0.0); mdm = (-ld).where((-ld>0)&(-ld>hd), 0.0)
        as_ = tr.ewm(alpha=1/14, adjust=False).mean()
        pdi = 100*pdm.ewm(alpha=1/14, adjust=False).mean()/(as_+1e-10)
        mdi = 100*mdm.ewm(alpha=1/14, adjust=False).mean()/(as_+1e-10)
        dx  = 100*(pdi-mdi).abs()/(pdi+mdi+1e-10)
        adx = float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
        price = float(closes.iloc[-1])
        chg   = float((closes.iloc[-1]-closes.iloc[-10])/closes.iloc[-10]*100) if len(closes)>=10 else 0
        cen   = "NEUTRO"
        if price > ema200 and ema9 > ema21: cen = "ALTA"
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
        checks = [("EMA 200 acima", res["price"] > res["ema200"]), ("EMA 9 > 21", res["ema9"] > res["ema21"]),
                  ("MACD Alta", res["macd_bull"]), ("Volume OK", res["vol_ok"]), ("RSI < 65", res["rsi"] < 65),
                  ("TF Superior Alta", res["h1_bull"]), ("ADX tendência", res["adx"] > Config.ADX_MIN)]
    else:
        checks = [("EMA 200 abaixo", res["price"] < res["ema200"]), ("EMA 9 < 21", res["ema9"] < res["ema21"]),
                  ("MACD Baixa", res["macd_bear"]), ("Volume OK", res["vol_ok"]), ("RSI > 35", res["rsi"] > 35),
                  ("TF Superior Baixa", res["h1_bear"]), ("ADX tendência", res["adx"] > Config.ADX_MIN)]
    sc = sum(1 for _, ok in checks if ok)
    return sc, len(checks), checks

def cbar(sc, tot):
    f = math.floor(sc/tot*5)
    return "█"*f + "░"*(5-f)

# ═══════════════════════════════════════════════════════════════
# MOTOR DE CONTRA-TENDÊNCIA (FOREX)
# ═══════════════════════════════════════════════════════════════
def detect_candle_patterns(df):
    if len(df) < 3: return False, False, " "
    o1,h1,l1,c1 = df["Open"].iloc[-2],df["High"].iloc[-2],df["Low"].iloc[-2],df["Close"].iloc[-2]
    o0,h0,l0,c0 = df["Open"].iloc[-1],df["High"].iloc[-1],df["Low"].iloc[-1],df["Close"].iloc[-1]
    body0 = abs(c0-o0); rng0 = h0-l0 or 1e-10
    uw = h0-max(c0,o0); lw = min(c0,o0)-l0
    pb = pb2 = False; nm = " "
    if (c0>o0) and (c1<o1) and c0>o1 and o0<c1: pb=True; nm="Engolfo de Alta"
    elif (c0<o0) and (c1>o1) and c0<l1: pb2=True; nm="Engolfo de Baixa"
    elif lw>body0*2 and uw<body0*0.5 and body0<rng0*0.4: pb=True; nm="Martelo"
    elif uw>body0*2 and lw<body0*0.5 and body0<rng0*0.4:
        pb2=True; nm="Estrela Cadente"
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
        div_bear = bool(rh > ph and rsi < rsi_s.iloc[-lb10*2:-lb10].max() and rsi > 55)
        div_bull = bool(rl < pl and rsi > rsi_s.iloc[-lb10*2:-lb10].min() and rsi < 45)
        mdiv_bear = bool(closes.iloc[-1]>closes.iloc[-3] and mh.iloc[-1]<mh.iloc[-3])
        mdiv_bull = bool(closes.iloc[-1]<closes.iloc[-3] and mh.iloc[-1]>mh.iloc[-3])
        rng0 = highs.iloc[-1]-lows.iloc[-1] or 1e-10
        uw = highs.iloc[-1]-max(closes.iloc[-1],df["Open"].iloc[-1])
        lw = min(closes.iloc[-1],df["Open"].iloc[-1])-lows.iloc[-1]
        pb, pb2, pnm = detect_candle_patterns(df)
        near_up = price >= ub*0.998; near_dn = price <= lb*1.002
        rsi_ob = rsi > 75; rsi_os = rsi < 25
        sig_sell = near_up or rsi_ob or div_bear or mdiv_bear
        sig_buy  = near_dn or rsi_os or div_bull or mdiv_bull
        if not (sig_sell or sig_buy): return None
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price, "rsi": rsi, "atr": atr, "adx": adx, "adx_mature": adx>30,
            "upper_band": ub, "lower_band": lb, "near_upper": near_up, "near_lower": near_dn,
            "rsi_overbought": rsi_ob, "rsi_oversold": rsi_os, "div_bear": div_bear, "div_bull": div_bull,            "macd_div_bear": mdiv_bear, "macd_div_bull": mdiv_bull, "wick_bear": bool(uw>rng0*0.5),
            "wick_bull": bool(lw>rng0*0.5), "pat_bull": pb, "pat_bear": pb2, "pat_name": pnm,
            "signal_sell_ct": sig_sell, "signal_buy_ct": sig_buy,
        }
    except Exception as e: log(f"[CT] {symbol}: {e}"); return None

def calc_reversal_conf(res, d):
    if d == "SELL":
        checks = [("RSI sobrecomprado", res["rsi_overbought"]), ("Banda Superior BB", res["near_upper"]),
                  ("RSI div. bearish", res["div_bear"]), ("MACD div. bearish", res["macd_div_bear"]),
                  ("Candle de baixa", res["pat_bear"]), ("Wick superior", res["wick_bear"]), ("ADX maduro", res["adx_mature"])]
    else:
        checks = [("RSI sobrevendido", res["rsi_oversold"]), ("Banda Inferior BB", res["near_lower"]),
                  ("RSI div. bullish", res["div_bull"]), ("MACD div. bullish", res["macd_div_bull"]),
                  ("Candle de alta", res["pat_bull"]), ("Wick inferior", res["wick_bull"]), ("ADX maduro", res["adx_mature"])]
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
        priv_key = os.getenv("VAPID_PRIVATE_KEY", ""); pub_key = os.getenv("VAPID_PUBLIC_KEY", "")
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
        self.paused_until = 0; self.active_trades = []; self.pending_trades = []
        self.pending_counter = 0; self.radar_list = {}; self.gatilho_list = {}
        self.reversal_list = {}; self.asset_cooldown = {}; self.history = []
        self.last_id = 0; self.last_news_ts = 0; self._restore_msg = None
        self.trend_cache = {}; self.last_trends_update = 0
        self.signals_feed = []; self.news_cache = []; self.news_cache_ts = 0

    def send(self, text, markup=None, disable_preview=False):
        import re
        clean = re.sub(r"<[^>]+>", " ", text).strip()
        tipo = push_title = push_body = None
        if "RADAR" in text: tipo="radar"; push_title="⚠ RADAR"
        elif "GATILHO ATINGIDO" in text: tipo="gatilho"; push_title="🔔 GATILHO ATINGIDO!"
        elif "SINAL CONFIRMADO" in text: tipo="sinal"; push_title="🎯 SINAL CONFIRMADO!"
        elif "SINAL PENDENTE" in text: tipo="sinal"; push_title="🎯 SINAL PENDENTE!"
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
    def send_pending_notification(self, t):
        dl = "COMPRAR (BUY) 🟢" if t["dir"]=="BUY" else "VENDER (SELL) 🔴"
        sl_pct = abs(t["entry"]-t["sl"])/t["entry"]*100
        tp_pct = abs(t["tp"]-t["entry"])/t["entry"]*100
        is_ct = "CONTRA-TENDÊNCIA" in (t.get("tipo") or " ")
        header = "⚡ SINAL CT PENDENTE" if is_ct else "🎯 SINAL PENDENTE"
        text = (f"{header} – <b>{t['symbol']}</b> ({t['name']})\nAguardando sua confirmação…\n\n▶️ <b>{dl}</b>\n\n"
                f"💰 <b>Entrada:</b> <code>{fmt(t['entry'])}</code>\n🛡 <b>SL:</b> <code>{fmt(t['sl'])}</code> ({-sl_pct:.2f}%)\n"
                f"🎯 <b>TP:</b> <code>{fmt(t['tp'])}</code> ({tp_pct:+.2f}%)\n\n")
        if is_ct and t.get("sinais"): text += "<b>Sinais de exaustão:</b>\n" + "\n".join(f"   ⚡ {sg}" for sg in t["sinais"]) + "\n\n"
        if t.get("conf_txt"): text += f"<b>Confluência: {t.get('sc','')}/{t.get('tot_c',t.get('tc',''))} [{t['bar']}]</b>\n{t['conf_txt']}"
        markup = {"inline_keyboard": [[{"text": "✅ Aceitar", "callback_data": f"confirm_{t['pending_id']}"}, {"text": "❌ Recusar", "callback_data": f"reject_{t['pending_id']}"}]]}
        self.send(text, markup=markup)

    def confirm_pending(self, pending_id):
        for t in self.pending_trades[:]:
            if t.get("pending_id") == pending_id:
                self.pending_trades.remove(t)
                trade = {k: v for k, v in t.items() if k not in ("conf_txt", "sc", "tot_c", "tc", "bar", "ratio", "vol_txt", "sinais", "pending_id")}
                self.active_trades.append(trade); save_state(self)
                dl = "BUY 🟢" if t["dir"]=="BUY" else "SELL 🔴"
                self.send(f"✅ <b>TRADE CONFIRMADO – {t['symbol']}</b>\n{dl} | Entrada: <code>{fmt(t['entry'])}</code>\nSL: <code>{fmt(t['sl'])}</code> | TP: <code>{fmt(t['tp'])}</code>")
                return True
        return False

    def reject_pending(self, pending_id):
        for t in self.pending_trades[:]:
            if t.get("pending_id") == pending_id:
                self.pending_trades.remove(t); save_state(self)
                self.send(f"❌ <b>TRADE RECUSADO – {t['symbol']}</b>\nSinal ignorado.")
                return True
        return False

    def build_menu(self):
        tfl = Config.TIMEFRAMES.get(self.timeframe, ("?", " "))[0]
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
        cb = f"\n⛔ CB – retoma em {int((self.paused_until-time.time())/60)}min " if self.is_paused() else " "
        self.send(f"<b>BOT SNIPER v7.1 PRO</b>\n{self.wins}W / {self.losses}L ({wr:.1f}%)\nModo: {ml} | TF: {self.timeframe}{cb}", markup)
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
            res = get_analysis(t["symbol"], self.timeframe); cur = res["price"] if res else t["entry"]
            pnl = (cur-t["entry"])/t["entry"]*100
            if t["dir"] == "SELL": pnl = -pnl
            lines.append(f"{'🟢' if pnl>=0 else '🔴'} {t['symbol']} {t['dir']} P&L: {pnl:+.2f}%")
        self.send("\n".join(lines))

    def send_placar(self):
        tot = self.wins+self.losses; wr = (self.wins/tot*100) if tot>0 else 0
        self.send(f"🏆 W/L: {self.wins}/{self.losses} ({wr:.1f}%)")

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
                    self.trend_cache[s] = {"data": res, "reversal": {"has":rev[0], "dir":rev[1], "strength":rev[2], "reasons":rev[3]}, "ts": time.time()}
            except Exception as e: log(f"[TRENDS] {s}: {e}")
        self.last_trends_update = time.time()

    def scan(self):
        if self.is_paused(): return
        if len(self.active_trades) >= Config.MAX_TRADES: return
        universe = all_syms() if self.mode == "TUDO" else list(Config.MARKET_CATEGORIES[self.mode]["assets"].keys())
        for s in universe:
            cat = asset_cat(s)
            if not mkt_open(cat): continue
            if any(t["symbol"] == s for t in self.active_trades): continue
            if any(t["symbol"] == s for t in self.pending_trades): continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
            res = self.trend_cache.get(s, {}).get("data") or get_analysis(s, self.timeframe)
            if not res: continue
            if s not in self.trend_cache:
                rev = detect_reversal(res)
                self.trend_cache[s] = {"data": res, "reversal": {"has":rev[0], "dir":rev[1], "strength":rev[2], "reasons":rev[3]}, "ts": time.time()}
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
                    dist = abs(price-gatilho)/price*100; dl = "COMPRA" if dir_s=="BUY" else "VENDA"
                    self.send(f"⚠️ <b>RADAR – {s}</b> ({res['name']})\n{cl_lbl} | TF: <code>{self.timeframe}</code>\n\nTendência de <b>{cen}</b> detectada\nAguardando gatilho de <b>{dl}</b>\n\n🎯 Gatilho: <code>{fmt(gatilho)}</code>\n📍 Atual: <code>{fmt(price)}</code> ({dist:.2f}%)\n🛡 SL est.: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n🎯 TP est.: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n⚖️ Ratio: <b>{ratio}</b>\nRSI: <code>{res['rsi']:.1f}</code> | ADX: <code>{res['adx']:.1f}</code>")
                    self.radar_list[s] = time.time()
                continue
            if time.time() - self.gatilho_list.get(s, 0) > Config.GATILHO_COOLDOWN:
                dl = "COMPRAR (BUY) 🟢" if dir_s=="BUY" else "VENDER (SELL) 🔴"
                self.send(f"🔔 <b>GATILHO ATINGIDO – {s}</b> ({res['name']})\n{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n✅ Preço chegou no nível de entrada!\n\n▶️ <b>AÇÃO: {dl}</b>\n\n💰 Entrada: <code>{fmt(price)}</code>\n🛡 SL: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n🎯 TP: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n⚖️ Ratio: <b>{ratio}</b>\n\n⏳ <i>Verificando confluência…</i>")
                self.gatilho_list[s] = time.time()
            sc, tot_c, checks = calc_confluence(res, dir_s); bar = cbar(sc, tot_c)
            conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)
            if sc < Config.MIN_CONFLUENCE:
                falhou = [nm for nm, ok in checks if not ok]
                self.send(f"⚡ <b>CONFLUÊNCIA INSUF. – {s}</b>\n\nGatilho atingido mas bot NÃO entrou.\nScore: <code>{sc}/{tot_c}</code> [{bar}] (min: {Config.MIN_CONFLUENCE})\n\n<b>Filtros que falharam:</b>\n" + "\n".join(f"   ❌ {nm}" for nm in falhou)); continue
            if dir_s == "BUY": sl = price - Config.ATR_MULT_SL * atr; tp = price + Config.ATR_MULT_TP * atr
            else: sl = price + Config.ATR_MULT_SL * atr; tp = price - Config.ATR_MULT_TP * atr
            sl_pct = abs(price-sl)/price*100; tp_pct = abs(tp-price)/price*100
            dl = "COMPRAR (BUY) 🟢" if dir_s=="BUY" else "VENDER (SELL) 🔴"
            vol_txt = f"{res['vol_ratio']:.1f}x média" if res["vol_ratio"]>0 else "N/A"
            self.pending_counter += 1
            pending_trade = {"pending_id": self.pending_counter, "symbol": s, "name": res["name"], "entry": price,
                 "tp": tp, "sl": sl, "dir": dir_s, "peak": price, "atr": atr,
                 "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"), "session_alerted": True,
                 "conf_txt": conf_txt, "sc": sc, "tot_c": tot_c, "bar": bar, "ratio": ratio, "vol_txt": vol_txt}
            self.pending_trades.append(pending_trade)
            self.send_pending_notification(pending_trade)
            self.radar_list[s] = self.gatilho_list[s] = time.time()
            save_state(self)

    def scan_reversal_forex(self):
        if self.is_paused(): return
        if not mkt_open("FOREX"): return
        if len(self.active_trades) >= Config.MAX_TRADES: return
        for s in Config.MARKET_CATEGORIES["FOREX"]["assets"].keys():
            if any(t["symbol"] == s for t in self.active_trades): continue
            if any(t["symbol"] == s for t in self.pending_trades): continue
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
            conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in ch)
            sl_m = Config.ATR_MULT_SL; tp_m = Config.ATR_MULT_SL * 1.5
            if dir_s == "BUY": sl = price - sl_m*atr; tp = price + tp_m*atr
            else: sl = price + sl_m*atr; tp = price - tp_m*atr
            sl_p = abs(price-sl)/price*100; tp_p = abs(tp-price)/price*100
            ratio = f"1:{tp_m/sl_m:.1f}"; dl = "COMPRAR (BUY) 🟢" if dir_s=="BUY" else "VENDER (SELL) 🔴"
            sinais_txt = "\n".join(f"   ⚡ {sg}" for sg in sinais)
            self.pending_counter += 1
            pending_trade = {"pending_id": self.pending_counter, "symbol": s, "name": res["name"], "entry": price,
                 "tp": tp, "sl": sl, "dir": dir_s, "peak": price, "atr": atr, "tipo": "CONTRA-TENDÊNCIA ⚡",
                 "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"), "session_alerted": True,
                 "conf_txt": conf_txt, "sc": sc, "tc": tc, "bar": bar, "ratio": ratio, "sinais": sinais}
            self.pending_trades.append(pending_trade)
            self.send_pending_notification(pending_trade)
            self.reversal_list[s] = time.time()
            save_state(self)

    def monitor_trades(self):
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res: continue
            cur = res["price"]; atr = res["atr"]
            if not t.get("session_alerted", True):
                dl = "BUY 🟢" if t["dir"]=="BUY" else "SELL 🔴"
                sl_p = abs(t["entry"]-t["sl"])/t["entry"]*100; tp_p = abs(t["tp"]-t["entry"])/t["entry"]*100
                self.send(f"📌 <b>TRADE RESTAURADO – {t['symbol']}</b>\nAção: <b>{dl}</b> | Aberto: {t.get('opened_at','?')}\nEntrada: <code>{fmt(t['entry'])}</code> | Atual: <code>{fmt(cur)}</code>\n🎯 TP: <code>{fmt(t['tp'])}</code> ({tp_p:+.2f}%)\n🛡 SL: <code>{fmt(t['sl'])}</code> ({-sl_p:.2f}%)")
                t["session_alerted"] = True; changed = True
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
                if is_win: self.wins += 1; self.consecutive_losses = 0
                else: self.losses += 1; self.consecutive_losses += 1; self.asset_cooldown[t["symbol"]] = time.time()
                self.history.append({"symbol": t["symbol"], "dir": t["dir"], "result": "WIN" if is_win else "LOSS", "pnl": round(pnl,2), "closed_at": closed_at})
                self.send(f"🏁 <b>OPERAÇÃO ENCERRADA</b>\nAtivo: <b>{t['symbol']}</b> ({t.get('name','')}) | {t['dir']}\nResultado: <b>{st}</b>\n\n💰 Entrada: <code>{fmt(t['entry'])}</code>\n🔚 Saída: <code>{fmt(cur)}</code>\nP&L: <code>{pnl:+.2f}%</code>")
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
e.waitUntil(self.registration.showNotification(data.title, {body: data.body, icon: data.icon || '/icon-192.png',
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
# DASHBOARD HTML (PROFISSIONAL v7.1 - ATUALIZADO)
# ═══════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Sniper Bot Pro</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{--bg:#04070f;--bg2:#080e1a;--bg3:#0d1525;--bg4:#111d30;--bg5:#1a2a45;--text:#c8dcf0;--text2:#8aaccf;--muted:#3d5f85;--muted2:#5577a0;--border:rgba(255,255,255,0.055);--border2:rgba(255,255,255,0.09);--green:#00e676;--green2:#00c853;--g3:rgba(0,230,118,.1);--g4:rgba(0,230,118,.06);--red:#ff3d71;--red2:#d50000;--r3:rgba(255,61,113,.1);--r4:rgba(255,61,113,.06);--gold:#ffd740;--gold2:#ffc400;--y3:rgba(255,215,64,.12);--y4:rgba(255,215,64,.06);--cyan:#18ffff;--cyan2:#00e5ff;--c3:rgba(24,255,255,.1);--blue:#448aff;--blue2:#2979ff;--b3:rgba(68,138,255,.1);--orange:#ff6d00;--mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif;--r:14px;--rsm:9px;--r2:20px;--nav:64px;--safe:env(safe-area-inset-bottom,0px);--head:58px;--shadow:0 2px 12px rgba(0,0,0,.45);--shadow-lg:0 4px 28px rgba(0,0,0,.55)}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:var(--sans);-webkit-font-smoothing:antialiased}
#app{display:flex;flex-direction:column;height:100%;max-width:480px;margin:0 auto}
#hdr{height:var(--head);flex-shrink:0;background:linear-gradient(180deg,rgba(8,14,26,.98),rgba(4,7,15,.96));backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid var(--border2);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:100}
.hdr-l{display:flex;align-items:center;gap:10px}
.logo{width:38px;height:38px;border-radius:11px;background:linear-gradient(135deg,#00c853,#00e5ff);display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:18px;font-weight:700;color:#000;box-shadow:0 0 0 1px rgba(0,230,118,.25),0 0 18px rgba(0,200,83,.25);flex-shrink:0}
.t1{font-size:15px;font-weight:700;letter-spacing:-.3px}.t2{font-size:9px;color:var(--muted2);letter-spacing:1.5px;text-transform:uppercase;margin-top:1px}
.hdr-r{display:flex;align-items:center;gap:8px}
.lpill{display:flex;align-items:center;gap:5px;background:rgba(0,230,118,.08);border:1px solid rgba(0,230,118,.18);border-radius:20px;padding:4px 10px;font-size:9px;color:var(--green);letter-spacing:1px;text-transform:uppercase;font-weight:600}
.ldot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:blink 2s ease-in-out infinite;box-shadow:0 0 5px var(--green)}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
.ibtn{width:36px;height:36px;border-radius:10px;border:1px solid var(--border2);background:var(--bg3);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:16px;transition:all .15s;color:var(--text2)}
.ibtn:active{background:var(--bg4);transform:scale(.9)}
#pages{flex:1;overflow:hidden;position:relative}
.pg{position:absolute;inset:0;display:none;overflow-y:auto;padding:14px 14px calc(var(--nav) + var(--safe) + 14px);opacity:0;transform:translateY(6px);transition:opacity .22s,transform .22s}
.pg.on{display:block;opacity:1;transform:translateY(0)}
.pg::-webkit-scrollbar{width:2px}.pg::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
#nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:480px;height:var(--nav);background:rgba(8,14,26,.97);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-top:1px solid var(--border2);display:flex;z-index:200;padding-bottom:var(--safe)}
.nb{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:none;background:none;cursor:pointer;font-size:9px;color:var(--muted2);letter-spacing:.5px;text-transform:uppercase;padding:0;transition:all .2s;position:relative;font-family:var(--sans);font-weight:500}
.nb .ni{font-size:20px;transition:all .2s;opacity:.55}
.nb.on{color:var(--green)}.nb.on .ni{transform:scale(1.1);opacity:1;filter:drop-shadow(0 0 5px var(--green))}
.nb:active{opacity:.65}
.nbadge{position:absolute;top:5px;right:calc(50% - 19px);min-width:16px;height:16px;border-radius:8px;background:var(--red);color:#fff;font-size:9px;display:none;align-items:center;justify-content:center;font-family:var(--mono);font-weight:700;padding:0 3px;box-shadow:0 0 8px rgba(255,61,113,.5)}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:10px}
.chd{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;font-weight:600}.srow{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:12px}
.sb{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:12px 10px;position:relative;overflow:hidden}
.sb.pnl-card{border-bottom:2px solid rgba(0,230,118,.4)}
.sb.wr-card{border-bottom:2px solid rgba(24,255,255,.4)}
.sb.open-card{border-bottom:2px solid rgba(68,138,255,.4)}
.sb.closed-card{border-bottom:2px solid rgba(255,215,64,.4)}
.sl{font-size:8px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:5px;font-weight:600}
.sv{font-size:22px;font-weight:800;font-family:var(--mono);line-height:1}
.ss{font-size:9px;color:var(--muted2);margin-top:4px}
.g{color:var(--green)}.r{color:var(--red)}.go{color:var(--gold)}.cy{color:var(--cyan)}.bl{color:var(--blue)}.or{color:var(--orange)}
.sh{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.sttl{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);display:flex;align-items:center;gap:6px;font-weight:600}
.dv{height:1px;background:var(--border);margin:16px 0}
.empty{text-align:center;padding:40px 20px;color:var(--muted)}
.empi{font-size:38px;margin-bottom:12px;display:block;opacity:.55}
.empt{font-size:12px;line-height:1.7;color:var(--muted2)}
.ts{font-size:9px;color:var(--muted);text-align:center;padding:8px 0;letter-spacing:.5px;font-family:var(--mono)}
.cbbar{background:rgba(255,61,113,.07);border:1px solid rgba(255,61,113,.18);border-radius:var(--rsm);padding:12px 14px;margin-bottom:12px;display:none;align-items:center;justify-content:space-between}
.cbtxt{font-size:11px;color:var(--red);font-weight:600}.cbmin{font-size:20px;font-family:var(--mono);font-weight:700;color:var(--red)}
.eb{background:rgba(255,61,113,.07);border:1px solid rgba(255,61,113,.18);border-radius:var(--rsm);padding:10px 12px;margin-bottom:10px;font-size:11px;color:var(--red);display:none}
.spin{animation:spin 1s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}

/* ═══ TRADE CARDS ══════════════════════════════ */
.otrade{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:10px;position:relative;overflow:hidden}
.otrade.buy{border-left:3px solid var(--green)}.otrade.sell{border-left:3px solid var(--red)}
.otrade-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.otrade-sym{font-size:16px;font-weight:700;font-family:var(--mono)}
.otrade-dir{font-size:10px;font-weight:700;padding:4px 10px;border-radius:20px;letter-spacing:.5px}
.otrade-dir.buy{background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.otrade-dir.sell{background:var(--r3);color:var(--red);border:1px solid rgba(255,61,113,.2)}
.otrade-lvls{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px}
.otrade-lv{background:var(--bg3);border-radius:var(--rsm);padding:8px;text-align:center}
.otrade-ll{font-size:7px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;font-weight:600}
.otrade-lvv{font-size:12px;font-weight:700;font-family:var(--mono)}
.otrade-pnl{font-size:18px;font-weight:800;font-family:var(--mono);margin-bottom:8px}
.otrade-prog{height:4px;background:var(--bg4);border-radius:2px;margin-bottom:8px;overflow:hidden}
.otrade-prog-fill{height:100%;border-radius:2px;transition:width .5s}
.otrade-dist{display:flex;justify-content:space-between;font-size:9px;color:var(--muted2);margin-top:4px}
.otrade-dist span{display:flex;align-items:center;gap:3px}
.otrade-dist .near{color:var(--red);font-weight:600}
.otrade-dist .far{color:var(--green)}

/* ═══ TRENDS GROUPED & COLORED ═══════════════════════════════════ */
.trend-group{margin-bottom:16px}
.trend-group-hd{font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);margin-bottom:8px;font-weight:700;display:flex;align-items:center;gap:6px}
.trend-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:12px;margin-bottom:8px;display:flex;align-items:center;justify-content:space-between}
.trend-card.alta{border-left:3px solid var(--green);background:linear-gradient(90deg,rgba(0,230,118,0.05),transparent)}
.trend-card.baixa{border-left:3px solid var(--red);background:linear-gradient(90deg,rgba(255,61,113,0.05),transparent)}
.trend-info{display:flex;flex-direction:column;gap:2px}.trend-sym{font-size:14px;font-weight:700;font-family:var(--mono)}
.trend-name{font-size:10px;color:var(--muted2)}
.trend-meta{display:flex;align-items:center;gap:8px}
.trend-tag{font-size:9px;font-weight:700;padding:2px 6px;border-radius:6px;text-transform:uppercase}
.trend-tag.alta{background:var(--g3);color:var(--green)}
.trend-tag.baixa{background:var(--r3);color:var(--red)}
.trend-tag.neutro{background:var(--bg3);color:var(--muted)}
.trend-stats{font-size:10px;color:var(--muted2);font-family:var(--mono)}

/* ═══ CONTRA-TENDÊNCIA CARDS ═══════════════════════════════════ */
.ct-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:10px;position:relative;overflow:hidden}
.ct-card::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%;background:var(--cyan)}
.ct-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.ct-sym{font-size:16px;font-weight:700;font-family:var(--mono)}
.ct-dir{font-size:10px;font-weight:700;padding:4px 8px;border-radius:8px;background:var(--c3);color:var(--cyan);border:1px solid rgba(24,255,255,.2)}
.ct-body{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.ct-stat{background:var(--bg3);border-radius:var(--rsm);padding:8px;text-align:center}
.ct-stat-lbl{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
.ct-stat-val{font-size:14px;font-weight:700;font-family:var(--mono)}
.ct-bar{height:6px;background:var(--bg4);border-radius:3px;overflow:hidden;margin-bottom:6px}
.ct-bar-fill{height:100%;background:var(--cyan);transition:width .5s}
.ct-reasons{display:flex;flex-wrap:wrap;gap:4px}
.ct-reason{font-size:9px;background:var(--bg3);color:var(--text2);padding:3px 6px;border-radius:6px;border:1px solid var(--border)}

/* ═══ SIGNALS FEED ═══════════════════════════════════ */
.sig-item{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:12px;margin-bottom:8px}
.sig-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px}
.sig-type{font-size:9px;font-weight:700;padding:3px 8px;border-radius:8px;text-transform:uppercase}
.sig-type.radar{background:var(--y3);color:var(--gold)}
.sig-type.gatilho{background:var(--c3);color:var(--cyan)}
.sig-type.sinal{background:var(--b3);color:var(--blue)}
.sig-type.ct{background:var(--r3);color:var(--red)}
.sig-type.close{background:var(--g3);color:var(--green)}
.sig-type.cb{background:var(--r3);color:var(--red)}
.sig-type.insuf{background:var(--bg3);color:var(--muted)}
.sig-ts{font-size:9px;color:var(--muted2);font-family:var(--mono)}
.sig-text{font-size:12px;color:var(--text);line-height:1.4}

/* ═══ CLOSED TRADES LIST ═══════════════════════════════════ */
.ctrow{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border)}
.ctrow:last-child{border-bottom:none}
.ctrow-left{display:flex;align-items:center;gap:8px}
.ctrow-icon{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px}
.ctrow-icon.win{background:var(--g3);color:var(--green)}
.ctrow-icon.loss{background:var(--r3);color:var(--red)}
.ctrow-info{display:flex;flex-direction:column}
.ctrow-sym{font-size:12px;font-weight:600;font-family:var(--mono)}
.ctrow-time{font-size:9px;color:var(--muted2)}
.ctrow-pnl{font-size:14px;font-weight:700;font-family:var(--mono)}
/* ═══ BOTTOM NAV & MISC ════════════════════════════════════ */
.mdg{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.mdb{background:var(--bg3);border:1px solid var(--border2);border-radius:var(--r);padding:14px 8px;cursor:pointer;font-size:12px;font-family:var(--sans);color:var(--text2);text-align:center;transition:all .15s;line-height:1.4;font-weight:500}
.mdb:active{transform:scale(.97)}.mdb.on{background:var(--g3);border:1px solid rgba(0,230,118,.3);color:var(--green)}
.mdi{font-size:22px;display:block;margin-bottom:4px}
.tfg{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
.tfb{background:var(--bg3);border:1px solid var(--border2);border-radius:var(--rsm);padding:11px 6px;cursor:pointer;font-size:11px;font-family:var(--mono);color:var(--text2);text-align:center;transition:all .15s;font-weight:600}
.tfb.on{background:var(--c3);border:1px solid rgba(24,255,255,.3);color:var(--cyan)}
.tfb:active{transform:scale(.97)}
.tfd{font-size:15px;display:block;margin-bottom:3px}.tfl2{font-size:8px;color:var(--muted);margin-top:2px;font-family:var(--sans);font-weight:500}
.ab{width:100%;padding:15px;border-radius:var(--r);border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:var(--sans);margin-bottom:8px;transition:all .15s;letter-spacing:.3px}
.ab:active{transform:scale(.98);opacity:.9}.abd{background:var(--r4);color:var(--red);border:1px solid rgba(255,61,113,.2)}
.abp{background:var(--g4);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.abn{background:var(--b3);color:var(--blue);border:1px solid rgba(68,138,255,.2)}
.pgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pbox{background:var(--bg3);border:1px solid var(--border);border-radius:var(--rsm);padding:12px}
.plbl{font-size:8px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:5px;font-weight:600}
.pval{font-size:16px;font-family:var(--mono);font-weight:700}
.cfgsec{margin-bottom:20px}
.cfgl{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted2);margin-bottom:10px;font-weight:600}
</style>
</head>
<body>
<div id="app">
<div id="hdr">
<div class="hdr-l">
<div class="logo">S</div>
<div>
<div class="t1">Sniper Bot Pro</div>
<div class="t2">Dashboard</div>
</div>
</div>
<div class="hdr-r">
<div class="lpill">LIVE<div class="ldot"></div></div>
<button class="ibtn" id="refbtn" onclick="refreshAll()">↻</button>
</div>
</div>
<div id="pages">
<div class="pg on" id="pg-dash">
<div id="eb" class="eb">⚠ Erro de conexão. Verifique sua rede.</div>
<div class="cbbar" id="cbbar"><div class="cbtxt">⛔ CIRCUIT BREAKER ATIVO</div><div class="cbmin" id="cbmin">--m</div></div>
<div class="srow">
<div class="sb pnl-card"><div class="sl">Lucro Hoje</div><div class="sv" id="d-dpnl">--%</div><div class="ss" id="d-drec">0W / 0L</div></div>
<div class="sb wr-card"><div class="sl">Win Rate</div><div class="sv" id="d-wr">--%</div><div class="ss" id="d-wlt">0W / 0L Total</div></div>
<div class="sb open-card"><div class="sl">Abertos</div><div class="sv" id="d-open">0</div><div class="ss">Monitorando</div></div>
<div class="sb closed-card"><div class="sl">Fechados Hoje</div><div class="sv" id="d-closed">0</div><div class="ss">Operações</div></div>
</div>
<div class="chd">💼 Trades Abertos <span class="ts">Auto: 10s</span></div>
<div id="d-trades"><div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto.<br>Aguardando aprovação...</div></div></div>
<div class="chd">📜 Fechados Hoje</div><div id="d-closed-list"><div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada hoje.</div></div></div>
</div>

<div class="pg" id="pg-pend">
<div class="chd">⏳ Aprovação de Sinais <span class="ts">Auto: 10s</span></div>
<div id="pendingQueue"><div class="empty"><span class="empi">✨</span><div class="empt">Nenhuma confirmação pendente</div></div></div>
</div>

<div class="pg" id="pg-scan">
<div class="chd">📡 Scanner Tempo Real <span class="ts">--</span></div>
<div id="scan-list"><div class="empty"><span class="empi">📡</span><div class="empt">Aguardando dados do scanner…</div></div></div>
</div>

<div class="pg" id="pg-sig">
<div class="chd">🔔 Feed de Sinais <span class="ts">--</span></div>
<div id="sig-list"><div class="empty"><span class="empi">🔔</span><div class="empt">Nenhum sinal ainda.</div></div></div>
</div>

<div class="pg" id="pg-ct">
<div class="chd">⚡ Contra-Tendência</div>
<div id="ct-list"><div class="empty"><span class="empi">⚡</span><div class="empt">Nenhuma oportunidade CT detectada.</div></div></div>
<div class="chd">📰 Notícias</div>
<div id="news-list"><div class="empty"><span class="empi">📰</span><div class="empt">Carregando notícias…</div></div></div>
</div>

<div class="pg" id="pg-cfg">
<div class="cfgsec">
<div class="cfgl">Mercado</div>
<div class="mdg">
<div class="mdb" data-mode="FOREX" onclick="setMode('FOREX')"><span class="mdi">📈</span>FOREX</div>
<div class="mdb" data-mode="CRYPTO" onclick="setMode('CRYPTO')"><span class="mdi">₿</span>CRIPTO</div>
<div class="mdb" data-mode="COMMODITIES" onclick="setMode('COMMODITIES')"><span class="mdi">🏅</span>COMM.</div>
<div class="mdb" data-mode="INDICES" onclick="setMode('INDICES')"><span class="mdi">📊</span>ÍNDICES</div>
<div class="mdb" data-mode="TUDO" onclick="setMode('TUDO')" style="grid-column:span 2">🌐 TUDO</div>
</div>
</div>
<div class="cfgsec">
<div class="cfgl">Timeframe</div>
<div class="tfg">
<div class="tfb" data-tf="1m" onclick="setTf('1m')"><span class="tfd">1m</span><span class="tfl2">Agressivo</span></div>
<div class="tfb" data-tf="5m" onclick="setTf('5m')"><span class="tfd">5m</span><span class="tfl2">Alto</span></div>
<div class="tfb" data-tf="15m" onclick="setTf('15m')"><span class="tfd">15m</span><span class="tfl2">Moderado</span></div>
<div class="tfb" data-tf="30m" onclick="setTf('30m')"><span class="tfd">30m</span><span class="tfl2">Conserv.</span></div>
<div class="tfb" data-tf="1h" onclick="setTf('1h')"><span class="tfd">1h</span><span class="tfl2">Seguro</span></div>
<div class="tfb" data-tf="4h" onclick="setTf('4h')"><span class="tfd">4h</span><span class="tfl2">Muito Seg.</span></div>
</div>
</div>
<div class="cfgsec">
<div class="cfgl">Parâmetros</div>
<div class="pgrid"><div class="pbox"><div class="plbl">Stop Loss</div><div class="pval" id="p-sl">--</div></div>
<div class="pbox"><div class="plbl">Take Profit</div><div class="pval" id="p-tp">--</div></div>
<div class="pbox"><div class="plbl">Max Trades</div><div class="pval" id="p-mt">--</div></div>
<div class="pbox"><div class="plbl">Confluência</div><div class="pval" id="p-mc">--</div></div>
</div>
</div>
<div class="cfgsec">
<button class="ab abd" onclick="resetPausa()">⛔ Resetar Circuit Breaker</button>
<button class="ab abn" onclick="requestNotif()">🔔 Ativar Notificações</button>
<button class="ab abp" onclick="refreshAll()">↻ Atualizar App</button>
</div>
</div>
</div>
<div id="nav">
<button class="nb on" onclick="goTo('dash',this)"><span class="ni">⬡</span>Dashboard</button>
<button class="nb" onclick="goTo('pend',this)"><span class="ni">⏳</span>Pendentes<div class="nbadge" id="nbadge-pend">0</div></button>
<button class="nb" onclick="goTo('scan',this)"><span class="ni">📡</span>Scanner</button>
<button class="nb" onclick="goTo('sig',this)"><span class="ni">🔔</span>Sinais<div class="nbadge" id="nbadge-sig">0</div></button>
<button class="nb" onclick="goTo('ct',this)"><span class="ni">⚡</span>CT/News</button>
<button class="nb" onclick="goTo('cfg',this)"><span class="ni">⚙</span>Config</button>
</div>
</div>
<script>
let _st=null,_scan=[],_sigs=[],_sf='TODOS',_sigf='todos',_unread=0,_lastSigLen=0,_pending=[];
function fp(p){if(p===undefined||p===null)return'--';if(p>=10000)return p.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});if(p>=1000)return p.toFixed(2);if(p>=10)return p.toFixed(4);if(p>=1)return p.toFixed(5);return p.toFixed(6);}
async function apiFetch(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},mode:'same-origin',...opts});if(!r.ok)throw new Error(r.status);return r.json();}
function goTo(pg,btn){document.querySelectorAll('.pg').forEach(p=>{p.classList.remove('on');p.style.display='none';});document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));const t=document.getElementById('pg-'+pg);if(t){t.classList.add('on');t.style.display='block';}btn.classList.add('on');if(pg==='pend')loadPending();if(pg==='scan')loadScanner();if(pg==='sig'){loadSigs();_unread=0;updBadge();}if(pg==='ct'){loadCT();loadNews();}if(pg==='cfg')loadCfg();}
async function refreshAll(){const b=document.getElementById('refbtn');b.classList.add('spin');try{await loadDash();await loadPending();const a=document.querySelector('.pg.on');if(a.id==='pg-scan')await loadScanner();if(a.id==='pg-sig')await loadSigs();}finally{b.classList.remove('spin');}}
async function loadDash(){try{_st=await apiFetch('/api/status');document.getElementById('eb').style.display='none';document.getElementById('d-dpnl').textContent=_st.daily_pnl>=0?'+'+_st.daily_pnl+'%':_st.daily_pnl+'%';document.getElementById('d-dpnl').className='sv '+(_st.daily_pnl>=0?'g':'r');document.getElementById('d-drec').textContent=_st.daily_wins+'W / '+_st.daily_losses+'L';document.getElementById('d-wr').textContent=_st.winrate+'%';document.getElementById('d-wlt').textContent=_st.wins+'W / '+_st.losses+'L Total';document.getElementById('d-open').textContent=_st.active_trades.length;document.getElementById('d-closed').textContent=_st.today_closed;const cb=document.getElementById('cbbar');if(_st.paused){cb.style.display='flex';document.getElementById('cbmin').textContent=_st.cb_mins+'min';}else cb.style.display='none';document.getElementById('d-trades').innerHTML=_st.active_trades.length?_st.active_trades.map(renderOpenTrade).join(''):'<div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto.<br>Aguardando aprovação...</div></div>';document.getElementById('d-closed-list').innerHTML=_st.today_closed?renderClosedToday(_st.history_today):'<div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada hoje.</div></div>';document.getElementById('d-ts').textContent='Atualizado '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});updCfgBtns();updBadges();}catch(e){document.getElementById('eb').style.display='block';}}
function renderOpenTrade(t){const buy=t.dir==='BUY',pos=t.pnl>=0;const cls=buy?'buy':'sell';const pct=Math.min(Math.abs(t.pnl)/3*100,100);const progColor=pos?'var(--green)':'var(--red)';const distSlClass=t.dist_sl<30?'near':'far';const distTpClass=t.dist_tp<30?'near':'far';return`<div class="otrade ${cls}"><div class="otrade-head"><div class="otrade-sym">${t.symbol}</div><div class="otrade-dir ${cls}">${buy?'▲ BUY':'▼ SELL'}</div></div><div class="otrade-lvls"><div class="otrade-lv"><div class="otrade-ll">Entrada</div><div class="otrade-lvv">${fp(t.entry)}</div></div><div class="otrade-lv"><div class="otrade-ll">Atual</div><div class="otrade-lvv ${pos?'g':'r'}">${fp(t.current)}</div></div><div class="otrade-lv"><div class="otrade-ll">P&L</div><div class="otrade-lvv ${pos?'g':'r'}">${t.pnl>=0?'+':''}${t.pnl.toFixed(2)}%</div></div></div><div class="otrade-prog"><div class="otrade-prog-fill" style="width:${t.progress}%;background:${progColor}"></div></div><div class="otrade-dist"><span>🛡 SL: <span class="${distSlClass}">${t.dist_sl.toFixed(1)}%</span></span><span>🎯 TP: <span class="${distTpClass}">${t.dist_tp.toFixed(1)}%</span></span></div></div>`;}
function renderClosedToday(list){if(!list||!list.length)return'<div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada hoje.</div></div>';return list.map(h=>{const win=h.result==='WIN';return`<div class="ctrow"><div class="ctrow-left"><div class="ctrow-icon ${win?'win':'loss'}">${win?'✅':'❌'}</div><div class="ctrow-info"><div class="ctrow-sym">${h.symbol} ${h.dir}</div><div class="ctrow-time">${h.closed_at}</div></div></div><div class="ctrow-pnl ${win?'g':'r'}">${win?'+':''}${h.pnl.toFixed(2)}%</div></div>`;}).join('');}
async function loadPending(){try{const d=await apiFetch('/api/pending');renderPendingFromApi(d);}catch(e){console.log('pending err',e);}}
function renderPendingFromApi(list){const el=document.getElementById('pendingQueue');const cnt=document.getElementById('pendingCount');if(!el)return;el.innerHTML=list.length?list.map(p=>{const buy=p.dir==='BUY';const dirClass=buy?'buy':'sell';const dirLabel=buy?'▲ BUY':'▼ SELL';const slRaw=typeof p.sl==='number'?p.sl.toFixed(8).replace(/\.?0+$/,''):String(p.sl);const tpRaw=typeof p.tp==='number'?p.tp.toFixed(8).replace(/\.?0+$/,''):String(p.tp);const entryVal=fp(p.entry);return`<div class="otrade ${dirClass}" style="margin-bottom:10px"><div class="otrade-head"><div class="otrade-sym">${p.symbol} <span style="font-size:9px;color:var(--muted2)">PENDENTE</span></div><div class="otrade-dir ${dirClass}">${dirLabel}</div></div><div class="otrade-lvls"><div class="otrade-lv"><div class="otrade-ll">Entrada</div><div class="otrade-lvv">${entryVal}</div></div><div class="otrade-lv"><div class="otrade-ll">SL 🛡</div><div class="otrade-lvv r">${fp(p.sl)}</div></div><div class="otrade-lv"><div class="otrade-ll">TP 🎯</div><div class="otrade-lvv g">${fp(p.tp)}</div></div></div><div style="display:flex;gap:6px;margin-top:10px"><button class="ab abp" style="flex:1;padding:10px;font-size:11px" onclick="confirmPending(${p.pending_id},this)">✅ ACEITAR</button><button class="ab abd" style="flex:1;padding:10px;font-size:11px" onclick="rejectPending(${p.pending_id},this)">❌ RECUSAR</button></div></div>`;}).join(''):'<div class="empty"><span class="empi">✨</span><div class="empt">Nenhuma confirmação pendente</div></div>';}
async function confirmPending(id,btn){btn.textContent='…';btn.disabled=true;try{await apiFetch('/api/confirm',{method:'POST',body:JSON.stringify({pending_id:id})});loadPending();loadDash();}catch(e){btn.textContent='Erro';btn.disabled=false;}}
async function rejectPending(id,btn){btn.textContent='…';btn.disabled=true;try{await apiFetch('/api/reject',{method:'POST',body:JSON.stringify({pending_id:id})});loadPending();}catch(e){btn.textContent='Erro';btn.disabled=false;}}

// ✅ TENDÊNCIAS AGRUPADAS E COLORIDAS
async function loadScanner(){
    try{
        _scan=await apiFetch('/api/trends');
        const groups = {};
        _scan.forEach(x => {
            const cat = x.category || 'OUTROS';
            if(!groups[cat]) groups[cat] = [];
            groups[cat].push(x);
        });
        let html = '';
        const catLabels = {'FOREX':'FOREX','CRYPTO':'CRIPTO','COMMODITIES':'COMMODITIES','INDICES':'ÍNDICES','OUTROS':'OUTROS'};
        for(const cat in groups){
            html += `<div class="trend-group"><div class="trend-group-hd">${catLabels[cat]||cat}</div>`;            html += groups[cat].map(x => {
                const c = x.cenario.toLowerCase();
                const cls = c==='alta'?'alta':c==='baixa'?'baixa':'neutro';
                const tag = c==='alta'?'▲ ALTA':c==='baixa'?'▼ BAIXA':'NEUTRO';
                return `<div class="trend-card ${cls}">
                    <div class="trend-info">
                        <div class="trend-sym">${x.symbol}</div>
                        <div class="trend-name">${x.name}</div>
                    </div>
                    <div class="trend-meta">
                        <span class="trend-tag ${cls}">${tag}</span>
                        <span class="trend-stats">RSI:${x.rsi} ADX:${x.adx}</span>
                    </div>
                </div>`;
            }).join('');
            html += `</div>`;
        }
        document.getElementById('scan-list').innerHTML = html || '<div class="empty"><span class="empi">📡</span><div class="empt">Nenhum dado</div></div>';
    }catch(e){}
}

async function loadSigs(){
    try{
        const d=await apiFetch('/api/signals');
        if(d.length>_lastSigLen){_unread+=d.length-_lastSigLen;updBadge();}
        _lastSigLen=d.length;_sigs=d;
        document.getElementById('sig-list').innerHTML=d.length?d.map(s=>{
            const tipo = s.tipo || 'info';
            return `<div class="sig-item">
                <div class="sig-head">
                    <span class="sig-type ${tipo}">${tipo.toUpperCase()}</span>
                    <span class="sig-ts">${s.ts}</span>
                </div>
                <div class="sig-text">${s.texto}</div>
            </div>`;
        }).join(''):'<div class="empty"><span class="empi">🔔</span><div class="empt">Nenhum sinal</div></div>';
    }catch(e){}
}

// ✅ CONTRA-TENDÊNCIA ORGANIZADA E BONITA
async function loadCT(){
    try{
        const d=await apiFetch('/api/reversals');
        document.getElementById('ct-list').innerHTML=d.length?d.map(x=>{
            const pct = Math.min(x.strength, 100);
            return `<div class="ct-card">
                <div class="ct-head">
                    <div class="ct-sym">${x.symbol}</div>
                    <div class="ct-dir">${x.direction}</div>
                </div>                <div class="ct-body">
                    <div class="ct-stat"><div class="ct-stat-lbl">Força</div><div class="ct-stat-val cy">${x.strength}%</div></div>
                    <div class="ct-stat"><div class="ct-stat-lbl">RSI</div><div class="ct-stat-val">${x.rsi}</div></div>
                </div>
                <div class="ct-bar"><div class="ct-bar-fill" style="width:${pct}%"></div></div>
                <div class="ct-reasons">${x.reasons.map(r=>`<span class="ct-reason">${r}</span>`).join('')}</div>
            </div>`;
        }).join(''):'<div class="empty"><span class="empi">⚡</span><div class="empt">Nenhuma CT</div></div>';
    }catch(e){}
}

async function loadNews(){try{const d=await apiFetch('/api/news');document.getElementById('news-list').innerHTML=d.articles?d.articles.map(a=>`<div style="padding:8px 0;border-bottom:1px solid var(--border)"><a href="${a.url}" target="_blank" style="color:var(--cyan)">${a.title}</a></div>`).join(''):'<div class="empty"><span class="empi">📰</span><div class="empt">Sem notícias</div></div>';}catch(e){}}
async function loadCfg(){try{const c=await apiFetch('/api/config');document.getElementById('p-sl').textContent=c.atm_sl+'×ATR';document.getElementById('p-tp').textContent=c.atr_tp+'×ATR';document.getElementById('p-mt').textContent=c.max_trades;document.getElementById('p-mc').textContent=c.min_conf+'/7';}catch(_){}updCfgBtns();}
function updCfgBtns(){if(!_st)return;document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('on',b.dataset.mode===_st.mode));document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('on',b.dataset.tf===_st.timeframe));}
async function setMode(m){try{await apiFetch('/api/mode',{method:'POST',body:JSON.stringify({mode:m})});await loadDash();}catch(e){alert('Erro: '+e.message);}}
async function setTf(t){try{await apiFetch('/api/timeframe',{method:'POST',body:JSON.stringify({timeframe:t})});await loadDash();}catch(e){alert('Erro: '+e.message);}}
async function resetPausa(){if(!confirm('Resetar Circuit Breaker?'))return;try{await apiFetch('/api/resetpausa',{method:'POST'});await loadDash();}catch(e){alert('Erro: '+e.message);}}

// ✅ NOTIFICAÇÕES
async function requestNotif(){
    if(!('serviceWorker' in navigator) || !('PushManager' in window)){alert('Notificações não suportadas.');return;}
    try{
        const perm = await Notification.requestPermission();
        if(perm !== 'granted'){alert('Permissão negada.');return;}
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:await apiFetch('/api/vapid-public-key').then(r=>r.key)});
        await apiFetch('/api/subscribe',{method:'POST',body:JSON.stringify(sub)});
        alert('Notificações ativadas com sucesso!');
    }catch(e){alert('Erro ao ativar: '+e.message);}
}

function updBadges(){const pend=_pending?_pending.length:0;document.getElementById('nbadge-pend').textContent=pend>0?pend:'';document.getElementById('nbadge-pend').style.display=pend>0?'flex':'none';const sig=_unread>0?_unread:0;document.getElementById('nbadge-sig').textContent=sig>0?sig:'';document.getElementById('nbadge-sig').style.display=sig>0?'flex':'none';}
window.addEventListener('load',()=>{loadDash();loadPending();setInterval(()=>{loadDash();if(document.querySelector('.pg.on').id==='pg-pend')loadPending();},10000);if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});});
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
    def api_health(): return jsonify({"status": "ok", "version": "7.1 PRO"})

    @app.route("/api/status")
    def api_status():
        total = bot.wins + bot.losses
        wr = round(bot.wins/total*100, 1) if total > 0 else 0
        today = datetime.now(Config.BR_TZ).strftime("%d/%m")
        today_trades = [h for h in bot.history if h.get("closed_at", " ").startswith(today)]
        daily_pnl = sum(h.get("pnl", 0) for h in today_trades)
        daily_wins = sum(1 for h in today_trades if h.get("result") == "WIN")
        daily_losses = sum(1 for h in today_trades if h.get("result") == "LOSS")

        trades_out = []
        for t in bot.active_trades:
            try: res = get_analysis(t["symbol"], bot.timeframe); cur = res["price"] if res else t["entry"]
            except: cur = t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL": pnl = -pnl
            dist_sl = abs(cur - t["sl"]) / abs(t["entry"] - t["sl"]) * 100 if t["entry"] != t["sl"] else 0
            dist_tp = abs(cur - t["tp"]) / abs(t["tp"] - t["entry"]) * 100 if t["tp"] != t["entry"] else 0
            progress = min(max(100 - dist_tp, 0), 100) if t["tp"] != t["entry"] else 0
            trades_out.append({
                "symbol": t["symbol"], "name": t.get("name", " "), "dir": t["dir"],
                "tipo": t.get("tipo", " "), "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
                "current": cur, "pnl": round(pnl, 2), "opened_at": t.get("opened_at", " "),
                "dist_sl": round(dist_sl, 1), "dist_tp": round(dist_tp, 1), "progress": round(progress, 1)
            })
        return jsonify({
            "wins": bot.wins, "losses": bot.losses, "winrate": wr,
            "consecutive_losses": bot.consecutive_losses, "mode": bot.mode, "timeframe": bot.timeframe,
            "paused": bot.is_paused(), "cb_mins": max(0, int((bot.paused_until - time.time()) / 60)) if bot.is_paused() else 0,
            "active_trades": trades_out,
            "markets": {cat: mkt_open(cat) for cat in Config.MARKET_CATEGORIES.keys()},
            "pending_count": len(bot.pending_trades),
            "daily_pnl": round(daily_pnl, 2), "daily_wins": daily_wins, "daily_losses": daily_losses,            "today_closed": len(today_trades), "history_today": today_trades
        })

    @app.route("/api/config")
    def api_config():
        return jsonify({"atm_sl": Config.ATR_MULT_SL, "atr_tp": Config.ATR_MULT_TP, "max_trades": Config.MAX_TRADES, "min_conf": Config.MIN_CONFLUENCE})

    @app.route("/api/history")
    def api_history(): return jsonify(list(reversed(bot.history[-50:])))

    @app.route("/api/signals")
    def api_signals(): return jsonify(list(reversed(bot.signals_feed)))

    @app.route("/api/pending")
    def api_pending(): return jsonify(bot.pending_trades)

    @app.route("/api/confirm", methods=["POST", "OPTIONS"])
    def api_confirm():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        if bot.confirm_pending(pid): return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @app.route("/api/reject", methods=["POST", "OPTIONS"])
    def api_reject():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        if bot.reject_pending(pid): return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @app.route("/api/news")
    def api_news():
        now = time.time()
        if now - bot.news_cache_ts > 600 or not bot.news_cache:
            try: bot.news_cache = {"fg": get_fear_greed(), "articles": get_news(15)}; bot.news_cache_ts = now
            except Exception as e: log(f"[NEWS] {e}")
        return jsonify(bot.news_cache if bot.news_cache else {"fg": {}, "articles": []})

    @app.route("/api/trends")
    def api_trends():
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            d = entry["data"]
            out.append({"symbol": sym, "name": d["name"], "category": asset_cat(sym), "price": d["price"], "cenario": d["cenario"], "rsi": round(d["rsi"],1), "adx": round(d["adx"],1), "change_pct": round(d["change_pct"],2), "macd_bull": d["macd_bull"], "macd_bear": d["macd_bear"], "h1_bull": d["h1_bull"], "h1_bear": d["h1_bear"]})
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
                out.append({"symbol": sym, "name": d["name"], "price": d["price"], "rsi": round(d["rsi"],1), "adx": round(d["adx"],1), "direction": rev["dir"], "strength": rev["strength"], "reasons": rev["reasons"]})
        out.sort(key=lambda x: -x["strength"])
        return jsonify(out)

    @app.route("/api/mode", methods=["POST", "OPTIONS"])
    def api_mode():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        mode = data.get("mode", " ")
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]: return jsonify({"error": "inválido"}),400
        bot.set_mode(mode); return jsonify({"ok": True})

    @app.route("/api/timeframe", methods=["POST", "OPTIONS"])
    def api_timeframe():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        tf = data.get("timeframe", " ")
        if tf not in Config.TIMEFRAMES: return jsonify({"error": "inválido"}),400
        bot.set_timeframe(tf); return jsonify({"ok": True})

    @app.route("/api/resetpausa", methods=["POST", "OPTIONS"])
    def api_reset():
        if request.method == "OPTIONS": return jsonify({}), 200
        bot.reset_pause(); return jsonify({"ok": True})

    @app.route("/api/vapid-public-key")
    def api_vapid_key(): return jsonify({"key": os.getenv("VAPID_PUBLIC_KEY", "")})

    @app.route("/api/subscribe", methods=["POST", "OPTIONS"])
    def api_subscribe():
        if request.method == "OPTIONS": return jsonify({}), 200
        sub = request.get_json(force=True)
        if sub and sub not in _push_subscriptions:
            _push_subscriptions.append(sub); log(f"[PUSH] Nova inscrição. Total: {len(_push_subscriptions)}")
        return jsonify({"ok": True})

    return app

def run_api(bot):
    port = int(os.getenv("PORT", 8080))
    app = create_api(bot)
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
                        txt = u["message"].get("text", " ").strip().lower()
                        if txt in ("/noticias", "/news"): bot.send_news()
                        elif txt == "/status": bot.send_status()
                        elif txt in ("/placar", "/score"): bot.send_placar()
                        elif txt in ("/menu", "/start"): bot.build_menu()
                        elif txt == "/resetpausa": bot.reset_pause()
                    if "callback_query" in u:
                        cb = u["callback_query"]["data"]; cid = u["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": cid}, timeout=5)
                        if cb.startswith("set_tf"): bot.set_timeframe(cb.replace("set_tf", ""))
                        elif cb.startswith("set"): bot.set_mode(cb.replace("set_", ""))
                        elif cb == "tf_menu": bot.build_tf_menu()
                        elif cb == "main_menu": bot.build_menu()
                        elif cb == "news": bot.send_news()
                        elif cb == "status": bot.send_status()
                        elif cb == "placar": bot.send_placar()
                        elif cb.startswith("confirm_"):
                            try: bot.confirm_pending(int(cb.split("_")[1]))
                            except: pass
                        elif cb.startswith("reject"):
                            try: bot.reject_pending(int(cb.split("_")[1]))
                            except: pass
            bot.update_trends_cache()
            bot.maybe_send_news()
            bot.scan()
            bot.scan_reversal_forex()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)
        except Exception as e:
            log(f"Erro loop: {e}"); time.sleep(10)

def main():    log("🔌 Bot Sniper v7.1 PRO — Dashboard Profissional + Gestão de Trades")
    try: 
    requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=8)
    except: pass
    bot = TradingBot()
    load_state(bot)
    t = threading.Thread(target=bot_loop, args=(bot,), daemon=True)
    t.start()
    run_api(bot)

if __name__ == "__main__":
    main()
