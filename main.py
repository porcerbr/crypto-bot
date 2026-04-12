import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIGURAÇÕES
# ==========================

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT"]

EMA_FAST = 9
EMA_SLOW = 21

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

        requests.post(
            url,
            json={
                "chat_id": CHAT_ID,
                "text": msg
            },
            timeout=10
        )

        print("[Telegram] OK")

    except Exception as e:

        print("Erro Telegram:", e)

# ==========================
# COMANDOS TELEGRAM
# ==========================

def verificar_comandos():

    global BOT_ATIVO
    global LAST_UPDATE_ID

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

        params = {}

        if LAST_UPDATE_ID:
            params["offset"] = LAST_UPDATE_ID + 1

        data = requests.get(
            url,
            params=params,
            timeout=10
        ).json()

        if "result" not in data:
            return

        for update in data["result"]:

            LAST_UPDATE_ID = update["update_id"]

            if "message" not in update:
                continue

            texto = update["message"].get("text","")

            if texto == "/start":

                BOT_ATIVO = True
                enviar("🟢 BOT ATIVADO")

            elif texto == "/stop":

                BOT_ATIVO = False
                enviar("🔴 BOT PARADO")

    except Exception as e:

        print("Erro comandos:", e)

# ==========================
# DADOS BINANCE
# ==========================

def get_data(symbol):

    try:

        print(f"Buscando candles de {symbol}")

        url="https://data-api.binance.vision/api/v3/klines"

        params={
            "symbol":symbol,
            "interval":"1m",
            "limit":50
        }

        response=requests.get(
            url,
            params=params,
            timeout=10
        )

        data=response.json()

        if not isinstance(data,list):

            print("Resposta inválida:", data)
            return None

        closes=[]

        for candle in data:

            closes.append(float(candle[4]))

        return closes

    except Exception as e:

        print("Erro dados",symbol,e)
        return None

# ==========================
# PREÇO
# ==========================

def get_price(symbol):

    try:

        url="https://data-api.binance.vision/api/v3/ticker/price"

        params={"symbol":symbol}

        response=requests.get(
            url,
            params=params,
            timeout=10
        )

        data=response.json()

        if "price" not in data:
            return None

        return float(data["price"])

    except Exception as e:

        print("Erro preço:",symbol,e)
        return None

# ==========================
# EMA
# ==========================

def ema(prices,period):

    if len(prices)<period:
        return None

    k=2/(period+1)

    e=sum(prices[:period])/period

    for p in prices[period:]:

        e=(p-e)*k+e

    return e

# ==========================
# ESCOLHER ATIVO
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

        if e9 is None or e21 is None:
            continue

        distancia=abs(e9-e21)

        if e9>e21:
            direcao="BUY"
        else:
            direcao="SELL"

        if distancia>melhor_score:

            melhor_score=distancia
            melhor_symbol=symbol
            melhor_direcao=direcao

    return melhor_symbol,melhor_direcao

# ==========================
# CRIAR SINAL
# ==========================

def criar_sinal(symbol,direcao):

    global last_signal_time

    agora_time=agora()

    entrada=agora_time+timedelta(minutes=2)
    protecao1=entrada+timedelta(minutes=1)
    protecao2=entrada+timedelta(minutes=2)

    resultado=protecao2+timedelta(minutes=1)

    preco=get_price(symbol)

    if preco is None:
        print("Sem preço...")
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
        "✅ ENTRADA CONFIRMADA ✅\n\n"
        f"🌎 Ativo: {symbol}\n"
        f"📊 Estratégia: {emoji}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}\n\n"
        f"⚠️ Proteção 1 {protecao1.strftime('%H:%M')}\n"
        f"⚠️ Proteção 2 {protecao2.strftime('%H:%M')}"
    )

# ==========================
# RESULTADOS (WIN/LOSS)
# ==========================

def verificar_resultados():

    global wins
    global losses

    agora_time = agora()

    novas_operacoes = []

    for op in operacoes_ativas:

        if agora_time >= op["tempo_resultado"]:

            print("Verificando resultado:", op["symbol"])

            preco_final = get_price(op["symbol"])

            if preco_final is None:

                novas_operacoes.append(op)
                continue

            if op["direcao"] == "BUY":

                if preco_final > op["preco"]:
                    wins += 1
                    resultado = "WIN"
                else:
                    losses += 1
                    resultado = "LOSS"

            else:

                if preco_final < op["preco"]:
                    wins += 1
                    resultado = "WIN"
                else:
                    losses += 1
                    resultado = "LOSS"

            total = wins + losses

            taxa = (wins / total) * 100

            enviar(
                "🏆 RESULTADO\n\n"
                f"🌎 {op['symbol']}\n"
                f"{'✅ WIN' if resultado=='WIN' else '❌ LOSS'}\n\n"
                f"Wins: {wins}\n"
                f"Losses: {losses}\n"
                f"Precisão: {round(taxa,1)}%"
            )

        else:

            novas_operacoes.append(op)

    operacoes_ativas.clear()
    operacoes_ativas.extend(novas_operacoes)

# ==========================
# LOOP PRINCIPAL
# ==========================

def main():

    global last_signal_time

    enviar("🤖 BOT INICIADO")

    while True:

        verificar_comandos()

        verificar_resultados()

        if BOT_ATIVO:

            agora_time=agora()

            pode=False

            if last_signal_time is None:
                pode=True

            else:

                tempo=(agora_time-last_signal_time).seconds

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
