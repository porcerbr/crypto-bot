import os
import time
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]

EMA_SHORT = 9
EMA_LONG = 21
CHECK_INTERVAL = 60

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

last_states = {}
last_signal_time = {}
last_warning_time = {}

for symbol in SYMBOLS:
    last_states[symbol] = None
    last_signal_time[symbol] = 0
    last_warning_time[symbol] = 0


def fetch_prices(symbol):

    try:

        params = {
            "symbol": symbol,
            "interval": "1m",
            "limit": 50
        }

        r = requests.get(
            BINANCE_URL,
            params=params,
            timeout=10
        )

        if r.status_code != 200:
            return None

        data = r.json()

        prices = [float(c[4]) for c in data]

        return prices

    except Exception:
        return None


def calculate_ema(prices, period):

    multiplier = 2 / (period + 1)

    ema = sum(prices[:period]) / period

    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }

    try:
        requests.post(url, json=payload, timeout=10)
        print("Telegram enviado")

    except Exception as e:
        print("Erro Telegram:", e)


def check_signal(symbol, ema9, ema21):

    state = "BUY" if ema9 > ema21 else "SELL"

    ema_distance = abs(ema9 - ema21)

    now_time = time.time()

    # 🟡 ALERTA ANTECIPADO
    if ema_distance < 0.05:

        if now_time - last_warning_time[symbol] > 120:

            now = (
                datetime.now(timezone.utc)
                - timedelta(hours=3)
            ).strftime("%H:%M:%S")

            msg = (
                f"⏳ <b>PREPARAR POSSÍVEL ENTRADA</b>\n\n"
                f"<b>Cripto:</b> {symbol}\n"
                f"<b>EMAs próximas</b>\n"
                f"<b>Possível entrada em:</b> ~2 minutos\n"
                f"<b>Hora:</b> {now}"
            )

            send_telegram(msg)

            last_warning_time[symbol] = now_time

    # 🔵 FILTRO DE QUALIDADE
    if ema_distance < 0.02:
        return

    previous = last_states[symbol]

    if now_time - last_signal_time[symbol] < 60:
        return

    if previous is None:
        last_states[symbol] = state
        return

    if state != previous:

        now = (
            datetime.now(timezone.utc)
            - timedelta(hours=3)
        ).strftime("%H:%M:%S")

        emoji = "🟢" if state == "BUY" else "🔴"

        msg = (
            f"{emoji} <b>{state} CONFIRMADO</b>\n\n"
            f"<b>Cripto:</b> {symbol}\n"
            f"<b>EMA9:</b> {ema9:.2f}\n"
            f"<b>EMA21:</b> {ema21:.2f}\n"
            f"<b>Hora:</b> {now}"
        )

        send_telegram(msg)

        last_states[symbol] = state
        last_signal_time[symbol] = now_time


def main():

    print("BOT INICIADO")

    send_telegram(
        "<b>BOT INICIADO</b>\n\n"
        "Modo com ALERTA ANTECIPADO ativo\n"
        "Timeframe 1m"
    )

    while True:

        for symbol in SYMBOLS:

            prices = fetch_prices(symbol)

            if prices is None:
                continue

            ema9 = calculate_ema(prices, EMA_SHORT)
            ema21 = calculate_ema(prices, EMA_LONG)

            if ema9 is None or ema21 is None:
                continue

            check_signal(symbol, ema9, ema21)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
