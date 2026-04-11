import os
import time
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOL = "ETHUSDT"

EMA_SHORT = 9
EMA_LONG = 21
RSI_PERIOD = 14

CHECK_INTERVAL = 60

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"

last_state = None
last_signal_time = 0
last_warning_time = 0


# ================================
# BUSCAR PREÇOS
# ================================

def fetch_prices():

    try:

        params = {
            "symbol": SYMBOL,
            "interval": "1m",
            "limit": 100
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


# ================================
# CALCULAR EMA
# ================================

def calculate_ema(prices, period):

    if len(prices) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(prices[:period]) / period

    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


# ================================
# CALCULAR RSI
# ================================

def calculate_rsi(prices, period=14):

    if len(prices) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):

        diff = prices[i] - prices[i - 1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi


# ================================
# PEGAR STOP DO CANDLE ANTERIOR
# ================================

def get_previous_candle_levels():

    try:

        params = {
            "symbol": SYMBOL,
            "interval": "1m",
            "limit": 2
        }

        r = requests.get(
            BINANCE_URL,
            params=params,
            timeout=10
        )

        data = r.json()

        prev_candle = data[-2]

        high = float(prev_candle[2])
        low = float(prev_candle[3])

        return high, low

    except Exception:

        return None, None


# ================================
# ENVIAR TELEGRAM
# ================================

def send_telegram(msg):

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }

    try:

        requests.post(url, json=payload, timeout=10)

        print("Mensagem enviada")

    except Exception as e:

        print("Erro Telegram:", e)


# ================================
# LÓGICA PRINCIPAL
# ================================

def check_signal(prices):

    global last_state
    global last_signal_time
    global last_warning_time

    if len(prices) < EMA_LONG + 20:
        return

    ema9 = calculate_ema(prices, EMA_SHORT)
    ema21 = calculate_ema(prices, EMA_LONG)

    ema9_prev = calculate_ema(prices[:-1], EMA_SHORT)
    ema21_prev = calculate_ema(prices[:-1], EMA_LONG)

    rsi = calculate_rsi(prices[-15:], RSI_PERIOD)
    rsi_prev = calculate_rsi(prices[-16:-1], RSI_PERIOD)

    if None in [ema9, ema21, ema9_prev, ema21_prev, rsi, rsi_prev]:
        return

    now_time = time.time()

    # ================================
    # PREVISÃO 2 CANDLES
    # ================================

    dist_now = abs(ema9 - ema21)
    dist_prev = abs(ema9_prev - ema21_prev)

    speed = dist_prev - dist_now

    if speed > 0:

        candles_to_cross = dist_now / speed

        if 1 <= candles_to_cross <= 2.5:

            if now_time - last_warning_time > 120:

                now = (
                    datetime.now(timezone.utc)
                    - timedelta(hours=3)
                ).strftime("%H:%M:%S")

                msg = (
                    f"⏳ <b>PREPARAR ENTRADA</b>\n\n"
                    f"Cripto: ETHUSDT\n"
                    f"RSI: {rsi:.1f}\n"
                    f"Cruzamento em ~{candles_to_cross:.1f} candles\n"
                    f"Hora: {now}"
                )

                send_telegram(msg)

                last_warning_time = now_time

    # ================================
    # CRUZAMENTO REAL
    # ================================

    state = "BUY" if ema9 > ema21 else "SELL"

    if last_state is None:
        last_state = state
        return

    if now_time - last_signal_time < 60:
        return

    # FILTRO RSI

    rsi_buy_ok = (
        rsi > 50 and
        rsi > rsi_prev and
        rsi < 70
    )

    rsi_sell_ok = (
        rsi < 50 and
        rsi < rsi_prev and
        rsi > 30
    )

    if state != last_state:

        if state == "BUY" and not rsi_buy_ok:
            return

        if state == "SELL" and not rsi_sell_ok:
            return

        now = (
            datetime.now(timezone.utc)
            - timedelta(hours=3)
        ).strftime("%H:%M:%S")

        emoji = "🟢" if state == "BUY" else "🔴"

        high, low = get_previous_candle_levels()

        if state == "BUY":
            stop_price = low
        else:
            stop_price = high

        current_price = prices[-1]

        msg = (
            f"{emoji} <b>{state} CONFIRMADO</b>\n\n"
            f"Cripto: ETHUSDT\n"
            f"Entrada: {current_price:.2f}\n"
            f"Stop: {stop_price:.2f}\n"
            f"RSI: {rsi:.1f}\n"
            f"Hora: {now}"
        )

        send_telegram(msg)

        last_state = state
        last_signal_time = now_time


# ================================
# MAIN
# ================================

def main():

    print("BOT ETH INICIADO")

    send_telegram(
        "<b>BOT ETH INICIADO</b>\n\n"
        "Modo previsão 2 candles ativo\n"
        "EMA 9 / EMA 21\n"
        "RSI 14 ativo\n"
        "Stop automático ativado\n"
        "Timeframe 1m"
    )

    while True:

        prices = fetch_prices()

        if prices is not None:

            check_signal(prices)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
