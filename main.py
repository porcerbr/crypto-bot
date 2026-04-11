import os
import time
import requests
from datetime import datetime, timedelta, timezone

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "ADAUSDT",
    "XRPUSDT"
]

EMA_SHORT = 9
EMA_MEDIUM = 21
EMA_LONG = 50

RSI_PERIOD = 14

CHECK_INTERVAL = 60

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

last_signal = {s: None for s in SYMBOLS}
prediction_flag = {s: False for s in SYMBOLS}


def agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)


def enviar(msg):

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


def get_candles(symbol):

    print("Buscando candles:", symbol)

    url = "https://data-api.binance.vision/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": "1m",
        "limit": 100
    }

    try:

        r = requests.get(url, params=params, timeout=10)

        if r.status_code != 200:
            print("Erro API:", symbol)
            return None

        data = r.json()

        closes = [float(c[4]) for c in data]

        print("Candles recebidos:", symbol)

        return closes

    except Exception as e:

        print("Erro candles:", symbol, e)

        return None


def ema(prices, period):

    if len(prices) < period:
        return None

    k = 2 / (period + 1)

    e = sum(prices[:period]) / period

    for p in prices[period:]:
        e = (p - e) * k + e

    return e


def rsi(prices):

    if len(prices) < RSI_PERIOD + 1:
        return None

    gains = []
    losses = []

    for i in range(1, RSI_PERIOD + 1):

        diff = prices[i] - prices[i - 1]

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

    return 100 - (100 / (1 + rs))


def verificar(symbol, prices):

    e9 = ema(prices, EMA_SHORT)
    e21 = ema(prices, EMA_MEDIUM)
    e50 = ema(prices, EMA_LONG)

    r = rsi(prices)

    if not e9 or not e21 or not e50 or not r:
        print("Indicadores insuficientes:", symbol)
        return

    agora_str = agora().strftime("%H:%M")

    print(
        f"{agora_str} | {symbol} | "
        f"E9:{e9:.2f} "
        f"E21:{e21:.2f} "
        f"E50:{e50:.2f} "
        f"RSI:{r:.1f}"
    )


def main():

    print("BOT PROFISSIONAL INICIADO")

    enviar(
        "🚀 BOT PROFISSIONAL INICIADO"
    )

    while True:

        try:

            for symbol in SYMBOLS:

                prices = get_candles(symbol)

                if prices:

                    verificar(symbol, prices)

                else:

                    print("Sem dados:", symbol)

        except Exception as e:

            print("Erro geral:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
