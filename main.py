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
COOLDOWN_MINUTES = 3

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BOT_ATIVO = False
LAST_UPDATE_ID = None

last_signal_time = {s: None for s in SYMBOLS}

wins = 0
losses = 0

operacoes_ativas = []

# ==========================
# HORÁRIO BR
# ==========================

def agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)

# ==========================
# TELEGRAM
# ==========================

def enviar(msg):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(url,json={
            "chat_id":CHAT_ID,
            "text":msg
        })

        print("[Telegram] Mensagem enviada")

    except Exception as e:

        print("Erro Telegram:",e)

def verificar_comandos():

    global BOT_ATIVO
    global LAST_UPDATE_ID

    try:

        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

        data=requests.get(url).json()

        for update in data["result"]:

            uid=update["update_id"]

            if LAST_UPDATE_ID and uid<=LAST_UPDATE_ID:
                continue

            LAST_UPDATE_ID=uid

            if "message" not in update:
                continue

            texto=update["message"].get("text","")

            if texto=="/start":

                BOT_ATIVO=True
                enviar("🟢 BOT ATIVADO")

            elif texto=="/stop":

                BOT_ATIVO=False
                enviar("🔴 BOT PARADO")

    except Exception as e:

        print("Erro comandos:",e)

# ==========================
# DADOS
# ==========================

def get_data(symbol):

    try:

        print(f"Buscando {symbol}")

        url="https://data-api.binance.vision/api/v3/klines"

        params={
            "symbol":symbol,
            "interval":"1m",
            "limit":100
        }

        data=requests.get(url,params=params).json()

        closes=[float(c[4]) for c in data]
        highs=[float(c[2]) for c in data]
        lows=[float(c[3]) for c in data]

        return closes,highs,lows

    except Exception as e:

        print("Erro dados:",symbol,e)

        return None,None,None

def get_price(symbol):

    url="https://api.binance.com/api/v3/ticker/price"

    params={"symbol":symbol}

    data=requests.get(url,params=params).json()

    return float(data["price"])

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

def atr(highs,lows):

    trs=[]

    for i in range(1,ATR_PERIOD):

        trs.append(highs[i]-lows[i])

    return sum(trs)/len(trs)

# ==========================
# LÓGICA
# ==========================

def gerar_sinal(symbol, closes, highs, lows):

    try:

        e9=ema(closes,EMA_FAST)
        e21=ema(closes,EMA_SLOW)
        e50=ema(closes,EMA_TREND)

        r=rsi(closes)
        vol=atr(highs,lows)

        distancia=abs(e9-e21)

        print(
            f"{symbol} | "
            f"EMA9:{round(e9,2)} "
            f"EMA21:{round(e21,2)} "
            f"RSI:{round(r,1)}"
        )

        if vol < 0.15:
            return None

        if distancia < 0.04:
            return None

        if e9>e21 and e9>e50 and r>52:
            return "BUY"

        if e9<e21 and e9<e50 and r<48:
            return "SELL"

        return None

    except Exception as e:

        print("Erro sinal:",symbol,e)

        return None

# ==========================
# RESULTADOS
# ==========================

def verificar_resultados():

    global wins
    global losses

    agora_time = agora()

    novas_operacoes=[]

    for op in operacoes_ativas:

        tempo_passado = (
            agora_time - op["tempo"]
        ).seconds

        if tempo_passado >= 180:

            preco_atual = get_price(
                op["symbol"]
            )

            direcao = op["direcao"]
            preco_entrada = op["preco"]

            if direcao=="BUY":

                if preco_atual > preco_entrada:
                    wins+=1
                    resultado="WIN"
                else:
                    losses+=1
                    resultado="LOSS"

            else:

                if preco_atual < preco_entrada:
                    wins+=1
                    resultado="WIN"
                else:
                    losses+=1
                    resultado="LOSS"

            total = wins + losses

            taxa = (wins/total)*100

            enviar(

                "🏆 RESULTADO\n\n"

                f"🌎 Ativo: {op['symbol']}\n"
                f"📊 Resultado: {'✅ WIN' if resultado=='WIN' else '❌ LOSS'}\n\n"

                "📊 Estatísticas:\n"
                f"Wins: {wins}\n"
                f"Loss: {losses}\n"
                f"Precisão: {round(taxa,1)}%"
            )

        else:

            novas_operacoes.append(op)

    operacoes_ativas.clear()
    operacoes_ativas.extend(novas_operacoes)

# ==========================
# MENSAGENS
# ==========================

def preparar_msg(symbol,direcao):

    entrada=agora()+timedelta(minutes=2)

    emoji="🟢 COMPRA" if direcao=="BUY" else "🔴 VENDA"

    return(

        "⚠️ PREPARAR ENTRADA ⚠️\n\n"

        f"🌎 Ativo: {symbol}\n"
        f"📊 Estratégia: {emoji}\n"
        f"⏰ Entrada prevista: {entrada.strftime('%H:%M')}"
    )

def confirmar_msg(symbol,direcao):

    entrada=agora()+timedelta(minutes=1)

    p1=entrada+timedelta(minutes=1)
    p2=entrada+timedelta(minutes=2)

    emoji="🟢 COMPRA" if direcao=="BUY" else "🔴 VENDA"

    preco_entrada=get_price(symbol)

    operacoes_ativas.append({

        "symbol":symbol,
        "direcao":direcao,
        "preco":preco_entrada,
        "tempo":agora()

    })

    return(

        "✅ ENTRADA CONFIRMADA ✅\n\n"

        f"🌎 Ativo: {symbol}\n"
        "⏳ Expiração: M1\n"
        f"📊 Estratégia: {emoji}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}\n\n"

        f"⚠️ Proteção 1: {p1.strftime('%H:%M')}\n"
        f"⚠️ Proteção 2: {p2.strftime('%H:%M')}"
    )

# ==========================
# MAIN
# ==========================

def main():

    enviar("🤖 BOT COM WIN/LOSS ATIVO")

    while True:

        verificar_comandos()

        verificar_resultados()

        if BOT_ATIVO:

            for symbol in SYMBOLS:

                closes,highs,lows=get_data(symbol)

                if not closes:
                    continue

                direcao=gerar_sinal(
                    symbol,
                    closes,
                    highs,
                    lows
                )

                if direcao:

                    agora_time=agora()

                    ultimo=last_signal_time[symbol]

                    if(
                        ultimo is None or
                        (agora_time-ultimo).seconds >
                        COOLDOWN_MINUTES*60
                    ):

                        enviar(
                            preparar_msg(
                                symbol,
                                direcao
                            )
                        )

                        time.sleep(60)

                        enviar(
                            confirmar_msg(
                                symbol,
                                direcao
                            )
                        )

                        last_signal_time[symbol]=agora_time

        time.sleep(CHECK_INTERVAL)

if __name__=="__main__":
    main()
