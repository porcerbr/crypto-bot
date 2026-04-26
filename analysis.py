import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone
from config import Config
from utils import log, asset_name

SYMBOL_MAP = Config.YAHOO_SYMBOLS

def _to_yahoo(symbol):
    return SYMBOL_MAP.get(symbol, symbol)

def _resample_to_4h(df):
    if df.empty:
        return df
    df_4h = df.resample('4h').agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }).dropna()
    return df_4h

def _detect_fvg(df, lookback=20):
    if len(df) < lookback + 3:
        return {"bullish": [], "bearish": []}

    fvg_bull = []
    fvg_bear = []
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    opens = df["Open"].values
    times = df.index

    for i in range(max(3, len(df) - lookback), len(df)):
        if lows[i] > highs[i - 2]:
            body_i1 = abs(closes[i-1] - opens[i-1])
            range_i1 = highs[i-1] - lows[i-1]
            if range_i1 > 0 and body_i1 / range_i1 > 0.6:
                fvg_bull.append({
                    "top": float(lows[i]),
                    "bottom": float(highs[i - 2]),
                    "time": times[i],
                    "active": lows[i] <= closes[-1] <= highs[i-2]
                })
        if highs[i] < lows[i - 2]:
            body_i1 = abs(closes[i-1] - opens[i-1])
            range_i1 = highs[i-1] - lows[i-1]
            if range_i1 > 0 and body_i1 / range_i1 > 0.6:
                fvg_bear.append({
                    "top": float(lows[i - 2]),
                    "bottom": float(highs[i]),
                    "time": times[i],
                    "active": highs[i] <= closes[-1] <= lows[i-2]
                })

    return {"bullish": fvg_bull, "bearish": fvg_bear}

def _detect_order_blocks(df, lookback=15):
    if len(df) < lookback + 3:
        return {"bullish": [], "bearish": []}

    obs_bull = []
    obs_bear = []
    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values
    opens = df["Open"].values
    times = df.index

    for i in range(2, len(df)):
        if closes[i-2] < opens[i-2]:
            body = closes[i-1] - opens[i-1]
            range_c = highs[i-1] - lows[i-1]
            if body > 0 and range_c > 0 and (body / range_c) > 0.5:
                if closes[i] > closes[i-1]:
                    obs_bull.append({
                        "high": float(highs[i-2]),
                        "low": float(lows[i-2]),
                        "time": times[i-2],
                        "active": lows[i-2] <= closes[-1] <= highs[i-2]
                    })
        if closes[i-2] > opens[i-2]:
            body = opens[i-1] - closes[i-1]
            range_c = highs[i-1] - lows[i-1]
            if body > 0 and range_c > 0 and (body / range_c) > 0.5:
                if closes[i] < closes[i-1]:
                    obs_bear.append({
                        "high": float(highs[i-2]),
                        "low": float(lows[i-2]),
                        "time": times[i-2],
                        "active": lows[i-2] <= closes[-1] <= highs[i-2]
                    })

    cutoff = times[-1] - pd.Timedelta(hours=lookback)
    obs_bull = [ob for ob in obs_bull if ob["time"] >= cutoff][-3:]
    obs_bear = [ob for ob in obs_bear if ob["time"] >= cutoff][-3:]

    return {"bullish": obs_bull, "bearish": obs_bear}

def _detect_liquidity_sweeps(df, swing_lookback=10):
    if len(df) < swing_lookback + 3:
        return {"bullish": False, "bearish": False, "swing_high": None, "swing_low": None}

    highs = df["High"].values
    lows = df["Low"].values
    closes = df["Close"].values

    recent_high = float(max(highs[-swing_lookback-2:-2]))
    recent_low = float(min(lows[-swing_lookback-2:-2]))

    last_high = float(highs[-1])
    last_low = float(lows[-1])
    last_close = float(closes[-1])

    bearish_sweep = (last_high > recent_high) and (last_close < recent_high)
    bullish_sweep = (last_low < recent_low) and (last_close > recent_low)

    return {
        "bullish": bullish_sweep,
        "bearish": bearish_sweep,
        "swing_high": recent_high,
        "swing_low": recent_low,
    }

def _calc_indicators(df):
    closes = df["Close"]
    highs = df["High"]
    lows = df["Low"]
    opens = df["Open"]

    ema9 = closes.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = closes.ewm(span=21, adjust=False).mean().iloc[-1]
    ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]

    w = min(20, len(closes)-1)
    sma20 = closes.rolling(w).mean().iloc[-1]
    std20 = closes.rolling(w).std().iloc[-1]
    upper = sma20 + 2*std20
    lower = sma20 - 2*std20

    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1])

    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = float(macd_line.iloc[-1] - signal_line.iloc[-1])
    macd_bull = macd_line.iloc[-1] > signal_line.iloc[-1]
    macd_bear = macd_line.iloc[-1] < signal_line.iloc[-1]

    tr = pd.concat([
        highs - lows,
        (highs - closes.shift()).abs(),
        (lows - closes.shift()).abs()
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    up_move = highs.diff()
    down_move = -lows.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/14, adjust=False).mean() / atr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False).mean() / atr_smooth
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1])

    price = float(closes.iloc[-1])
    chg = (closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100 if len(closes) >= 10 else 0.0

    cen = "NEUTRO"
    if price > ema200 and ema9 > ema21:
        cen = "ALTA"
    elif price < ema200 and ema9 < ema21:
        cen = "BAIXA"

    candle_bull = float(closes.iloc[-1]) > float(opens.iloc[-1])
    candle_bear = not candle_bull

    t_buy = float(highs.tail(5).max())
    t_sell = float(lows.tail(5).min())

    return {
        "price": price, "ema9": float(ema9), "ema21": float(ema21), "ema200": float(ema200),
        "upper": float(upper), "lower": float(lower), "rsi": round(rsi_val, 1),
        "atr": round(atr, 5), "adx": round(adx, 1),
        "macd_bull": bool(macd_bull), "macd_bear": bool(macd_bear),
        "macd_hist": float(macd_hist), "change_pct": round(chg, 2),
        "candle_bull": bool(candle_bull), "candle_bear": bool(candle_bear),
        "t_buy": t_buy, "t_sell": t_sell,
    }

def get_analysis(symbol, timeframe=None):
    timeframe = timeframe or Config.TIMEFRAME
    period, interval = Config.TIMEFRAMES.get(timeframe, ("60d", "1h"))
    yf_symbol = _to_yahoo(symbol)

    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty or len(df) < 30:
            log(f"[ANÁLISE] Dados insuficientes para {symbol} ({yf_symbol})")
            return None

        last_time = df.index[-1]
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        if interval == "1h":
            expected = now_utc.replace(minute=0, second=0, microsecond=0)
            if last_time >= expected:
                log(f"[ANÁLISE] {symbol}: último candle ainda não fechado, ignorando.")
                return None

        tr_temp = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs()
        ], axis=1).max(axis=1)
        atr_temp = tr_temp.rolling(14).mean().iloc[-1]
        last_range = df["High"].iloc[-1] - df["Low"].iloc[-1]
        if atr_temp > 0 and last_range > 3 * atr_temp:
            log(f"[ANÁLISE] {symbol}: candle anômalo (range > 3x ATR), ignorando.")
            return None

        indicators = _calc_indicators(df)
        fvg = _detect_fvg(df, Config.FVG_LOOKBACK)
        ob = _detect_order_blocks(df, Config.OB_LOOKBACK)
        sweep = _detect_liquidity_sweeps(df, Config.LIQUIDITY_SWING_LOOKBACK)

        indicators["fvg"] = fvg
        indicators["ob"] = ob
        indicators["sweep"] = sweep
        indicators["symbol"] = symbol
        indicators["name"] = asset_name(symbol)

        return indicators

    except Exception as e:
        log(f"[ANÁLISE] Erro {symbol} ({yf_symbol}): {e}")
        return None

def get_multi_timeframe(symbol):
    mtf = {"h1": None, "h4": None, "aligned": False, "h4_cenario": "NEUTRO"}
    h1 = get_analysis(symbol, "1h")
    if not h1:
        return mtf

    mtf["h1"] = h1
    yf_symbol = _to_yahoo(symbol)
    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period="120d", interval="1h")
        if df.empty or len(df) < 100:
            return mtf

        df_4h = _resample_to_4h(df)
        if len(df_4h) < 30:
            return mtf

        h4_ind = _calc_indicators(df_4h)
        h4_fvg = _detect_fvg(df_4h, Config.FVG_LOOKBACK)
        h4_ob = _detect_order_blocks(df_4h, Config.OB_LOOKBACK)
        h4_sweep = _detect_liquidity_sweeps(df_4h, Config.LIQUIDITY_SWING_LOOKBACK)

        h4_ind["fvg"] = h4_fvg
        h4_ind["ob"] = h4_ob
        h4_ind["sweep"] = h4_sweep

        mtf["h4"] = h4_ind
        mtf["aligned"] = h1["cenario"] == h4_ind["cenario"] and h1["cenario"] != "NEUTRO"
        mtf["h4_cenario"] = h4_ind["cenario"]

    except Exception as e:
        log(f"[MTF] Erro H4 {symbol}: {e}")

    return mtf
                    
