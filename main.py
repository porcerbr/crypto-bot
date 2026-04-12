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
RSI_PERIOD = 14

SIGNAL_INTERVAL = 300  # 5 minutos

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BOT_ATIVO = False
LAST_UPDATE_ID = None

last_signal_time = None

wins = 0
losses = 0

operacoes_ativas = []

# ==========================
# HORÁRIO
# ==========================

def agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)

# ==========================
# TELEGRAM
# ==========================

def enviar(msg):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": msg
            }
        )

        print("[Telegram] OK")

    except Exception as e:

        print("Erro Telegram:", e)

def verificar_comandos():

    global BOT_ATIVO
    global LAST_UPDATE_ID

    try:

        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

        params={}

        if LAST_UPDATE_ID:
            params["offset"]=LAST_UPDATE_ID+1

        data=requests.get(url,params=params).json()

        for update in data["result"]:

            LAST_UPDATE_ID=update["update_id"]

            if "message" not in update:
                continue

            texto=update["message"].get("text","")

            if texto=="/start":

                BOT_ATIVO=True
                enviar("🟢 BOT ATIVADO")

            elif texto=="/stop":

                BOT_ATIVO=False
                enviar("🔴 BOT PARADO")

    except:
        pass

# ==========================
# DADOS
# ==========================

def get_data(symbol):

    try:

        url="https://data-api.binance.vision/api/v3/klines"

        params={
            "symbol":symbol,
            "interval":"1m",
            "limit":50
        }

        data=requests.get(url,params=params).json()

        closes=[float(c[4]) for c in data]

        return closes

    except:

        return None

def get_price(symbol):

    try:

        url="https://api.binance.com/api/v3/ticker/price"

        params={"symbol":symbol}

        data=requests.get(url,params=params).json()

        return float(data["price"])

    except:

        return None

# ==========================
# INDICADORES
# ==========================

def ema(prices,period):

    k=2/(period+1)

    e=sum(prices[:period])/period

    for p in prices[period:]:
        e=(p-e)*k+e

    return e

def rsi(prices):

    gains=[]
    losses=[]

    for i in range(1,RSI_PERIOD+1):

        diff=prices[i]-prices[i-1]

        gains.append(max(diff,0))
        losses.append(abs(min(diff,0)))

    avg_gain=sum(gains)/RSI_PERIOD
    avg_loss=sum(losses)/RSI_PERIOD

    if avg_loss==0:
        return 100

    rs=avg_gain/avg_loss

    return 100-(100/(1+rs))

# ==========================
# ESCOLHER MELHOR ATIVO
# ==========================

def escolher_ativo():

    melhor_symbol=None
    melhor_score=0
    melhor_direcao=None

    for symbol in SYMBOLS:

        closes=get_data(symbol)

        if not closes:
            continue

        e9=ema(closes,EMA_FAST)
        e21=ema(closes,EMA_SLOW)

        r=rsi(closes)

        distancia=abs(e9-e21)

        score=distancia

        if e9>e21:
            direcao="BUY"
        else:
            direcao="SELL"

        if score>melhor_score:

            melhor_score=score
            melhor_symbol=symbol
            melhor_direcao=direcao

    return melhor_symbol,melhor_direcao

# ==========================
# RESULTADOS
# ==========================

def verificar_resultados():

    global wins
    global losses

    agora_time=agora()

    novas=[]

    for op in operacoes_ativas:

        if agora_time>=op["tempo_resultado"]:

            preco_atual=get_price(op["symbol"])

            if preco_atual is None:
                novas.append(op)
                continue

            if op["direcao"]=="BUY":

                if preco_atual>op["preco"]:
                    wins+=1
                    resultado="WIN"
                else:
                    losses+=1
                    resultado="LOSS"

            else:

                if preco_atual<op["preco"]:
                    wins+=1
                    resultado="WIN"
                else:
                    losses+=1
                    resultado="LOSS"

            total=wins+losses

            taxa=(wins/total)*100

            enviar(
                "🏆 RESULTADO\n\n"
                f"🌎 {op['symbol']}\n"
                f"{'✅ WIN' if resultado=='WIN' else '❌ LOSS'}\n\n"
                f"Wins: {wins}\n"
                f"Loss: {losses}\n"
                f"Precisão: {round(taxa,1)}%"
            )

        else:

            novas.append(op)

    operacoes_ativas.clear()
    operacoes_ativas.extend(novas)

# ==========================
# CRIAR SINAL
# ==========================

def criar_sinal(symbol,direcao):

    global last_signal_time

    agora_time=agora()

    entrada=agora_time+timedelta(minutes=2)

    resultado=entrada+timedelta(minutes=3)

    preco=get_price(symbol)

    if preco is None:
        return

    operacoes_ativas.append({

        "symbol":symbol,
        "direcao":direcao,
        "preco":preco,
        "tempo_resultado":resultado

    })

    last_signal_time=agora_time

    emoji="🟢 COMPRA" if direcao=="BUY" else "🔴 VENDA"

    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 {symbol}\n"
        f"{emoji}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}"
    )

# ==========================
# MAIN
# ==========================

def main():

    global last_signal_time

    enviar("🤖 BOT TEMPO CURTO ATIVO")

    while True:

        verificar_comandos()

        verificar_resultados()

        if BOT_ATIVO:

            agora_time=agora()

            pode=False

            if last_signal_time is None:
                pode=True

            else:

                tempo=(
                    agora_time-last_signal_time
                ).seconds

                if tempo>=SIGNAL_INTERVAL:
                    pode=True

            if pode:

                symbol,direcao=escolher_ativo()

                if symbol:

                    criar_sinal(
                        symbol,
                        direcao
                    )

        time.sleep(60)

if __name__=="__main__":
    main()
