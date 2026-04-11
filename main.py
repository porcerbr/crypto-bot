import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==============================
# CONFIGURAÇÕES
# ==============================

SYMBOL = "ETHUSDT"
INTERVAL = "1m"

EMA_SHORT = 9
EMA_LONG = 21
RSI_PERIOD = 14

CHECK_INTERVAL = 60

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

last_state = None


# ==============================
# HORÁRIO BRASIL
# ==============================

def agora_brasil():
    return datetime.now(timezone.utc) - timedelta(hours=3)


# ==============================
# TELEGRAM
# ==============================

def enviar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }

        requests.post(url, json=payload)

    except Exception as e:
        print("Erro Telegram:", e)


# ==============================
# PEGAR CANDLES
# ==============================

def get_candles():

    url = "https://data-api.binance.vision/api/v3/klines"

    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "limit": 100
    }

    try:
        r = requests.get(url, params=params, timeout=10)

        data = r.json()

        closes = [float(c[4]) for c in data]

        return closes

    except Exception as e:
        print("Erro candles:", e)
        return None


# ==============================
# EMA
# ==============================

def calcular_ema(prices, period):

    if len(prices) < period:
        return None

    k = 2 / (period + 1)

    ema = sum(prices[:period]) / period

    for p in prices[period:]:
        ema = (p - ema) * k + ema

    return ema


# ==============================
# RSI
# ==============================

def calcular_rsi(prices):

    if len(prices) < RSI_PERIOD + 1:
        return None

    ganhos = []
    perdas = []

    for i in range(1, RSI_PERIOD + 1):

        diff = prices[i] - prices[i - 1]

        if diff >= 0:
            ganhos.append(diff)
            perdas.append(0)
        else:
            ganhos.append(0)
            perdas.append(abs(diff))

    media_ganho = sum(ganhos) / RSI_PERIOD
    media_perda = sum(perdas) / RSI_PERIOD

    if media_perda == 0:
        return 100

    rs = media_ganho / media_perda

    rsi = 100 - (100 / (1 + rs))

    return rsi


# ==============================
# PREVISÃO
# ==============================

def verificar_sinal(prices):

    global last_state

    ema9 = calcular_ema(prices, EMA_SHORT)
    ema21 = calcular_ema(prices, EMA_LONG)

    rsi = calcular_rsi(prices)

    if not ema9 or not ema21 or not rsi:
        return

    estado = "COMPRA" if ema9 > ema21 else "VENDA"

    agora = agora_brasil().strftime("%H:%M")

    print(
        f"{agora} | "
        f"Preço: {prices[-1]:.2f} | "
        f"EMA9: {ema9:.2f} | "
        f"EMA21: {ema21:.2f} | "
        f"RSI: {rsi:.1f}"
    )

    # PREVISÃO 2 candles antes

    distancia = abs(ema9 - ema21)

    if distancia < 0.3:

        if estado != last_state:

            mensagem = (
                f"⚠️ <b>POSSÍVEL {estado}</b>\n\n"
                f"Ativo: {SYMBOL}\n"
                f"RSI: {rsi:.1f}\n"
                f"Hora: {agora}\n\n"
                f"Entrada prevista em breve"
            )

            enviar_telegram(mensagem)

            last_state = estado


# ==============================
# MAIN
# ==============================

def main():

    print("BOT ETH INICIADO")

    enviar_telegram(
        "🤖 <b>BOT ETH INICIADO</b>\n\n"
        "EMA 9 / 21\n"
        "RSI 14\n"
        "Previsão 2 candles"
    )

    while True:

        try:

            prices = get_candles()

            if prices:

                verificar_sinal(prices)

            else:
                print("Sem dados...")

        except Exception as e:

            print("Erro geral:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
