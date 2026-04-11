import os
import time
import requests
from datetime import datetime, timezone
from collections import deque

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "ADAUSDT",
    "XRPUSDT"
]

EMA_SHORT = 9
EMA_LONG = 21
CHECK_INTERVAL = 60

BINANCE_ENDPOINT = "https://api.binance.com/api/v3/klines"

price_histories = {}
last_crossover_state = {}
last_signal_time = {}

for symbol in SYMBOLS:
    price_histories[symbol] = deque(maxlen=50)
    last_crossover_state[symbol] = None
    last_signal_time[symbol] = 0


def fetch_prices(symbol):
    params = {
        "symbol": symbol,
        "interval": "1m",
        "limit": 50
    }

    try:
        resp = requests.get(
            BINANCE_ENDPOINT,
            params=params,
            timeout=10
        )

        if resp.status_code == 200:
            klines = resp.json()

            return [
                float(k[4])
                for k in klines
            ]

    except Exception as e:
        print("Erro ao buscar preços:", e)

    return None


def calculate_ema(prices, period):

    if len(prices) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(prices[:period]) / period

    for price in prices[period:]:
        ema = (
            (price - ema)
            * multiplier
            + ema
        )

    return ema


def send_telegram_message(message):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        requests.post(
            url,
            json=payload,
            timeout=10
        )

        print("[Telegram] Message sent")

    except Exception as e:
        print("[Telegram Error]", e)


def check_crossover(symbol, ema_short, ema_long):

    current_state = (
        "BULLISH"
        if ema_short > ema_long
        else "BEARISH"
    )

    ema_distance = abs(
        ema_short - ema_long
    )

    # Filtro forte
    if ema_distance < 0.1:
        return

    previous_state = last_crossover_state[symbol]

    current_time = time.time()

    # Evita repetição (5 minutos)
    if current_time - last_signal_time[symbol] < 300:
        return

    if previous_state is None:
        last_crossover_state[symbol] = current_state
        return

    if current_state != previous_state:

        now = datetime.now(
            timezone.utc
        ).strftime("%H:%M:%S")

        if current_state == "BULLISH":
            emoji = "🟢"
            action = "COMPRA FORTE"
        else:
            emoji = "🔴"
            action = "VENDA FORTE"

        message = (
            f"{emoji} <b>{action}</b>\n\n"
            f"<b>Cripto:</b> {symbol}\n"
            f"<b>EMA9:</b> {ema_short:.2f}\n"
            f"<b>EMA21:</b> {ema_long:.2f}\n"
            f"<b>Hora:</b> {now}\n"
            f"<b>Timeframe:</b> 1m"
        )

        send_telegram_message(message)

        last_crossover_state[symbol] = current_state
        last_signal_time[symbol] = current_time


def main():

    print("MULTI-CRYPTO BOT INICIADO")

    startup_msg = (
        "<b>BOT INICIADO</b>\n\n"
        "Monitorando:\n"
        "BTC, ETH, SOL, ADA, XRP\n"
        "EMA 9 / EMA 21\n"
        "Filtro ativo\n"
        "Timeframe 1m"
    )

    send_telegram_message(startup_msg)

    while True:

        try:

            now = datetime.now(
                timezone.utc
            ).strftime("%H:%M:%S")

            for symbol in SYMBOLS:

                print(f"[{now}] Verificando {symbol}")

                prices = fetch_prices(symbol)

                if prices is None:
                    continue

                price_histories[symbol] = deque(
                    prices,
                    maxlen=50
                )

                prices_list = list(
                    price_histories[symbol]
                )

                ema_short = calculate_ema(
                    prices_list,
                    EMA_SHORT
                )

                ema_long = calculate_ema(
                    prices_list,
                    EMA_LONG
                )

                if ema_short and ema_long:

                    print(
                        f"{symbol} | "
                        f"EMA9: {ema_short:.2f} | "
                        f"EMA21: {ema_long:.2f}"
                    )

                    check_crossover(
                        symbol,
                        ema_short,
                        ema_long
                    )

        except Exception as e:
            print("[Error]", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
