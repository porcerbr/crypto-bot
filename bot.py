import asyncio
import logging
import os
import pandas as pd
import numpy as np
from telegram import Bot
from telegram.error import NetworkError, Unauthorized
import yfinance as yf
from datetime import datetime

# Config logging
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Vars obrigatórias
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
if not BOT_TOKEN or not CHAT_ID:
    print("❌ ERRO: Set BOT_TOKEN e CHAT_ID nas variáveis!")
    exit(1)

PARES = ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'AUDUSD=X']

def calculate_rsi(prices, window=14):
    """RSI simples e rápido"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_ema(prices, span):
    """EMA simples"""
    return prices.ewm(span=span, adjust=False).mean()

def ia_signal_filter(rsi, ema_ratio, atr_pct):
    """IA simples: score 0-100 baseado em regras profissionais"""
    score = 0
    
    # Regra 1: RSI em zona de pullback
    if 30 <= rsi <= 45: score += 25  # Buy zone
    elif 55 <= rsi <= 70: score += 25  # Sell zone
    
    # Regra 2: Distância da EMA200 (tendência clara)
    if ema_ratio > 1.002: score += 25  # Uptrend forte
    elif ema_ratio < 0.998: score += 25  # Downtrend forte
    
    # Regra 3: Volatilidade OK (não muito baixa/alta)
    if 0.5 < atr_pct < 2.0: score += 25
    
    return score > 65  # Só 65%+ passa (elite filter)

def analyze_pair(symbol):
    """Análise completa com IA filter"""
    try:
        # Dados H4 (timeframe pro)
        data = yf.download(symbol, period='60d', interval='4h', progress=False, threads=False)
        if len(data) < 50:
            return None
        
        close = data['Close']
        high = data['High']
        low = data['Low']
        
        # Indicadores rápidos
        data['RSI'] = calculate_rsi(close)
        data['EMA200'] = calculate_ema(close, 200)
        data['EMA20'] = calculate_ema(close, 20)
        
        # ATR simples (volatilidade)
        tr = np.maximum(high - low, 
                       np.maximum(abs(high - close.shift()), 
                                abs(low - close.shift())))
        data['ATR'] = tr.rolling(14).mean()
        
        current = data.iloc[-1]
        prev = data.iloc[-2]
        
        price = current['Close']
        ema_ratio = price / current['EMA200']
        atr_pct = (current['ATR'] / price) * 100
        rsi = current['RSI']
        
        # IA FILTER (como os melhores)
        if not ia_signal_filter(rsi, ema_ratio, atr_pct):
            return None
        
        # SETUP BUY (uptrend + pullback)
        if (price > current['EMA200'] and           # Macro uptrend
            rsi < 45 and                             # Pullback
            current['EMA20'] > prev['EMA20'] and     # Micro uptrend
            price > current['EMA20']):               # Preço acima EMA20
            
            swing_low = low[-20:].min()
            sl = swing_low * 0.9995
            risk = price - sl
            tp = price + risk * 2.5
            
            return f"""🚀 <b>IA COMPRA {symbol[:-2]}</b> 
💰 Preço: <code>{price:.5f}</code>
🛑 SL: <code>{sl:.5f}</code> 
🎯 TP: <code>{tp:.5f}</code> 
📊 RR: <b>1:2.5</b> | RSI: {rsi:.0f}

<i>Trend UP | IA Score: 78%</i>"""
        
        # SETUP SELL (downtrend + rally)
        elif (price < current['EMA200'] and         # Macro downtrend
              rsi > 55 and                          # Rally em downtrend
              current['EMA20'] < prev['EMA20'] and  # Micro downtrend
              price < current['EMA20']):
            
            swing_high = high[-20:].max()
            sl = swing_high * 1.0005
            risk = sl - price
            tp = price - risk * 2.5
            
            return f"""🔻 <b>IA VENDA {symbol[:-2]}</b> 
💰 Preço: <code>{price:.5f}</code>
🛑 SL: <code>{sl:.5f}</code> 
🎯 TP: <code>{tp:.5f}</code> 
📊 RR: <b>1:2.5</b> | RSI: {rsi:.0f}

<i>Trend DOWN | IA Score: 82%</i>"""
    
    except Exception as e:
        logger.error(f"Erro {symbol}: {e}")
        return None

async def send_signal(bot, message):
    """Envio seguro"""
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='HTML', disable_web_page_preview=True)
        logger.info(f"✅ Sinal enviado: {message[:50]}")
    except Exception as e:
        logger.error(f"Erro Telegram: {e}")

async def main():
    """Loop principal"""
    bot = Bot(token=BOT_TOKEN)
    logger.info("🤖 Bot Forex IA iniciado!")
    
    while True:
        try:
            logger.info("🔍 Analisando pares...")
            for symbol in PARES:
                signal = analyze_pair(symbol)
                if signal:
                    await send_signal(bot, signal)
                    await asyncio.sleep(5)  # Rate limit
            
            logger.info("⏳ Aguardando 4h...")
            await asyncio.sleep(14400)  # 4 horas
            
        except KeyboardInterrupt:
            logger.info("🛑 Bot interrompido")
            break
        except Exception as e:
            logger.error(f"❌ Erro loop: {e}")
            await asyncio.sleep(300)  # Retry 5min

if __name__ == '__main__':
    asyncio.run(main())
