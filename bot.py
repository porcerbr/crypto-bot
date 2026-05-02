import asyncio
import logging
import os
import pandas as pd
import numpy as np
from telegram import Bot
from telegram.error import NetworkError, Unauthorized
import yfinance as yf
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

# Config
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
if not BOT_TOKEN or not CHAT_ID:
    logger.error("Falta BOT_TOKEN ou CHAT_ID nas vars!")
    exit(1)

PARES = ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X']
MODEL = None
FEATURES = ['rsi', 'macd_dist', 'atr_pct', 'adx_proxy', 'price_ema_ratio']

# Funções TA puras (sem TA-Lib)
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

# Treina modelo simples uma vez
def train_model(par):
    global MODEL
    try:
        data = yf.download(par, period='6mo', interval='4h', progress=False)
        if len(data) < 100:
            return
        
        close = data['Close']; high = data['High']; low = data['Low']
        
        # Features
        data['rsi'] = rsi(close)
        data['ema_200'] = ema(close, 200)
        macd_line = ema(close, 12) - ema(close, 26)
        data['macd_sig'] = ema(macd_line, 9)
        data['macd_dist'] = (macd_line - data['macd_sig']) / close
        data['atr_pct'] = atr(high, low, close) / close * 100
        data['adx_proxy'] = data['atr_pct'].rolling(14).mean()  # Proxy simples
        data['price_ema_ratio'] = close / data['ema_200']
        
        # Label: 1 se próximo retorno positivo forte
        data['future_ret'] = close.shift(-5) / close - 1
        data['target'] = (data['future_ret'] > data['atr_pct']/100 * 1.5).astype(int)
        
        df = data[FEATURES + ['target']].dropna()
        if len(df) < 50:
            return
        
        X = df[FEATURES]; y = df['target']
        X_train, _, y_train, _ = train_test_split(X, y, test_size=0.3, random_state=42)
        
        MODEL = RandomForestClassifier(n_estimators=50, random_state=42)
        MODEL.fit(X_train, y_train)
        acc = MODEL.score(X, y)
        logger.info(f"Modelo {par} treinado! Acc: {acc:.2f}")
    except Exception as e:
        logger.error(f"Erro treino {par}: {e}")

# Filtra sinal com IA
def ia_filter(data):
    global MODEL
    if MODEL is None:
        return True  # Fallback sem modelo
    try:
        last_row = data[FEATURES].iloc[-1:].fillna(0)
        prob_valid = MODEL.predict_proba(last_row)[0][1]
        logger.info(f"Prob sinal válido: {prob_valid:.2%}")
        return prob_valid > 0.65
    except:
        return True

# Gera sinal avançado
def get_signal(par):
    try:
        data = yf.download(par, period='3mo', interval='4h', progress=False)
        if len(data) < 50:
            return None
        
        close = data['Close']; high = data['High']; low = data['Low']
        
        # Indicadores
        data['rsi'] = rsi(close)
        data['ema_200'] = ema(close, 200)
        macd_line = ema(close, 12) - ema(close, 26)
        data['macd_sig'] = ema(macd_line, 9)
        data['atr'] = atr(high, low, close)
        
        last = data.iloc[-1]; prev = data.iloc[-2]
        price = last['Close']
        
        # Sinal BUY: Uptrend + pullback + cross + IA OK
        if (price > last['ema_200'] and  # Trend up
            last['rsi'] < 45 and  # Pullback
            prev['macd_sig'] > prev['macd_line'] and last['macd_sig'] < last['macd_line'] and  # Cross bull
            ia_filter(data)):
            
            sl = low[-20:].min() * 0.9995  # Swing low
            risk = price - sl
            tp = price + risk * 2.5
            return f"🚀 IA COMPRA {par[:-2]} @ {price:.5f}
SL: {sl:.5f} | TP: {tp:.5f} (RR 1:2.5)
RSI:{last['rsi']:.0f} | Trend: UP"
        
        # SELL similar
        elif (price < last['ema_200'] and last['rsi'] > 55 and
              prev['macd_sig'] < prev['macd_line'] and last['macd_sig'] > last['macd_line'] and
              ia_filter(data)):
            sl = high[-20:].max() * 1.0005
            risk = sl - price
            tp = price - risk * 2.5
            return f"🔻 IA VENDA {par[:-2]} @ {price:.5f}
SL: {sl:.5f} | TP: {tp:.5f} (RR 1:2.5)
RSI:{last['rsi']:.0f} | Trend: DOWN"
        
        return None
    except Exception as e:
        logger.error(f"Erro sinal {par}: {e}")
        return None

async def send_message(bot, msg):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='HTML')
        logger.info(f"Sinal enviado: {msg[:50]}...")
    except (NetworkError, Unauthorized) as e:
        logger.error(f"Erro Telegram: {e}")

async def main_loop():
    global MODEL
    bot = Bot(token=BOT_TOKEN)
    
    # Treina modelos no start
    logger.info("Iniciando treino IA...")
    for par in PARES:
        train_model(par)
    
    logger.info("Bot rodando! Checa a cada 4h.")
    
    while True:
        try:
            for par in PARES:
                sinal = get_signal(par)
                if sinal:
                    await send_message(bot, sinal)
            await asyncio.sleep(14400)  # 4 horas
        except Exception as e:
            logger.error(f"Loop error: {e}")
            await asyncio.sleep(300)

if __name__ == '__main__':
    asyncio.run(main_loop())
