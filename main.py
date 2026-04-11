import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIG
# ==========================

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT"]

EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50

RSI_PERIOD = 14
ATR_PERIOD = 14

CHECK_INTERVAL = 60
COOLDOWN_MINUTES = 5

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BOT_ATIVO = False
LAST_UPDATE_ID = None

last_signal_time = {s: None for s in SYMBOLS}


# ==========================
# HORÁRIO BR
# ==========================

def agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)


# ==========================
# TELEGRAM
# ==========================

def enviar(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": msg})


def verificar_comandos():

    global BOT_ATIVO
    global LAST_UPDATE_ID

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

    data = requests.get(url).json()

    for update in data["result"]:

        uid = update["update_id"]

        if LAST_UPDATE_ID and uid <= LAST_UPDATE_ID:
            continue

        LAST_UPDATE_ID = uid

        if "message" not in update:
            continue

        texto = update["message"].get("text","")

        if texto == "/start":

            BOT_ATIVO = True
            enviar("🟢 BOT ATIVADO")

        elif texto == "/stop":

            BOT_ATIVO = False
            enviar("🔴 BOT PARADO")


# ==========================
# DADOS
# ==========================

def get_data(symbol):

    url = "https://data-api.binance.vision/api/v3/klines"

    params = {
        "symbol": symbol,
        "interval": "1m",
        "limit": 100
    }

    data = requests.get(url, params=params).json()

    closes = [float(c[4]) for c in data]
    highs  = [float(c[2]) for c in data]
    lows   = [float(c[3]) for c in data]

    return closes, highs, lows


# ==========================
# INDICADORES
# ==========================

def ema(prices, period):

    k = 2/(period+1)

    e = sum(prices[:period])/period

    for p in prices[period:]:

        e = (p-e)*k + e

    return e


def rsi(prices):

    gains=[]
    losses=[]

    for i in range(1, RSI_PERIOD+1):

        diff = prices[i]-prices[i-1]

        gains.append(max(diff,0))
        losses.append(abs(min(diff,0)))

    avg_gain=sum(gains)/RSI_PERIOD
    avg_loss=sum(losses)/RSI_PERIOD

    if avg_loss==0:
        return 100

    rs=avg_gain/avg_loss

    return 100-(100/(1+rs))


def atr(highs,lows):

    trs=[]

    for i in range(1, ATR_PERIOD):

        tr=highs[i]-lows[i]
        trs.append(tr)

    return sum(trs)/len(trs)


# ==========================
# LÓGICA MAIS ASSERTIVA
# ==========================

def gerar_sinal(symbol, closes, highs, lows):

    e9  = ema(closes, EMA_FAST)
    e21 = ema(closes, EMA_SLOW)
    e50 = ema(closes, EMA_TREND)

    r = rsi(closes)
    vol = atr(highs, lows)

    distancia = abs(e9-e21)

    # ❌ Evita mercado lateral
    if vol < 0.25:
        return None

    if distancia < 0.07:
        return None

    tendencia = abs(e9 - e50)

    if tendencia < 0.1:
        return None

    # 🔥 COMPRA FORTE
    if e9 > e21 and e9 > e50 and r > 55:

        return "BUY","FORTE"

    # 🔴 VENDA FORTE
    if e9 < e21 and e9 < e50 and r < 45:

        return "SELL","FORTE"

    return None


# ==========================
# FORMATAR
# ==========================

def formatar(symbol, direcao, forca):

    agora_time = agora()

    entrada = agora_time + timedelta(minutes=1)

    p1 = entrada + timedelta(minutes=1)
    p2 = entrada + timedelta(minutes=2)

    emoji = "🟢 COMPRA" if direcao=="BUY" else "🔴 VENDA"

    return (

        "✅ ENTRADA CONFIRMADA ✅\n\n"

        f"🌎 Ativo: {symbol}\n"
        "⏳ Expiração: M1\n"
        f"📊 Estratégia: {emoji}\n"
        f"📈 Tendência: {forca}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}\n\n"

        f"⚠️ Proteção 1: {p1.strftime('%H:%M')}\n"
        f"⚠️ Proteção 2: {p2.strftime('%H:%M')}"
    )


# ==========================
# MAIN
# ==========================

def main():

    enviar("🤖 BOT M1 ASSERTIVO INICIADO")

    while True:

        verificar_comandos()

        if BOT_ATIVO:

            for symbol in SYMBOLS:

                closes, highs, lows = get_data(symbol)

                sinal = gerar_sinal(symbol, closes, highs, lows)

                if sinal:

                    direcao, forca = sinal

                    agora_time = agora()

                    ultimo = last_signal_time[symbol]

                    if (
                        ultimo is None or
                        (agora_time - ultimo).seconds > COOLDOWN_MINUTES*60
                    ):

                        enviar(formatar(symbol,direcao,forca))

                        last_signal_time[symbol]=agora_time

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
