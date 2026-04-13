import requests
import time
from datetime import datetime, timedelta, timezone

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

wins = 0
losses = 0

operacoes_ativas = []
setup_pendente = None

last_signal_time = None
SIGNAL_INTERVAL = 300  # 5 minutos

BR_TZ = timezone(timedelta(hours=-3))

# ==========================
# TEMPO
# ==========================

def utc_now():
    return datetime.now(timezone.utc)

def br_now():
    return utc_now().astimezone(BR_TZ)

def floor_minute(dt):
    return dt.replace(second=0, microsecond=0)

def next_minute(dt):
    return floor_minute(dt) + timedelta(minutes=1)

def fmt_br(dt):
    return dt.astimezone(BR_TZ).strftime("%H:%M")

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

    except Exception as e:

        print("Erro Telegram:", e)

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

        r = requests.get(url, params=params, timeout=10)

        data = r.json()

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
# KUCOIN
# ==========================

def to_kucoin_symbol(symbol):

    return symbol.replace("USDT", "-USDT")

def get_price(symbol):

    try:

        url = "https://api.kucoin.com/api/v1/market/orderbook/level1"

        params = {
            "symbol": to_kucoin_symbol(symbol)
        }

        r = requests.get(url, params=params, timeout=10)

        data = r.json()

        price = data.get("data", {}).get("price")

        if price is None:
            return None

        return float(price)

    except:

        return None

def get_candles(symbol, timeframe="1min"):

    try:

        url = "https://api.kucoin.com/api/v1/market/candles"

        params = {
            "type": timeframe,
            "symbol": to_kucoin_symbol(symbol)
        }

        r = requests.get(url, params=params, timeout=10)

        data = r.json()

        if "data" not in data:
            return None

        rows = data["data"]

        candles = []

        for row in reversed(rows):

            ts = int(float(row[0]))

            candle = {
                "time": datetime.fromtimestamp(ts, tz=timezone.utc),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4])
            }

            candles.append(candle)

        return candles

    except:

        return None

# ==========================
# INDICADORES
# ==========================

def ema_last(prices, period):

    if len(prices) < period:
        return None

    k = 2 / (period + 1)

    ema = sum(prices[:period]) / period

    for p in prices[period:]:

        ema = (p - ema) * k + ema

    return ema

def rsi_last(prices, period=14):

    if len(prices) < period + 1:
        return None

    gains = 0
    losses_ = 0

    for i in range(1, period + 1):

        diff = prices[i] - prices[i-1]

        if diff >= 0:
            gains += diff
        else:
            losses_ += abs(diff)

    avg_gain = gains / period
    avg_loss = losses_ / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100/(1+rs))

# ==========================
# ESCOLHER MELHOR ATIVO
# ==========================

def escolher_melhor_ativo():

    melhor_symbol = None
    melhor_score = -1
    melhor_direcao = None

    for symbol in SYMBOLS:

        candles_m5 = get_candles(symbol,"5min")
        candles_m1 = get_candles(symbol,"1min")

        if not candles_m5 or not candles_m1:
            continue

        closes5 = [c["close"] for c in candles_m5]
        closes1 = [c["close"] for c in candles_m1]

        ema9_5 = ema_last(closes5,9)
        ema21_5 = ema_last(closes5,21)

        ema9_1 = ema_last(closes1,9)
        ema21_1 = ema_last(closes1,21)

        rsi1 = rsi_last(closes1)

        if None in [ema9_5,ema21_5,ema9_1,ema21_1,rsi1]:
            continue

        last = candles_m1[-1]

        corpo = abs(last["close"] - last["open"])
        range_ = last["high"] - last["low"]

        if range_ == 0:
            continue

        body_ratio = corpo / range_

        if body_ratio < 0.45:
            continue

        direcao = None

        if ema9_5 > ema21_5 and ema9_1 > ema21_1 and rsi1 > 50:
            direcao = "BUY"

        elif ema9_5 < ema21_5 and ema9_1 < ema21_1 and rsi1 < 50:
            direcao = "SELL"

        if direcao is None:
            continue

        score = abs(ema9_1 - ema21_1)

        if score > melhor_score:

            melhor_score = score
            melhor_symbol = symbol
            melhor_direcao = direcao

    return melhor_symbol, melhor_direcao, melhor_score

# ==========================
# CRIAR SINAL
# ==========================

def criar_sinal(symbol,direcao,score):

    global setup_pendente
    global last_signal_time

    agora = utc_now()

    entrada_time = next_minute(agora) + timedelta(minutes=2)

    setup_pendente = {
        "symbol":symbol,
        "direcao":direcao,
        "entrada_time":entrada_time
    }

    last_signal_time = agora

    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 {symbol}\n"
        f"📊 {'🟢 COMPRA' if direcao=='BUY' else '🔴 VENDA'}\n"
        f"⏰ Entrada: {fmt_br(entrada_time)}"
    )

def processar_setup_pendente():

    global setup_pendente

    if setup_pendente is None:
        return

    agora = utc_now()

    if agora >= setup_pendente["entrada_time"]:

        symbol = setup_pendente["symbol"]
        direcao = setup_pendente["direcao"]

        entrada = setup_pendente["entrada_time"]

        p1 = entrada + timedelta(minutes=1)
        p2 = entrada + timedelta(minutes=2)

        operacoes_ativas.append({
            "symbol":symbol,
            "direcao":direcao,
            "etapa":0,
            "tempo_entrada":entrada,
            "tempo_protecao1":p1,
            "tempo_protecao2":p2
        })

        enviar(
            "✅ ENTRADA CONFIRMADA ✅\n\n"
            f"🌎 {symbol}\n"
            f"📊 {'🟢 COMPRA' if direcao=='BUY' else '🔴 VENDA'}\n"
            f"⏰ {fmt_br(entrada)}\n\n"
            f"⚠️ P1 {fmt_br(p1)}\n"
            f"⚠️ P2 {fmt_br(p2)}"
        )

        setup_pendente = None

# ==========================
# RESULTADOS
# ==========================

def enviar_resultado(symbol,resultado):

    total = wins + losses

    taxa = (wins/total)*100 if total>0 else 0

    enviar(
        "🏆 RESULTADO\n\n"
        f"{symbol}\n"
        f"{resultado}\n\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Precisão: {round(taxa,1)}%"
    )

#=================
#VERIFICAR RESULTADO 
#==================

def verificar_resultados():
    global wins
    global losses
    agora_utc = utc_now()
    novas_operacoes = []
    for op in operacoes_ativas:
        symbol = op["symbol"]
        direcao = op["direcao"]
        candles = get_candles(symbol)
        if candles is None or len(candles) < 5:
            novas_operacoes.append(op)
            continue
        # ETAPA 0 — ENTRADA
        if op["etapa"] == 0:
            if agora_utc < op["tempo_entrada"] + timedelta(minutes=1):
                novas_operacoes.append(op)
                continue
            vela_atual = candle_por_abertura(candles, op["tempo_entrada"])
            vela_anterior = candle_por_abertura(candles, op["tempo_entrada"] - timedelta(minutes=1))
            if vela_atual is None or vela_anterior is None:
                novas_operacoes.append(op)
                continue
            win = (
                float(vela_atual["close"]) > float(vela_anterior["close"])
                if direcao == "BUY"
                else float(vela_atual["close"]) < float(vela_anterior["close"])
            )
            if win:
                wins += 1
                enviar_resultado(symbol, "WIN na Entrada")
                continue
            op["etapa"] = 1
            novas_operacoes.append(op)
            continue
        # ETAPA 1 — PROTEÇÃO 1
        if op["etapa"] == 1:
            if agora_utc < op["tempo_protecao1"] + timedelta(minutes=1):
                novas_operacoes.append(op)
                continue
            vela_atual = candle_por_abertura(candles, op["tempo_protecao1"])
            vela_anterior = candle_por_abertura(candles, op["tempo_protecao1"] - timedelta(minutes=1))
            if vela_atual is None or vela_anterior is None:
                novas_operacoes.append(op)
                continue
            win = (
                float(vela_atual["close"]) > float(vela_anterior["close"])
                if direcao == "BUY"
                else float(vela_atual["close"]) < float(vela_anterior["close"])
            )
            if win:
                wins += 1
                enviar_resultado(symbol, "WIN na Proteção 1")
                continue
            op["etapa"] = 2
            novas_operacoes.append(op)
            continue
        # ETAPA 2 — PROTEÇÃO 2
        if op["etapa"] == 2:
            if agora_utc < op["tempo_protecao2"] + timedelta(minutes=1):
                novas_operacoes.append(op)
                continue
            vela_atual = candle_por_abertura(candles, op["tempo_protecao2"])
            vela_anterior = candle_por_abertura(candles, op["tempo_protecao2"] - timedelta(minutes=1))
            if vela_atual is None or vela_anterior is None:
                novas_operacoes.append(op)
                continue
            win = (
                float(vela_atual["close"]) > float(vela_anterior["close"])
                if direcao == "BUY"
                else float(vela_atual["close"]) < float(vela_anterior["close"])
            )
            if win:
                wins += 1
                enviar_resultado(symbol, "WIN na Proteção 2")
            else:
                losses += 1
                enviar_resultado(symbol, "LOSS após Proteção 2")
            continue
    operacoes_ativas.clear()
    operacoes_ativas.extend(novas_operacoes)

# ==========================
# LOOP
# ==========================

def main():

    global last_signal_time

    enviar("🤖 BOT INICIADO")

    while True:

        try:

            verificar_comandos()

            if BOT_ATIVO:

                processar_setup_pendente()

                agora = utc_now()

                if setup_pendente is None:

                    if last_signal_time is None or (
                        agora - last_signal_time
                    ).seconds >= SIGNAL_INTERVAL:

                        symbol,direcao,score = escolher_melhor_ativo()

                        if symbol:

                            criar_sinal(symbol,direcao,score)

            time.sleep(15)

        except Exception as e:

            print("Erro geral:",e)

            time.sleep(10)

main()
