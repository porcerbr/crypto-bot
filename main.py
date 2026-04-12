import requests
import time
from datetime import datetime, timedelta
import pandas as pd

# ==========================
# CONFIGURAÇÕES
# ==========================

TOKEN = "SEU_TOKEN_TELEGRAM"
CHAT_ID = "SEU_CHAT_ID"

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

# ==========================
# TELEGRAM
# ==========================

def enviar(msg):

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": msg
    }

    try:
        requests.post(url, data=payload)
    except:
        pass

# ==========================
# TEMPO
# ==========================

def agora():
    return datetime.utcnow() - timedelta(hours=3)

# ==========================
# PREÇO (CORRIGIDO)
# ==========================

def get_price(symbol):

    try:

        url = (
            "https://api.binance.com/api/v3/ticker/price"
            f"?symbol={symbol}"
        )

        r = requests.get(url, timeout=5)

        data = r.json()

        return float(data["price"])

    except Exception as e:

        print(f"Erro preço {symbol}: {e}")

        return None

# ==========================
# CANDLES
# ==========================

def get_candles(symbol):

    try:

        url = (
            "https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}"
            f"&interval={INTERVAL}"
            "&limit=50"
        )

        r = requests.get(url, timeout=5)

        data = r.json()

        df = pd.DataFrame(data)

        df = df.iloc[:, 0:6]

        df.columns = [
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]

        df["close"] = df["close"].astype(float)

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

# ==========================
# GERAR SINAL
# ==========================

def gerar_sinal(symbol):

    df = get_candles(symbol)

    if df is None:
        return

    df = calcular_indicadores(df)

    ultima = df.iloc[-1]
    anterior = df.iloc[-2]

    ema9 = ultima["EMA9"]
    ema21 = ultima["EMA21"]

    ema9_ant = anterior["EMA9"]
    ema21_ant = anterior["EMA21"]

    rsi = ultima["RSI"]

    direcao = None

    if ema9_ant < ema21_ant and ema9 > ema21 and rsi > 50:
        direcao = "BUY"

    elif ema9_ant > ema21_ant and ema9 < ema21 and rsi < 50:
        direcao = "SELL"

    if direcao is None:
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
        preco_entrada = op["preco"]

        # ==================
        # ENTRADA
        # ==================

        if op["etapa"] == 0:

            if agora_time >= op["tempo_entrada"]:

                preco = get_price(symbol)

                if preco is None:
                    novas_operacoes.append(op)
                    continue

                win = (
                    preco > preco_entrada
                    if direcao == "BUY"
                    else preco < preco_entrada
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

        # ==================
        # PROTEÇÃO 1
        # ==================

        elif op["etapa"] == 1:

            if agora_time >= op["tempo_protecao1"]:

                preco = get_price(symbol)

                if preco is None:
                    novas_operacoes.append(op)
                    continue

                win = (
                    preco > preco_entrada
                    if direcao == "BUY"
                    else preco < preco_entrada
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

        # ==================
        # PROTEÇÃO 2
        # ==================

        elif op["etapa"] == 2:

            if agora_time >= op["tempo_protecao2"]:

                preco = get_price(symbol)

                if preco is None:
                    novas_operacoes.append(op)
                    continue

                win = (
                    preco > preco_entrada
                    if direcao == "BUY"
                    else preco < preco_entrada
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

    enviar("🤖 BOT INICIADO")

    while True:

        try:

            for symbol in SYMBOLS:

                gerar_sinal(symbol)

            verificar_resultados()

            time.sleep(30)

        except Exception as e:

            print("Erro geral:", e)

            time.sleep(10)

# ==========================

main()
