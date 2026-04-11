import os
import time
import requests
from datetime import datetime
from collections import deque

# =============================
# CONFIG
# =============================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOL = "ETHUSDT"

EMA_SHORT = 9
EMA_LONG = 21
RSI_PERIOD = 14

CHECK_INTERVAL = 60

last_signal = None

# =============================
# TELEGRAM
# =============================

def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }

    try:
        requests.post(url, json=payload, timeout=10)
        print("Mensagem enviada")

    except Exception as e:
        print("Erro Telegram:", e)


# =============================
# PREÇO (CORRIGIDO)
# =============================

def get_prices():

    try:

        url = "https://api.binance.com/api/v3/klines"

        params = {
            "symbol": SYMBOL,
            "interval": "1m",
            "limit": 100
        }

        r = requests.get(url, params=params, timeout=10)

        data = r.json()

        # se Binance retornar erro
        if isinstance(data, dict):
            print("Erro Binance:", data)
            return None

        closes = []

        for candle in data:

            closes.append(float(candle[4]))

        return closes

    except Exception as e:

        print("Erro preço:", e)

        return None


# =============================
# EMA
# =============================

def calculate_ema(prices, period):

    multiplier = 2 / (period + 1)

    ema = sum(prices[:period]) / period

    for price in prices[period:]:

        ema = (price - ema) * multiplier + ema

    return ema


# =============================
# RSI
# =============================

def calculate_rsi(prices):

    gains = []
    losses = []

    for i in range(1, len(prices)):

        diff = prices[i] - prices[i-1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains) / RSI_PERIOD
    avg_loss = sum(losses) / RSI_PERIOD

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi


# =============================
# PREVISÃO
# =============================

def predict_crossover(ema9, ema21):

    distance = ema9 - ema21

    if abs(distance) < 0.03:

        if distance > 0:
            return "SELL_PREP"
        else:
            return "BUY_PREP"

    return None


# =============================
# LOOP
# =============================

def main():

    global last_signal

    print("BOT ETH INICIADO")

    send_telegram(
        "<b>BOT ETH INICIADO</b>\n"
        "EMA 9/21 + RSI 14\n"
        "Previsão antecipada"
    )

    while True:

        try:

            prices = get_prices()

            if prices is None:

                print("Sem preço... tentando novamente")

                time.sleep(10)

                continue

            ema9 = calculate_ema(prices, EMA_SHORT)
            ema21 = calculate_ema(prices, EMA_LONG)

            rsi = calculate_rsi(prices[-15:])

            price = prices[-1]

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Price
