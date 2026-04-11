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
INTERVALO_SINAIS = 20  # minutos

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BOT_ATIVO = False
LAST_UPDATE_ID = None

ultimo_envio = None


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
# CALCULAR SCORE
# ==========================

def calcular_score(e9, e21, e50, r):

    score = 0

    if e9 > e21:
        score += 30

    if e9 > e50:
        score += 30

    if r > 52:
        score += 20

    score += 20

    return score


# ==========================
# ANALISAR TODOS
# ==========================

def analisar_ativos():

    resultados = []

    for symbol in SYMBOLS:

        prices = get_candles(symbol)

        if not prices:
            continue

        e9 = ema(prices, EMA_SHORT)
        e21 = ema(prices, EMA_MEDIUM)
        e50 = ema(prices, EMA_LONG)

        r = rsi(prices)

        if not e9 or not e21 or not e50 or not r:
            continue

        estado = "BUY" if e9 > e21 else "SELL"

        score = calcular_score(e9, e21, e50, r)

        resultados.append(
            (symbol, estado, score, r)
        )

    resultados.sort(
        key=lambda x: x[2],
        reverse=True
    )

    return resultados[:3]


# ==========================
# MAIN
# ==========================

def main():

    global ultimo_envio

    enviar("🤖 BOT PRONTO")

    while True:

        verificar_comandos()

        if BOT_ATIVO:

            agora_time = agora()

            if (
                ultimo_envio is None or
                (agora_time - ultimo_envio).seconds >= INTERVALO_SINAIS * 60
            ):

                sinais = analisar_ativos()

                if sinais:

                    msg = "📊 TOP OPORTUNIDADES\n\n"

                    for i, s in enumerate(sinais):

                        symbol, estado, score, r = s

                        msg += (
                            f"{i+1}️⃣ {symbol}\n"
                            f"{estado}\n"
                            f"Score:{score}\n"
                            f"RSI:{r:.1f}\n\n"
                        )

                    enviar(msg)

                    ultimo_envio = agora_time

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
