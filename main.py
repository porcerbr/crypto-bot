import asyncio
import logging
import os
import numpy as np
from telegram import Bot
from telegram.error import NetworkError, Unauthorized
import yfinance as yf
from datetime import datetime

logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
if not BOT_TOKEN or not CHAT_ID:
    print("❌ Set BOT_TOKEN e CHAT_ID!")
    exit(1)

PARES = ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X']

def rsi_numpy(prices, period=14):
    """RSI puro numpy (rápido)"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def ema_numpy(prices, period):
    """EMA numpy simples"""
    alpha = 2 / (period + 1)
    ema = prices[0]
    ema_values = [ema]
    for price in prices[1:]:
        ema = alpha * price + (1 - alpha) * ema
        ema_values.append(ema)
    return np.array(ema_values)

def atr_numpy(high, low, close, period=14):
    """ATR numpy"""
    prev_close = np.roll(close, 1)
    tr1 = high - low
    tr2 = np.abs(high - prev_close)
    tr3 = np.abs(low - prev_close)
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return np.mean(tr[-period:])

def ia_filter(rsi_val, ema_ratio, atr_pct):
    """IA regras pro (score >65%)"""
    score = 0
    if 30 <= rsi_val <= 45: score += 30  # Buy pullback
    elif 55 <= rsi_val <= 70: score += 30  # Sell rally
    
    if ema_ratio > 1.0015 or ema_ratio < 0.9985: score += 20  # Trend forte
    if 0.3 < atr_pct < 1.5: score += 20  # Vol OK
    
    logger.info(f"IA Score: {score}% (RSI:{rsi_val:.0f}, EMA:{ema_ratio:.4f})")
    return score >= 65

def analyze_pair(symbol):
    try:
        data = yf.download(symbol, period='60d', interval='4h', progress=False)
        if len(data) < 50:
            return None
        
        closes = data['Close'].values
        highs = data['High'].values
        lows = data['Low'].values
        
        # Indicadores numpy
        rsi = rsi_numpy(closes)
        ema200 = ema_numpy(closes, 200)[-1]
        ema20 = ema_numpy(closes[-50:], 20)[-1]  # EMA20 recente
        atr = atr_numpy(highs, lows, closes)
        
        price = closes[-1]
        ema_ratio = price / ema200
        atr_pct = (atr / price) * 100
        
        # IA FILTER
        if not ia_filter(rsi, ema_ratio, atr_pct):
            return None
        
        # BUY signal
        if (price > ema200 and rsi < 45 and price > ema20):
            swing_low = np.min(lows[-20:])
            sl = swing_low * 0.9995
            risk = price - sl
            tp = price + risk * 2.5
            
            return f"""🚀 <b>IA COMPRA {symbol[0:-2]}</b>
💰 Preço: <code>{price:.5f}</code>
🛑 SL: <code>{sl:.5f}</code>
🎯 TP: <code>{tp:.5f}</code>
📊 <b>RR 1:2.5</b> | RSI: {rsi:.0f}

<i>Trend UP forte | IA OK</i>"""
        
        # SELL signal
        elif (price < ema200 and rsi > 55 and price < ema20):
            swing_high = np.max(highs[-20:])
            sl = swing_high * 1.0005
            risk = sl - price
            tp = price - risk * 2.5
            
            return f"""🔻 <b>IA VENDA {symbol[0:-2]}</b>
💰 Preço: <code>{price:.5f}</code>
🛑 SL: <code>{sl:.5f}</code>
🎯 TP: <code>{tp:.5f}</code>
📊 <b>RR 1:2.5</b> | RSI: {rsi:.0f}

<i>Trend DOWN forte | IA OK</i>"""
        
    except Exception as e:
        logger.error(f"Erro {symbol}: {e}")
    return None

async def send_signal(bot, msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='HTML')
        logger.info(f"✅ SINAL: {msg[:50]}...")
    except Exception as e:
        logger.error(f"Telegram erro: {e}")

async def main():
    bot = Bot(token=BOT_TOKEN)
    logger.info("🤖 BOT FOREX IA NUMPY INICIADO!")
    
    while True:
        logger.info("🔍 Checando pares...")
        for symbol in PARES:
            signal = analyze_pair(symbol)
            if signal:
                await send_signal(bot, signal)
                await asyncio.sleep(3)
        
        logger.info("⏳ Próxima checagem em 4h")
        await asyncio.sleep(14400)

if __name__ == '__main__':
    asyncio.run(main())
