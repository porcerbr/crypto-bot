import os
import time
import requests
from datetime import datetime, timedelta, timezone

# =============================
# CONFIGURAÇÃO
# =============================

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

last_state = {symbol: None for symbol in SYMBOLS}


# =============================
# HORÁRIO BRASIL
# =============================

def agora_brasil():
    return datetime.now(timezone.utc) - timedelta(hours=3)


# =============================
# TELEGRAM
# =============================

def enviar_telegram(msg):

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


# =============================
# PEGAR CANDLES
# =============================

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

    except Exception as e:

        print("Erro candles:", symbol, e)

        return None


# =============================
# EMA
# =============================

def calcular_ema(prices, period):

    if len(prices) < period:
        return None

    k = 2 / (period + 1)

    ema = sum(prices[:period]) / period

    for p in prices[period:]:
        ema = (p - ema) * k + ema

    return ema


# =============================
# RSI
# =============================

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


# =============================
# VERIFICAR SINAL
# =============================

def verificar_sinal(symbol, prices):

    global last_state

    ema9 = calcular_ema(prices, EMA_SHORT)
    ema21 = calcular_ema(prices, EMA_MEDIUM)
    ema50 = calcular_ema(prices, EMA_LONG)

    rsi = calcular_rsi(prices)

    if not ema9 or not ema21 or not ema50 or not rsi:
        return

    agora = agora_brasil().strftime("%H:%M")

    print(
        f"{agora} | {symbol} | "
        f"Preço: {prices[-1]:.2f} | "
        f"EMA9: {ema9:.2f} | "
        f"EMA21: {ema21:.2f} | "
        f"EMA50: {ema50:.2f} | "
        f"RSI: {rsi:.1f}"
    )

    distancia = abs(ema9 - ema21)

    # evita sinais fracos
    if distancia < 0.25:
        return

    estado = None

    # BUY
    if ema9 > ema21 > ema50 and rsi > 55:
        estado = "BUY"

    # SELL
    elif ema9 < ema21 < ema50 and rsi < 45:
        estado = "SELL"

    if estado and estado != last_state[symbol]:

        mensagem = (
            f"{'🟢' if estado=='BUY' else '🔴'} "
            f"<b>{estado} PREVISTO</b>\n\n"
            f"Cripto: {symbol}\n"
            f"Entrada em ~2 candles\n"
            f"RSI: {rsi:.1f}\n"
            f"Hora: {agora}"
        )

        enviar_telegram(mensagem)

        last_state[symbol] = estado


# =============================
# MAIN
# =============================

def main():

    print("BOT MULTI-CRIPTO INICIADO")

    enviar_telegram(
        "🚀 <b>BOT MULTI-CRIPTO INICIADO</b>\n\n"
        "BTC ETH SOL ADA XRP\n"
        "EMA 9/21/50 + RSI"
    )

    while True:

        try:

            for symbol in SYMBOLS:

                prices = get_candles(symbol)

                if prices:

                    verificar_sinal(symbol, prices)

                else:

                    print("Sem dados:", symbol)

        except Exception as e:

            print("Erro geral:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
