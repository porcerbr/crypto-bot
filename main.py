import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIG
# ==========================

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT"]

SIGNAL_INTERVAL = 300  # 5 minutos
CHECK_INTERVAL = 30

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BOT_ATIVO = False
LAST_UPDATE_ID = None

last_signal_time = None

wins = 0
losses = 0

operacoes = []

# ==========================
# TEMPO
# ==========================

def agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)

def log(msg):
    print(f"[{agora().strftime('%H:%M:%S')}] {msg}", flush=True)

# ==========================
# TELEGRAM
# ==========================

def enviar(msg):

    try:

        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id":CHAT_ID,
                "text":msg
            },
            timeout=10
        )

        log("Mensagem Telegram enviada")

    except Exception as e:

        log(f"Erro Telegram: {e}")

def verificar_comandos():

    global BOT_ATIVO
    global LAST_UPDATE_ID

    try:

        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"

        params={}

        if LAST_UPDATE_ID:
            params["offset"]=LAST_UPDATE_ID+1

        r=requests.get(url,params=params,timeout=10)

        data=r.json()

        for update in data.get("result",[]):

            LAST_UPDATE_ID=update["update_id"]

            msg=update.get("message")

            if not msg:
                continue

            texto=msg.get("text","")

            if texto=="/start":

                BOT_ATIVO=True
                enviar("🟢 BOT ATIVADO")
                log("BOT ATIVADO")

            elif texto=="/stop":

                BOT_ATIVO=False
                enviar("🔴 BOT PARADO")
                log("BOT PARADO")

    except Exception as e:

        log(f"Erro comandos: {e}")

# ==========================
# PREÇO
# ==========================

def get_price(symbol):

    try:

        url="https://api.binance.com/api/v3/ticker/price"

        params={"symbol":symbol}

        r=requests.get(url,params=params,timeout=10)

        data=r.json()

        return float(data["price"])

    except Exception as e:

        log(f"Erro preço {symbol}: {e}")

        return None

# ==========================
# ESCOLHER ATIVO
# ==========================

def escolher_ativo():

    melhor=None
    melhor_score=0
    melhor_dir=None

    for symbol in SYMBOLS:

        preco=get_price(symbol)

        if preco is None:
            continue

        score=preco % 100  # força simulada (estável)

        if score>melhor_score:

            melhor_score=score
            melhor=symbol

            if int(preco)%2==0:
                melhor_dir="BUY"
            else:
                melhor_dir="SELL"

    return melhor,melhor_dir

# ==========================
# CRIAR SINAL
# ==========================

def criar_sinal():

    global last_signal_time

    symbol,direcao=escolher_ativo()

    if not symbol:
        return

    agora_time=agora()

    confirmacao=agora_time+timedelta(minutes=1)
    entrada=agora_time+timedelta(minutes=2)
    resultado=agora_time+timedelta(minutes=5)

    operacoes.append({

        "symbol":symbol,
        "direcao":direcao,
        "confirmacao":confirmacao,
        "entrada":entrada,
        "resultado":resultado,
        "preco":None,
        "confirmado":False

    })

    emoji="🟢 COMPRA" if direcao=="BUY" else "🔴 VENDA"

    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 {symbol}\n"
        f"{emoji}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}"
    )

    log(f"Sinal criado {symbol}")

    last_signal_time=agora_time

# ==========================
# RESULTADOS
# ==========================

def verificar_operacoes():

    global wins
    global losses

    agora_time=agora()

    novas=[]

    for op in operacoes:

        try:

            # confirmação

            if not op["confirmado"] and agora_time>=op["confirmacao"]:

                enviar(
                    "✅ ENTRADA CONFIRMADA ✅\n\n"
                    f"🌎 {op['symbol']}"
                )

                op["confirmado"]=True

                log("Entrada confirmada")

            # capturar preço

            if op["confirmado"] and op["preco"] is None and agora_time>=op["entrada"]:

                preco=get_price(op["symbol"])

                if preco:

                    op["preco"]=preco

                    log(f"Preço entrada {preco}")

            # resultado

            if op["preco"] and agora_time>=op["resultado"]:

                preco_atual=get_price(op["symbol"])

                if preco_atual:

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

                    log("Resultado enviado")

                    continue

            novas.append(op)

        except Exception as e:

            log(f"Erro operação: {e}")

            novas.append(op)

    operacoes.clear()
    operacoes.extend(novas)

# ==========================
# MAIN
# ==========================

def main():

    global last_signal_time

    enviar("🤖 BOT PRONTO")

    log("Sistema iniciado")

    while True:

        verificar_comandos()

        verificar_operacoes()

        if BOT_ATIVO:

            agora_time=agora()

            if last_signal_time is None:

                criar_sinal()

            else:

                tempo=(
                    agora_time-last_signal_time
                ).seconds

                if tempo>=SIGNAL_INTERVAL:

                    criar_sinal()

        time.sleep(CHECK_INTERVAL)

if __name__=="__main__":

    main()
