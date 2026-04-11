import os
import time
import requests
from datetime import datetime, timedelta
from collections import deque

# ===== CONFIG =====

SYMBOLS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "binancecoin": "BNB",
    "ripple": "XRP"
}

EMA_SHORT = 9
EMA_MEDIUM = 21
EMA_LONG = 50

RSI_PERIOD = 14

CHECK_INTERVAL = 60
TIMEZONE_OFFSET = -3

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

prices = {k: deque(maxlen=300) for k in SYMBOLS}
last_signal = {k: None for k in SYMBOLS}


# ===== PREÇO =====

def get_prices():

    try:

        ids = ",".join(SYMBOLS.keys())

        url = "https://api.coingecko.com/api/v3/simple/price"

        params = {
            "ids": ids,
            "vs_currencies": "usd"
        }

        r = requests.get(url, params=params, timeout=10)

        if r.status_code != 200:
            return None

        return r.json()

    except Exception as e:

        print("Erro preço:", e)

        return None


# ===== EMA =====

def calculate_ema(data, period):

    if len(data) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(list(data)[:period]) / period

    for price in list(data)[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


# ===== RSI =====

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


# ===== HORA =====

def now_brazil():

    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)


# ===== TELEGRAM =====

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


# ===== SINAL =====

def check_signal(symbol_key):

    data = prices[symbol_key]

    ema9 = calculate_ema(data, EMA_SHORT)
    ema21 = calculate_ema(data, EMA_MEDIUM)
    ema50 = calculate_ema(data, EMA_LONG)

    rsi = calculate_rsi(list(data), RSI_PERIOD)

    if None in (ema9, ema21, ema50, rsi):
        return

    distance = abs(ema9 - ema21)

    # evita sinal fraco
    if distance < 0.15:
        return

    symbol = SYMBOLS[symbol_key]

    now = now_brazil().strftime("%H:%M:%S")

    # ===== BUY =====

    if ema9 > ema21 > ema50 and rsi > 55:

        if last_signal[symbol_key] != "BUY":

            msg = f"""
🟢 <b>BUY PREVISTO</b>

Cripto: {symbol}

Entrada ~2 candles

EMA9 > EMA21 > EMA50
RSI14: {rsi:.1f}

Hora: {now}
"""

            send_telegram(msg)

            last_signal[symbol_key] = "BUY"

    # ===== SELL =====

    elif ema9 < ema21 < ema50 and rsi < 45:

        if last_signal[symbol_key] != "SELL":

            msg = f"""
🔴 <b>SELL PREVISTO</b>

Cripto: {symbol}

Entrada ~2 candles

EMA9 < EMA21 < EMA50
RSI14: {rsi:.1f}

Hora: {now}
"""

            send_telegram(msg)

            last_signal[symbol_key] = "SELL"


# ===== LOOP =====

def main():

    print("BOT AVANÇADO INICIADO")

    send_telegram(
        "🚀 BOT AVANÇADO INICIADO\nBTC ETH SOL BNB XRP"
    )

    while True:

        data = get_prices()

        if data:

            for key in SYMBOLS:

                try:

                    price = float(
                        data[key]["usd"]
                    )

                    prices[key].append(price)

                    print(
                        now_brazil().strftime("%H:%M:%S"),
                        SYMBOLS[key],
                        price
                    )

                    check_signal(key)

                except:
                    pass

        else:

            print("Sem dados...")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
