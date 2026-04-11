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


# ==========================
# SCORE DO SINAL
# ==========================

def calcular_score(e9, e21, e50, r, prices):

    score = 0

    # tendência alinhada
    if e9 > e21 > e50 or e9 < e21 < e50:
        score += 40

    # força da distância
    distancia = abs(e9 - e21)

    if distancia > 0.4:
        score += 25

    # RSI saudável
    if 55 < r < 70 or 30 < r < 45:
        score += 20

    # momentum
    momentum = abs(prices[-1] - prices[-2])

    if momentum > 0.2:
        score += 15

    return score


def qualidade(score):

    if score >= 75:
        return "ALTA"

    if score >= 60:
        return "MÉDIA"

    return "BAIXA"


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

    distancia = abs(e9 - e21)

    # FILTRO LATERAL
    if distancia < 0.20:
        prediction_flag[symbol] = False
        return

    estado = None

    if e9 > e21 > e50 and r > 55:
        estado = "BUY"

    elif e9 < e21 < e50 and r < 45:
        estado = "SELL"

    if not estado:
        return

    score = calcular_score(e9, e21, e50, r, prices)

    qual = qualidade(score)

    if score < 60:
        return

    # PREVISÃO

    if not prediction_flag[symbol]:

        enviar(
            f"⚠️ <b>POSSÍVEL {estado}</b>\n\n"
            f"{symbol}\n"
            f"Score: {score}/100\n"
            f"Qualidade: {qual}\n"
            f"RSI:{r:.1f}\n"
            f"Hora:{agora_str}"
        )

        prediction_flag[symbol] = True

    # ALERTA FINAL

    segundos = agora().second

    if segundos >= 58:

        if estado != last_signal[symbol]:

            enviar(
                f"⏰ <b>ENTRAR AGORA</b>\n\n"
                f"{symbol}\n"
                f"Tipo: {estado}\n"
                f"Score: {score}/100\n"
                f"Qualidade: {qual}\n"
                f"Stop: candle anterior\n"
                f"Hora:{agora_str}"
            )

            last_signal[symbol] = estado


def main():

    print("BOT PROFISSIONAL INICIADO")

    enviar(
        "🚀 <b>BOT PROFISSIONAL ATIVO</b>\n\n"
        "Score + Rompimento + Filtro lateral"
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
