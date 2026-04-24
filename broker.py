# broker.py
import pandas as pd
import time
from config import Config
from utils import log, fmt, to_yf, asset_cat, asset_name

# --- MetaTrader5 opcional (só Windows) ---
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = mt5.initialize()
except (ImportError, Exception):
    MT5_AVAILABLE = False

# ---------- análise via MT5 (retorna None se não disponível) ----------
def get_mt5_analysis(symbol, timeframe=None):
    if not MT5_AVAILABLE:
        return None
    if timeframe is None:
        timeframe = Config.TIMEFRAME
    tf_map = {
        "1m": mt5.TIMEFRAME_M1, "5m": mt5.TIMEFRAME_M5,
        "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4
    }
    mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M15)
    rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 200)
    if rates is None or len(rates) < 50:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    closes = df['close']; highs = df['high']; lows = df['low']
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
    sup_mt5_tf = mt5.TIMEFRAME_H1 if sup_tf == "1h" else mt5.TIMEFRAME_D1
    try:
        sup_rates = mt5.copy_rates_from_pos(symbol, sup_mt5_tf, 0, 200)
        if sup_rates is not None and len(sup_rates) >= 50:
            sup_df = pd.DataFrame(sup_rates)
            sup_df['time'] = pd.to_datetime(sup_df['time'], unit='s')
            sup_df.set_index('time', inplace=True)
            ch = sup_df['close']
            e21h = ch.ewm(span=21, adjust=False).mean().iloc[-1]
            e200h = ch.ewm(span=min(200,len(ch)-1), adjust=False).mean().iloc[-1]
            ph = ch.iloc[-1]
            h1b = bool(ph > e21h and e21h > e200h)
            h1r = bool(ph < e21h and e21h < e200h)
    except: pass
    return {
        "symbol": symbol,
        "name": asset_name(symbol),
        "price": price,
        "cenario": cen,
        "rsi": float(rsi),
        "atr": atr,
        "adx": adx,
        "ema9": float(ema9),
        "ema21": float(ema21),
        "ema200": float(ema200),
        "upper": float(upper),
        "lower": float(lower),
        "macd_bull": macd_bull,
        "macd_bear": macd_bear,
        "macd_hist": float(mh.iloc[-1]),
        "vol_ok": True,
        "vol_ratio": 0,
        "t_buy": float(highs.tail(5).max()),
        "t_sell": float(lows.tail(5).min()),
        "h1_bull": h1b,
        "h1_bear": h1r,
        "change_pct": chg,
    }

# ---------- envio de ordens (retorna erro se MT5 indisponível) ----------
def mt5_send_order(symbol, direction, lot, sl_price, tp_price):
    if not MT5_AVAILABLE:
        return False, "MT5 não disponível"
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return False, f"Símbolo {symbol} não encontrado"
    spread = (tick.ask - tick.bid) / tick.bid * 10000
    if spread > 5.0:
        return False, f"Spread muito alto ({spread:.1f} pips). Operação cancelada."
    deviation = max(20, int(spread * 2))
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = tick.ask if direction == "BUY" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": order_type,
        "price": price,
        "sl": float(sl_price),
        "tp": float(tp_price),
        "deviation": deviation,
        "magic": 234000,
        "comment": "Sniper Bot v11",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"Erro MT5: {result.retcode} — {result.comment}"
    positions = mt5.positions_get(symbol=symbol)
    if positions is None or len(positions) == 0:
        return False, "Ordem executada mas posição não encontrada"
    return True, f"Ordem #{result.order} executada | Preço: {result.price}"
