import os
import time
import requests
from datetime import datetime

# =============================
# CONFIGURAÇÃO
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

def send_telegram(message):

    try:

        url = "https://api.telegram.org/bot{}/sendMessage".format(
            TELEGRAM_BOT_TOKEN
        )

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }

        requests.post(url, json=payload, timeout=10)

        print("Mensagem enviada")

    except Exception as e:

        print("Erro Telegram:", e)


# =============================
# PREÇOS
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
# LOOP PRINCIPAL
# =============================

def main():

    global last_signal

    print("BOT ETH INICIADO")

    send_telegram(
        "BOT ETH INICIADO\n"
        "EMA 9/21 + RSI 14"
    )

    while True:

        try:

            prices = get_prices()

            if prices is None:

                print("Sem preço...")

                time.sleep(10)

                continue

            ema9 = calculate_ema(prices, EMA_SHORT)
            ema21 = calculate_ema(prices, EMA_LONG)

            rsi = calculate_rsi(prices[-15:])

            price = prices[-1]

            print(
                "[{}] Price {} | EMA9 {} | EMA21 {} | RSI {}".format(
                    datetime.now().strftime("%H:%M:%S"),
                    round(price, 2),
                    round(ema9, 2),
                    round(ema21, 2),
                    round(rsi, 2)
                )
            )

            # BUY

            if ema9 > ema21 and rsi > 50:

                if last_signal != "BUY":

                    send_telegram("🟢 BUY")

                    last_signal = "BUY"

            # SELL

            elif ema9 < ema21 and rsi < 50:

                if last_signal != "SELL":

                    send_telegram("🔴 SELL")

                    last_signal = "SELL"

        except Exception as e:

            print("Erro geral:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
