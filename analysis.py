import pandas as pd
import yfinance as yf
from config import Config
from utils import log, asset_name

# Mapa de símbolos para o Yahoo Finance
SYMBOL_MAP = Config.YAHOO_SYMBOLS

def _to_yahoo(symbol):
    """Converte símbolo interno para o ticker do Yahoo Finance."""
    return SYMBOL_MAP.get(symbol, symbol)   # fallback: usa o próprio símbolo

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
        closes = df["Close"]
        highs = df["High"]
        lows = df["Low"]
        opens = df["Open"]

        # EMAs
        ema9   = closes.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]

        # Bollinger
        w = min(20, len(closes)-1)
        sma20 = closes.rolling(w).mean().iloc[-1]
        std20 = closes.rolling(w).std().iloc[-1]
        upper = sma20 + 2*std20
        lower = sma20 - 2*std20

        # RSI
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        rsi_val = float(rsi.iloc[-1])

        # MACD
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = float(macd_line.iloc[-1] - signal_line.iloc[-1])
        macd_bull = macd_line.iloc[-1] > signal_line.iloc[-1]
        macd_bear = macd_line.iloc[-1] < signal_line.iloc[-1]

        # ATR
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows - closes.shift()).abs()
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])

        # ADX
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
        if len(closes) >= 10:
            chg = (closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100
        else:
            chg = 0.0

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
            "symbol": symbol,          # mantemos o símbolo original para exibição
            "name": asset_name(symbol),
            "price": price,
            "cenario": cen,
            "rsi": round(rsi_val, 1),
            "atr": round(atr, 5),
            "adx": round(adx, 1),
            "ema9": float(ema9),
            "ema21": float(ema21),
            "ema200": float(ema200),
            "upper": float(upper),
            "lower": float(lower),
            "macd_bull": macd_bull,
            "macd_bear": macd_bear,
            "macd_hist": macd_hist,
            "t_buy": t_buy,
            "t_sell": t_sell,
            "change_pct": round(chg, 2),
            "candle_bull": candle_bull,
            "candle_bear": candle_bear,
        }
    except Exception as e:
        log(f"[ANÁLISE] Erro {symbol} ({yf_symbol}): {e}")
        return None
