import requests
import time
from datetime import datetime, timedelta
import pandas as pd

# ==========================
# CONFIGURAÇÕES
# ==========================

TOKEN = "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ"
CHAT_ID = "1056795017"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "ADAUSDT"
]

INTERVAL = "1m"

wins = 0
losses = 0

operacoes_ativas = []

last_signal_time = None
SIGNAL_INTERVAL = 300  # 5 minutos

# ==========================
# TELEGRAM
# ==========================

def enviar(msg):

    try:

        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": msg
        }

        r = requests.post(url, data=payload, timeout=10)

        print("Telegram status:", r.status_code)

        if r.status_code != 200:
            print("Erro Telegram:", r.text)

    except Exception as e:

        print("Erro envio Telegram:", e)

LAST_UPDATE_ID = None
BOT_ATIVO = False

def verificar_comandos():

    global LAST_UPDATE_ID
    global BOT_ATIVO

    try:

        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

        params = {}

        if LAST_UPDATE_ID:
            params["offset"] = LAST_UPDATE_ID + 1

        r = requests.get(
            url,
            params=params,
            timeout=10
        )

        data = r.json()

        if "result" not in data:
            return

        for update in data["result"]:

            LAST_UPDATE_ID = update["update_id"]

            if "message" not in update:
                continue

            texto = update["message"].get("text","")

            # 🔵 START
            if texto == "/start":

                BOT_ATIVO = True

                enviar("🟢 BOT ATIVADO")

            # 🔴 STOP
            elif texto == "/stop":

                BOT_ATIVO = False

                enviar("🔴 BOT PARADO")

    except Exception as e:

        print("Erro comandos:", e)

# ==========================
# TEMPO
# ==========================

def agora():

    return datetime.now() - timedelta(hours=3)
    
# ==========================
# PREÇO (CORRIGIDO)
# ==========================

def get_price(symbol):

    try:

        # converter BTCUSDT → BTC-USDT
        kucoin_symbol = symbol.replace("USDT", "-USDT")

        url = (
            "https://api.kucoin.com/api/v1/market/orderbook/level1"
            f"?symbol={kucoin_symbol}"
        )

        r = requests.get(url, timeout=10)

        data = r.json()

        if "data" in data:

            return float(data["data"]["price"])

        return None

    except Exception as e:

        print(f"Erro preço {symbol}: {e}")

        return None
        
# ==========================
# CANDLES
# ==========================

    
def get_candles(symbol):

    try:

        kucoin_symbol = symbol.replace("USDT", "-USDT")

        url = (
            "https://api.kucoin.com/api/v1/market/candles"
            f"?type=1min"
            f"&symbol={kucoin_symbol}"
        )

        r = requests.get(url, timeout=10)

        data = r.json()

        if "data" not in data:

            print(
                f"Resposta inválida {symbol}: {data}"
            )

            return None

        candles = data["data"]

        df = pd.DataFrame(candles)

        df = df.iloc[:, 0:6]

        df.columns = [
            "time",
            "open",
            "close",
            "high",
            "low",
            "volume"
        ]

        df["close"] = df["close"].astype(float)

        df = df[::-1]  # inverter ordem

        return df

    except Exception as e:

        print(f"Erro candles {symbol}: {e}")

        return None
        
# ==========================
# INDICADORES
# ==========================

def calcular_indicadores(df):

    df["EMA9"] = df["close"].ewm(span=9).mean()
    df["EMA21"] = df["close"].ewm(span=21).mean()

    delta = df["close"].diff()

    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()

    rs = gain / loss

    df["RSI"] = 100 - (100 / (1 + rs))

    return df

#==================
#VERIFICAR SE JA TEM OPERAÇÃO 
#==================

def ja_tem_operacao(symbol):

    for op in operacoes_ativas:

        if op["symbol"] == symbol:

            return True

    return False

#======================
#ESCOLHER MELHOR ATIVO
#======================

def escolher_melhor_ativo():

    melhor_symbol = None
    melhor_score = 0
    melhor_direcao = None

    for symbol in SYMBOLS:

        if ja_tem_operacao(symbol):
            continue

        df = get_candles(symbol)

        if df is None:
            continue

        df = calcular_indicadores(df)

        ultima = df.iloc[-1]

        ema9 = ultima["EMA9"]
        ema21 = ultima["EMA21"]

        rsi = ultima["RSI"]

        if ema9 is None or ema21 is None:
            continue

        distancia = abs(ema9 - ema21)

        # 🔥 LÓGICA MAIS FLEXÍVEL

        if ema9 > ema21 and rsi > 45:

            direcao = "BUY"

        elif ema9 < ema21 and rsi < 55:

            direcao = "SELL"

        else:
            continue

        # score baseado na força
        score = distancia

        if score > melhor_score:

            melhor_score = score
            melhor_symbol = symbol
            melhor_direcao = direcao

    return melhor_symbol, melhor_direcao

# ==========================
# GERAR SINAL
# ==========================

def criar_sinal(symbol, direcao):

    # 🔴 EVITAR DUPLICADO
    if ja_tem_operacao(symbol):
        return

    preco = get_price(symbol)

    if preco is None:
        return

    tempo = agora()

    entrada = tempo + timedelta(minutes=2)

    p1 = entrada + timedelta(minutes=1)

    p2 = p1 + timedelta(minutes=1)

    op = {
        "symbol": symbol,
        "direcao": direcao,
        "preco": preco,
        "tempo_entrada": entrada,
        "tempo_protecao1": p1,
        "tempo_protecao2": p2,
        "etapa": 0
    }

    operacoes_ativas.append(op)

    enviar(
        "✅ ENTRADA CONFIRMADA ✅\n\n"
        f"🌎 Ativo: {symbol}\n"
        f"📊 Estratégia: "
        f"{'🟢 COMPRA' if direcao=='BUY' else '🔴 VENDA'}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}\n\n"
        f"⚠️ Proteção 1 {p1.strftime('%H:%M')}\n"
        f"⚠️ Proteção 2 {p2.strftime('%H:%M')}"
    )


# ==========================
# RESULTADO
# ==========================

def enviar_resultado(symbol, resultado):

    global wins
    global losses

    total = wins + losses

    taxa = (wins / total) * 100 if total > 0 else 0

    enviar(
        "🏆 RESULTADO\n\n"
        f"🌎 {symbol}\n"
        f"{'✅' if 'WIN' in resultado else '❌'} {resultado}\n\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Precisão: {round(taxa,1)}%"
    )

# ==========================
# VERIFICAR RESULTADOS
# ==========================

def verificar_resultados():

    global wins
    global losses

    agora_time = agora()

    novas_operacoes = []

    for op in operacoes_ativas:

        symbol = op["symbol"]
        direcao = op["direcao"]

        df = get_candles(symbol)

        if df is None:
            novas_operacoes.append(op)
            continue

        # pegar últimos candles
        ultimo = df.iloc[-1]
        anterior = df.iloc[-2]
        anterior2 = df.iloc[-3]

        # ==========================
        # ENTRADA
        # ==========================

        if op["etapa"] == 0:

            if agora_time >= op["tempo_entrada"]:

                preco_entrada = float(anterior["close"])
                preco_saida = float(ultimo["close"])

                win = (
                    preco_saida > preco_entrada
                    if direcao == "BUY"
                    else preco_saida < preco_entrada
                )

                if win:

                    wins += 1

                    enviar_resultado(
                        symbol,
                        "WIN na Entrada"
                    )

                    continue

                else:

                    op["etapa"] = 1
                    novas_operacoes.append(op)

            else:

                novas_operacoes.append(op)

        # ==========================
        # PROTEÇÃO 1
        # ==========================

        elif op["etapa"] == 1:

            if agora_time >= op["tempo_protecao1"]:

                preco_entrada = float(anterior2["close"])
                preco_saida = float(anterior["close"])

                win = (
                    preco_saida > preco_entrada
                    if direcao == "BUY"
                    else preco_saida < preco_entrada
                )

                if win:

                    wins += 1

                    enviar_resultado(
                        symbol,
                        "WIN na Proteção 1"
                    )

                    continue

                else:

                    op["etapa"] = 2
                    novas_operacoes.append(op)

            else:

                novas_operacoes.append(op)

        # ==========================
        # PROTEÇÃO 2
        # ==========================

        elif op["etapa"] == 2:

            if agora_time >= op["tempo_protecao2"]:

                preco_entrada = float(anterior["close"])
                preco_saida = float(ultimo["close"])

                win = (
                    preco_saida > preco_entrada
                    if direcao == "BUY"
                    else preco_saida < preco_entrada
                )

                if win:

                    wins += 1

                    enviar_resultado(
                        symbol,
                        "WIN na Proteção 2"
                    )

                else:

                    losses += 1

                    enviar_resultado(
                        symbol,
                        "LOSS após Proteção 2"
                    )

                continue

            else:

                novas_operacoes.append(op)

    operacoes_ativas.clear()
    operacoes_ativas.extend(novas_operacoes)
                    

# ==========================
# LOOP PRINCIPAL
# ==========================

def main():

    global last_signal_time

    print("BOT INICIANDO...")

    enviar("🤖 BOT INICIADO COM SUCESSO")

    while True:

        try:

            verificar_comandos()

            if BOT_ATIVO:

                agora_time = agora()

                pode_enviar = False

                # Controle de tempo entre sinais
                if last_signal_time is None:

                    pode_enviar = True

                else:

                    tempo = (agora_time - last_signal_time).seconds

                    if tempo >= SIGNAL_INTERVAL:

                        pode_enviar = True

                if pode_enviar:

                    symbol, direcao = escolher_melhor_ativo()

                    if symbol:

                        criar_sinal(symbol, direcao)

                        last_signal_time = agora_time

                verificar_resultados()

            time.sleep(30)

        except Exception as e:

            print("Erro geral:", e)

            time.sleep(10)
            
# ==========================

main()
