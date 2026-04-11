import os
import time
import requests
from datetime import datetime, timedelta
from collections import deque

# CONFIG
SYMBOL = "ethereum"

EMA_SHORT = 9
EMA_LONG = 21
RSI_PERIOD = 14

CHECK_INTERVAL = 60
TIMEZONE_OFFSET = -3

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

prices = deque(maxlen=200)

last_signal = None


# PEGAR PREÇO (corrigido)
def get_price():

    try:

        url = "https://api.coingecko.com/api/v3/simple/price"

        params = {
            "ids": "ethereum",
            "vs_currencies": "usd"
        }

        r = requests.get(url, params=params, timeout=10)

        if r.status_code != 200:
            return None

        data = r.json()

        if "ethereum" not in data:
            return None

        price = float(data["ethereum"]["usd"])

        return price

    except Exception as e:

        print("Erro preço:", e)

        return None


# EMA
def calculate_ema(data, period):

    if len(data) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(list(data)[:period]) / period

    for price in list(data)[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


# RSI
def calculate_rsi(data, period=14):

    if len(data) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):

        diff = data[i] - data[i - 1]

        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi


# HORA BRASIL
def now_brazil():

    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)


# TELEGRAM
def send_telegram(msg):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }

        requests.post(url, json=payload)

    except Exception as e:

        print("Erro Telegram:", e)


# VERIFICAR SINAL
def check_signal():

    global last_signal

    ema9 = calculate_ema(prices, EMA_SHORT)
    ema21 = calculate_ema(prices, EMA_LONG)

    rsi = calculate_rsi(list(prices), RSI_PERIOD)

    if ema9 is None or ema21 is None or rsi is None:
        return

    distance = abs(ema9 - ema21)

    # FILTRO — reduz sinais falsos
    if distance < 0.15:
        return

    now = now_brazil().strftime("%H:%M:%S")

    # BUY
    if ema9 > ema21 and rsi > 55:

        if last_signal != "BUY":

            msg = f"""
🟢 <b>PREVISÃO BUY ETH</b>

Entrada em ~2 candles

EMA9: {ema9:.2f}
EMA21: {ema21:.2f}
RSI14: {rsi:.1f}

Hora: {now}
"""

            send_telegram(msg)

            last_signal = "BUY"

    # SELL
    elif ema9 < ema21 and rsi < 45:

        if last_signal != "SELL":

            msg = f"""
🔴 <b>PREVISÃO SELL ETH</b>

Entrada em ~2 candles

EMA9: {ema9:.2f}
EMA21: {ema21:.2f}
RSI14: {rsi:.1f}

Hora: {now}
"""

            send_telegram(msg)

            last_signal = "SELL"


# LOOP
def main():

    print("BOT ETH INICIADO")

    send_telegram("🤖 BOT ETH INICIADO")

    while True:

        price = get_price()

        if price:

            prices.append(price)

            print(
                now_brazil().strftime("%H:%M:%S"),
                "Preço:",
                price
            )

            check_signal()

        else:

            print("Sem preço...")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
