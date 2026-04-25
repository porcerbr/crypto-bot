# analysis.py
import math
import pandas as pd
import yfinance as yf
from config import Config
from utils import log, asset_cat, asset_name, vol_reliable, to_yf
from broker import get_mt5_analysis, MT5_AVAILABLE

def get_analysis(symbol, timeframe=None):
    """Obtém análise completa – MT5 (prioritário) ou Yahoo Finance (fallback)."""
    res = get_mt5_analysis(symbol, timeframe)
    if res is not None:
        return res
    # Fallback Yahoo Finance (mesmo código original)
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]
    use_vol = vol_reliable(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 50:
            return None
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
        log(f"[ANÁLISE] {symbol}: {e}")
        return None

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
    min_sc = Config.MIN_CONFLUENCE
    passed = sc >= min_sc
    return sc, len(checks), checks, passed, min_sc

def cbar(sc, tot):
    f = math.floor(sc/tot*5)
    return "█"*f + "░"*(5-f)

def calc_premium_rr(res, dir_s, sc, tot_c):
    if not Config.DYNAMIC_RR_ENABLED:
        return Config.TP_SL_RATIO, f"Padrao 1:{Config.TP_SL_RATIO}", 0, []
    premium = []
    price  = res.get("price", 1)
    rsi    = res.get("rsi", 50)
    adx    = res.get("adx", 0)
    upper  = res.get("upper", price)
    lower  = res.get("lower", price)
    ema9   = res.get("ema9", price)
    ema21  = res.get("ema21", price)
    if adx > 35: premium.append(f"ADX {adx:.0f} (tendencia forte)")
    if sc >= tot_c: premium.append(f"Confluencia maxima ({sc}/{tot_c})")
    elif sc >= tot_c - 1 and tot_c >= 6: premium.append(f"Confluencia quase perfeita ({sc}/{tot_c})")
    vol_ratio = res.get("vol_ratio", 0)
    if vol_ratio > 1.8: premium.append(f"Volume {vol_ratio:.1f}x acima da media")
    macd_hist = res.get("macd_hist", 0)
    if dir_s == "BUY"  and res.get("macd_bull") and macd_hist > 0: premium.append("MACD forte e acelerado (alta)")
    elif dir_s == "SELL" and res.get("macd_bear") and macd_hist < 0: premium.append("MACD forte e acelerado (baixa)")
    if (dir_s == "BUY"  and res.get("h1_bull")) or (dir_s == "SELL" and res.get("h1_bear")): premium.append("TF superior alinhado")
    if dir_s == "BUY"  and 40 <= rsi <= 60: premium.append(f"RSI {rsi:.0f} — zona ideal de alta")
    elif dir_s == "SELL" and 40 <= rsi <= 60: premium.append(f"RSI {rsi:.0f} — zona ideal de baixa")
    band_range = max(upper - lower, 1e-10); pct_pos = (price - lower) / band_range
    if dir_s == "BUY"  and 0.25 <= pct_pos <= 0.65: premium.append("Espaco nas bandas para alta")
    elif dir_s == "SELL" and 0.35 <= pct_pos <= 0.75: premium.append("Espaco nas bandas para baixa")
    ema_spread_pct = abs(ema9 - ema21) / max(price, 1e-10) * 100
    if ema_spread_pct > 0.08: premium.append(f"EMAs espaçadas {ema_spread_pct:.2f}% (momentum claro)")
    n = len(premium); rr_ratio = Config.TP_SL_RATIO; rr_label = f"Padrao 1:{Config.TP_SL_RATIO}"
    for min_cond, rr, label in sorted(Config.DYNAMIC_RR_TIERS, key=lambda x: x[0], reverse=True):
        if n >= min_cond: rr_ratio = rr; rr_label = f"{label} 1:{rr}"; break
    return rr_ratio, rr_label, n, premium

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
    elif uw>body0*2 and lw<body0*0.5 and body0<rng0*0.4: pb2=True; nm="Estrela Cadente"
    elif body0 < rng0*0.1: pb=pb2=True; nm="Doji"
    elif lw>rng0*0.6 and body0<rng0*0.25: pb=True; nm="Pin Bar Alta"
    elif uw>rng0*0.6 and body0<rng0*0.25: pb2=True; nm="Pin Bar Baixa"
    return pb, pb2, nm

def get_reversal_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]
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
        ema9 = closes.ewm(span=9,adjust=False).mean()
        ema21 = closes.ewm(span=21,adjust=False).mean()
        ema12 = closes.ewm(span=12,adjust=False).mean(); ema26 = closes.ewm(span=26,adjust=False).mean()
        mh = (ema12-ema26)-(ema12-ema26).ewm(span=9,adjust=False).mean()
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean()
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
        near_up = price >= ub*Config.REVERSAL_BAND_BUFFER
        near_dn = price <= lb*(2-Config.REVERSAL_BAND_BUFFER)
        rsi_ob = rsi >= Config.REVERSAL_RSI_SELL
        rsi_os = rsi <= Config.REVERSAL_RSI_BUY
        trend_up = bool(price > ema200.iloc[-1] and ema9.iloc[-1] > ema21.iloc[-1] and ema21.iloc[-1] > ema200.iloc[-1])
        trend_down = bool(price < ema200.iloc[-1] and ema9.iloc[-1] < ema21.iloc[-1] and ema21.iloc[-1] < ema200.iloc[-1])
        sell_core = [near_up, rsi_ob, div_bear, mdiv_bear, bool(uw>rng0*0.6), pb2, trend_up, adx > 20]
        buy_core  = [near_dn, rsi_os, div_bull, mdiv_bull, bool(lw>rng0*0.6), pb, trend_down, adx > 20]
        sig_sell = sum(bool(x) for x in sell_core) >= Config.REVERSAL_MIN_SCORE - 1
        sig_buy  = sum(bool(x) for x in buy_core) >= Config.REVERSAL_MIN_SCORE - 1
        if not (sig_sell or sig_buy): return None
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price, "rsi": rsi, "atr": atr, "adx": adx, "adx_mature": adx>30,
            "upper_band": ub, "lower_band": lb, "near_upper": near_up, "near_lower": near_dn,
            "rsi_overbought": rsi_ob, "rsi_oversold": rsi_os, "div_bear": div_bear, "div_bull": div_bull,
            "macd_div_bear": mdiv_bear, "macd_div_bull": mdiv_bull, "wick_bear": bool(uw>rng0*0.6),
            "wick_bull": bool(lw>rng0*0.6), "pat_bull": pb, "pat_bear": pb2, "pat_name": pnm,
            "trend_up": trend_up, "trend_down": trend_down,
            "signal_sell_ct": sig_sell, "signal_buy_ct": sig_buy,
        }
    except Exception as e: log(f"[CT] {symbol}: {e}"); return None

def calc_reversal_conf(res, d):
    if d == "SELL":
        checks = [("Tendência principal de alta", res.get("trend_up", False)),
                  ("RSI sobrecomprado", res["rsi_overbought"]), ("Banda Superior BB", res["near_upper"]),
                  ("RSI div. bearish", res["div_bear"]), ("MACD div. bearish", res["macd_div_bear"]),
                  ("Candle de baixa", res["pat_bear"]), ("Wick superior", res["wick_bear"]), ("ADX maduro", res["adx_mature"])]
    else:
        checks = [("Tendência principal de baixa", res.get("trend_down", False)),
                  ("RSI sobrevendido", res["rsi_oversold"]), ("Banda Inferior BB", res["near_lower"]),
                  ("RSI div. bullish", res["div_bull"]), ("MACD div. bullish", res["macd_div_bull"]),
                  ("Candle de alta", res["pat_bull"]), ("Wick inferior", res["wick_bull"]), ("ADX maduro", res["adx_mature"])]
    sc = sum(1 for _, ok in checks if ok)
    min_sc = Config.MIN_CONFLUENCE_CT
    passed = sc >= min_sc
    return sc, len(checks), checks, passed, min_sc

def detect_reversal(res):
    if not res: return (False, None, 0, [])
    motivos = []; forca = 0; dir_rev = None
    rsi = res["rsi"]; price = res["price"]; cen = res["cenario"]
    trend_up = bool(price > res["ema200"] and res["ema9"] > res["ema21"] and res["ema21"] > res["ema200"])
    trend_down = bool(price < res["ema200"] and res["ema9"] < res["ema21"] and res["ema21"] < res["ema200"])
    if cen == "ALTA" or trend_up:
        if rsi >= 75: motivos.append(f"RSI sobrecomprado ({rsi:.0f})"); forca += 25; dir_rev = "SELL"
        if price >= res["upper"] * Config.REVERSAL_BAND_BUFFER: motivos.append("Banda superior BB"); forca += 25; dir_rev = "SELL"
        if res["macd_hist"] < 0: motivos.append("Div. MACD baixista"); forca += 20; dir_rev = "SELL"
        if res["adx"] > 20 and trend_up: motivos.append(f"Tendência esticada ({res['adx']:.0f} ADX)"); forca += 10
    if cen == "BAIXA" or trend_down:
        if rsi <= 25: motivos.append(f"RSI sobrevendido ({rsi:.0f})"); forca += 25; dir_rev = "BUY"
        if price <= res["lower"] * (2-Config.REVERSAL_BAND_BUFFER): motivos.append("Banda inferior BB"); forca += 25; dir_rev = "BUY"
        if res["macd_hist"] > 0: motivos.append("Div. MACD altista"); forca += 20; dir_rev = "BUY"
        if res["adx"] > 20 and trend_down: motivos.append(f"Tendência esticada ({res['adx']:.0f} ADX)"); forca += 10
    forca = min(forca, 100)
    return (forca >= 70 and dir_rev is not None, dir_rev, forca, motivos)
