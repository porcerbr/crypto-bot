import os
import time
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]

EMA_SHORT = 9
EMA_LONG = 21
CHECK_INTERVAL = 60

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

last_states = {}
last_signal_time = {}

for symbol in SYMBOLS:
    last_states[symbol] = None
    last_signal_time[symbol] = 0


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
            print(f"Erro HTTP {r.status_code} em {symbol}")
            return None

        data = r.json()

        prices = [float(c[4]) for c in data]

        return prices

    except Exception as e:
        print("Erro ao buscar:", symbol, e)
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
        print("Mensagem enviada Telegram")

    except Exception as e:
        print("Erro Telegram:", e)


def check_signal(symbol, ema9, ema21):

    state = "BUY" if ema9 > ema21 else "SELL"

    ema_distance = abs(ema9 - ema21)

# Ignorar cruzamentos muito fracos
if ema_distance < 0.02:
    return
    
    previous = last_states[symbol]

    now_time = time.time()

    if now_time - last_signal_time[symbol] < 60:
        return

    if previous is None:
        last_states[symbol] = state
        return

    if state != previous:

        now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")

        emoji = "🟢" if state == "BUY" else "🔴"

        msg = (
            f"{emoji} <b>{state}</b>\n\n"
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
        "<b>BOT INICIADO</b>\nMonitorando múltiplas criptos 1m"
    )

    while True:

        now = datetime.now().strftime("%H:%M:%S")

        for symbol in SYMBOLS:

            print(f"[{now}] Verificando {symbol}")

            prices = fetch_prices(symbol)

            if prices is None:
                continue

            ema9 = calculate_ema(prices, EMA_SHORT)
            ema21 = calculate_ema(prices, EMA_LONG)

            print(
                f"{symbol} EMA9={ema9:.2f} EMA21={ema21:.2f}"
            )

            check_signal(symbol, ema9, ema21)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
