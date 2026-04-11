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

# MODO ESTUDO (mais sinais)
MODO_ESTUDO = True

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

last_signal = {s: None for s in SYMBOLS}
prediction_flag = {s: False for s in SYMBOLS}


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
            "text": msg,
            "parse_mode": "HTML"
        }

        requests.post(url, json=payload)

    except Exception as e:

        print("Erro Telegram:", e)


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
# SCORE FLEXÍVEL
# ==========================

def calcular_score(e9, e21, e50, r):

    score = 0

    if e9 > e21 or e9 < e21:
        score += 30

    if e9 > e50 or e9 < e50:
        score += 25

    if r > 52 or r < 48:
        score += 25

    score += 20

    return score


# ==========================
# VERIFICAR
# ==========================

def verificar(symbol, prices):

    global last_signal
    global prediction_flag

    e9 = ema(prices, EMA_SHORT)
    e21 = ema(prices, EMA_MEDIUM)
    e50 = ema(prices, EMA_LONG)

    r = rsi(prices)

    if not e9 or not e21 or not e50 or not r:
        return

    agora_str = agora().strftime("%H:%M")

    print(
        f"{agora_str} | {symbol} | "
        f"E9:{e9:.2f} "
        f"E21:{e21:.2f} "
        f"E50:{e50:.2f} "
        f"RSI:{r:.1f}"
    )

    distancia = abs(e9 - e21)

    # distância menor (modo estudo)
    if distancia < 0.08:
        prediction_flag[symbol] = False
        return

    estado = None

    if e9 > e21:
        estado = "BUY"

    elif e9 < e21:
        estado = "SELL"

    score = calcular_score(e9, e21, e50, r)

    # score mais leve
    if score < 45:
        return

    # PREVISÃO

    if not prediction_flag[symbol]:

        enviar(
            f"⚠️ POSSÍVEL {estado}\n\n"
            f"{symbol}\n"
            f"Score: {score}\n"
            f"RSI:{r:.1f}\n"
            f"Hora:{agora_str}"
        )

        prediction_flag[symbol] = True

    # ALERTA FINAL

    segundos = agora().second

    if segundos >= 58:

        if estado != last_signal[symbol]:

            enviar(
                f"⏰ ENTRAR AGORA\n\n"
                f"{symbol}\n"
                f"Tipo: {estado}\n"
                f"Score: {score}\n"
                f"Stop: candle anterior\n"
                f"Hora:{agora_str}"
            )

            last_signal[symbol] = estado


# ==========================
# MAIN
# ==========================

def main():

    print("BOT MODO ESTUDO INICIADO")

    enviar(
        "📊 BOT MODO ESTUDO ATIVO\n"
        "Mais sinais habilitados"
    )

    while True:

        try:

            for symbol in SYMBOLS:

                prices = get_candles(symbol)

                if prices:

                    verificar(symbol, prices)

        except Exception as e:

            print("Erro geral:", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
