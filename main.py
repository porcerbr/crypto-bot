import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIG
# ==========================

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

BOT_ATIVO = False
LAST_UPDATE_ID = None

last_signal = {s: None for s in SYMBOLS}


# ==========================
# HORÁRIO BRASIL
# ==========================

def agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)


# ==========================
# TELEGRAM
# ==========================

def enviar(msg):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": msg
        }

        requests.post(url, json=payload)

    except Exception as e:

        print("Erro Telegram:", e)


def verificar_comandos():

    global BOT_ATIVO
    global LAST_UPDATE_ID

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    try:

        r = requests.get(url, timeout=10)

        data = r.json()

        for update in data["result"]:

            update_id = update["update_id"]

            if LAST_UPDATE_ID and update_id <= LAST_UPDATE_ID:
                continue

            LAST_UPDATE_ID = update_id

            if "message" not in update:
                continue

            texto = update["message"].get("text", "")

            if texto == "/start":

                BOT_ATIVO = True

                enviar("🟢 BOT ATIVADO")

            elif texto == "/stop":

                BOT_ATIVO = False

                enviar("🔴 BOT PARADO")

            elif texto == "/status":

                status = "ATIVO" if BOT_ATIVO else "PARADO"

                enviar(f"📊 STATUS: {status}")

    except Exception as e:

        print("Erro comandos:", e)


# ==========================
# CANDLES
# ==========================

def get_candles(symbol):

    url = "https://data-api.binance.vision/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": "1m",
        "limit": 100
    }

    try:

        r = requests.get(url, params=params, timeout=10)

        data = r.json()

        closes = [float(c[4]) for c in data]

        return closes

    except Exception:

        return None


# ==========================
# EMA
# ==========================

def ema(prices, period):

    if len(prices) < period:
        return None

    k = 2 / (period + 1)

    e = sum(prices[:period]) / period

    for p in prices[period:]:
        e = (p - e) * k + e

    return e


# ==========================
# RSI
# ==========================

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


# ==========================
# VERIFICAR SINAL
# ==========================

def verificar(symbol, prices):

    e9 = ema(prices, EMA_SHORT)
    e21 = ema(prices, EMA_MEDIUM)
    e50 = ema(prices, EMA_LONG)

    r = rsi(prices)

    if not e9 or not e21 or not e50 or not r:
        return

    distancia = abs(e9 - e21)

    if distancia < 0.08:
        return

    estado = None

    if e9 > e21:
        estado = "BUY"

    elif e9 < e21:
        estado = "SELL"

    if not estado:
        return

    segundos = agora().second

    if segundos >= 58:

        if estado != last_signal[symbol]:

            enviar(
                f"⏰ ENTRAR AGORA\n\n"
                f"{symbol}\n"
                f"Tipo: {estado}\n"
                f"RSI:{r:.1f}"
            )

            last_signal[symbol] = estado


# ==========================
# MAIN
# ==========================

def main():

    print("BOT COM CONTROLE TELEGRAM")

    enviar(
        "🤖 BOT PRONTO\n"
        "Use:\n"
        "/start → iniciar\n"
        "/stop → parar\n"
        "/status → status"
    )

    while True:

        verificar_comandos()

        if BOT_ATIVO:

            print("BOT ATIVO")

            for symbol in SYMBOLS:

                prices = get_candles(symbol)

                if prices:

                    verificar(symbol, prices)

        else:

            print("BOT PARADO")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
