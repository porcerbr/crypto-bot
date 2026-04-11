import os
import time
import requests
from datetime import datetime, timedelta
from collections import deque

# =============================
# CONFIGURAÇÕES
# =============================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOL = "ETHUSDT"

EMA_SHORT = 9
EMA_LONG = 21
RSI_PERIOD = 14

CHECK_INTERVAL = 60

price_history = deque(maxlen=100)

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
        requests.post(url, json=payload)
        print("Mensagem enviada")
    except Exception as e:
        print("Erro Telegram:", e)


# =============================
# BINANCE
# =============================

def get_prices():

    url = "https://api.binance.com/api/v3/klines"

    params = {
        "symbol": SYMBOL,
        "interval": "1m",
        "limit": 100
    }

    try:

        r = requests.get(url, params=params, timeout=10)

        data = r.json()

        closes = [float(c[4]) for c in data]

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

def calculate_rsi(prices, period=14):

    gains = []
    losses = []

    for i in range(1, period+1):

        diff = prices[i] - prices[i-1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period

    if avg_loss == 0:
        return 100

    rs = avg_gain/avg_loss

    rsi = 100 - (100/(1+rs))

    return rsi


# =============================
# PREVISÃO CRUZAMENTO
# =============================

def predict_crossover(ema9, ema21):

    distance = ema9 - ema21

    if abs(distance) < 0.02:

        if distance > 0:
            return "SELL_PREP"
        else:
            return "BUY_PREP"

    return None


# =============================
# LOOP PRINCIPAL
# =============================

def main():

    global last_signal

    print("BOT ETH INICIADO")

    send_telegram(
        "<b>BOT ETH INICIADO</b>\n"
        "EMA 9/21 + RSI 14\n"
        "Previsão 2 candles antes"
    )

    while True:

        try:

            prices = get_prices()

            if prices is None:
                time.sleep(10)
                continue

            ema9 = calculate_ema(prices, EMA_SHORT)
            ema21 = calculate_ema(prices, EMA_LONG)

            rsi = calculate_rsi(prices[-(RSI_PERIOD+1):])

            price = prices[-1]

            print(
                f"{datetime.now()} | "
                f"Price {price:.2f} | "
                f"EMA9 {ema9:.2f} | "
                f"EMA21 {ema21:.2f} | "
                f"RSI {rsi:.2f}"
            )

            prediction = predict_crossover(ema9, ema21)

            # =====================
            # PRÉ-SINAL
            # =====================

            if prediction == "BUY_PREP" and rsi < 55:

                if last_signal != "BUY_PREP":

                    send_telegram(
                        "🟡 <b>PREPARAR COMPRA</b>\n"
                        "Possível cruzamento em até 2 candles"
                    )

                    last_signal = "BUY_PREP"

            elif prediction == "SELL_PREP" and rsi > 45:

                if last_signal != "SELL_PREP":

                    send_telegram(
                        "🟡 <b>PREPARAR VENDA</b>\n"
                        "Possível cruzamento em até 2 candles"
                    )

                    last_signal = "SELL_PREP"

            # =====================
            # CRUZAMENTO REAL
            # =====================

            if ema9 > ema21 and rsi > 50:

                if last_signal != "BUY":

                    send_telegram(
                        "🟢 <b>BUY</b>\n"
                        "Entrada 1 segundo antes do fechamento"
                    )

                    last_signal = "BUY"

            elif ema9 < ema21 and rsi < 50:

                if last_signal != "SELL":

                    send_telegram(
                        "🔴 <b>SELL</b>\n"
                        "Entrada 1 segundo antes do fechamento"
                    )

                    last_signal = "SELL"

        except Exception as e:

            print("Erro geral:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
