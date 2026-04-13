import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIGURAÇÕES
# ==========================

TOKEN = os.getenv("7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ", "")
CHAT_ID = os.getenv("1056795017", "")

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "ADAUSDT",
]

INTERVAL = "1m"

wins = 0
losses = 0

# Operações já confirmadas e aguardando resultado
operacoes_ativas = []

# Setup encontrado, mas ainda aguardando a hora da entrada
setup_pendente = None

# Controle global para evitar spam
last_signal_time = None
SIGNAL_INTERVAL = 300  # 5 minutos

# Timezone do Brasil para exibição
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

        if LAST_UPDATE_ID is not None:
            params["offset"] = LAST_UPDATE_ID + 1

        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        if "result" not in data:
            return

        for update in data["result"]:
            LAST_UPDATE_ID = update["update_id"]

            if "message" not in update:
                continue

            texto = update["message"].get("text", "").strip()

            if texto == "/start":
                BOT_ATIVO = True
                enviar("🟢 BOT ATIVADO")

            elif texto == "/stop":
                BOT_ATIVO = False
                enviar("🔴 BOT PARADO")

    except Exception as e:
        print("Erro comandos:", e)


# ==========================
# KUCOIN HELPERS
# ==========================

def to_kucoin_symbol(symbol):
    return symbol.replace("USDT", "-USDT")

def get_price(symbol):
    try:
        kucoin_symbol = to_kucoin_symbol(symbol)
        url = "https://api.kucoin.com/api/v1/market/orderbook/level1"
        params = {"symbol": kucoin_symbol}

        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        price = data.get("data", {}).get("price")
        if price is None:
            print(f"Resposta inválida preço {symbol}: {data}")
            return None

        return float(price)

    except Exception as e:
        print(f"Erro preço {symbol}: {e}")
        return None

def get_candles(symbol, limit=120):
    try:
        kucoin_symbol = to_kucoin_symbol(symbol)
        url = "https://api.kucoin.com/api/v1/market/candles"
        params = {
            "type": "1min",
            "symbol": kucoin_symbol
        }

        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        if "data" not in data or not isinstance(data["data"], list):
            print(f"Resposta inválida {symbol}: {data}")
            return None

        rows = data["data"]

        candles = []
        for row in reversed(rows[-limit:]):  # ordem crescente
            try:
                open_ts = int(float(row[0]))
                open_dt = datetime.fromtimestamp(open_ts, tz=timezone.utc)

                candle = {
                    "time": open_dt,
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                }
                candles.append(candle)
            except Exception:
                continue

        return candles

    except Exception as e:
        print(f"Erro candles {symbol}: {e}")
        return None

def candle_por_abertura(candles, abertura_utc):
    alvo = floor_minute(abertura_utc)
    for candle in candles:
        if floor_minute(candle["time"]) == alvo:
            return candle
    return None


# ==========================
# INDICADORES
# ==========================

def ema_last(prices, period):
    if len(prices) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period

    for price in prices[period:]:
        ema_val = (price - ema_val) * k + ema_val

    return ema_val

def rsi_last(prices, period=14):
    if len(prices) < period + 1:
        return None

    gains = 0.0
    losses = 0.0

    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses += abs(diff)

    avg_gain = gains / period
    avg_loss = losses / period

    if len(prices) > period + 1:
        for i in range(period + 1, len(prices)):
            diff = prices[i] - prices[i - 1]
            gain = max(diff, 0)
            loss = abs(min(diff, 0))
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ==========================
# BLOQUEIO DE DUPLICADO
# ==========================

def ja_tem_operacao(symbol):
    for op in operacoes_ativas:
        if op["symbol"] == symbol:
            return True
    return False


# ==========================
# ESCOLHER MELHOR ATIVO
# ==========================

def escolher_melhor_ativo():
    melhor_symbol = None
    melhor_score = -1
    melhor_direcao = None

    for symbol in SYMBOLS:
        if ja_tem_operacao(symbol):
            continue

        candles = get_candles(symbol)
        if not candles or len(candles) < 30:
            continue

        closes = [c["close"] for c in candles]

        e9 = ema_last(closes, 9)
        e21 = ema_last(closes, 21)
        rsi = rsi_last(closes, 14)

        if e9 is None or e21 is None or rsi is None:
            continue

        trend_pct = abs(e9 - e21) / closes[-1] * 100

        # filtro leve para evitar lateralização
        if trend_pct < 0.01:
            continue

        if e9 > e21 and rsi >= 48:
            direcao = "BUY"
        elif e9 < e21 and rsi <= 52:
            direcao = "SELL"
        else:
            continue

        score = trend_pct + abs(rsi - 50) * 0.05

        if score > melhor_score:
            melhor_score = score
            melhor_symbol = symbol
            melhor_direcao = direcao

    return melhor_symbol, melhor_direcao, melhor_score


# ==========================
# CRIAR SINAL
# ==========================

def criar_sinal(symbol, direcao, score):
    global setup_pendente
    global last_signal_time

    agora_utc = utc_now()

    # entrada no começo da próxima vela + 2 minutos
    entrada_time = next_minute(agora_utc) + timedelta(minutes=2)

    setup_pendente = {
        "symbol": symbol,
        "direcao": direcao,
        "score": score,
        "entrada_time": entrada_time,
        "preparado": False,
    }

    last_signal_time = agora_utc

    # aviso antecipado
    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 Ativo: {symbol}\n"
        f"📊 Estratégia: {'🟢 COMPRA' if direcao == 'BUY' else '🔴 VENDA'}\n"
        f"⏰ Entrada prevista: {fmt_br(entrada_time)}\n"
        f"📈 Força: {score:.3f}"
    )


def processar_setup_pendente():
    global setup_pendente

    if setup_pendente is None:
        return

    agora_utc = utc_now()

    if agora_utc >= setup_pendente["entrada_time"]:
        symbol = setup_pendente["symbol"]
        direcao = setup_pendente["direcao"]
        entrada_time = setup_pendente["entrada_time"]

        p1 = entrada_time + timedelta(minutes=1)
        p2 = entrada_time + timedelta(minutes=2)

        operacoes_ativas.append({
            "symbol": symbol,
            "direcao": direcao,
            "etapa": 0,
            "tempo_entrada": entrada_time,
            "tempo_protecao1": p1,
            "tempo_protecao2": p2,
        })

        enviar(
            "✅ ENTRADA CONFIRMADA ✅\n\n"
            f"🌎 Ativo: {symbol}\n"
            f"📊 Estratégia: {'🟢 COMPRA' if direcao == 'BUY' else '🔴 VENDA'}\n"
            f"⏰ Entrada: {fmt_br(entrada_time)}\n\n"
            f"⚠️ Proteção 1 {fmt_br(p1)}\n"
            f"⚠️ Proteção 2 {fmt_br(p2)}"
        )

        setup_pendente = None


# ==========================
# RESULTADO
# ==========================

def enviar_resultado(symbol, resultado):
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
                processar_setup_pendente()
                verificar_resultados()

                agora_utc = utc_now()

                # só procurar novo sinal se não houver setup pendente nem operação ativa
                if setup_pendente is None and not operacoes_ativas:
                    if last_signal_time is None or (agora_utc - last_signal_time).seconds >= SIGNAL_INTERVAL:
                        symbol, direcao, score = escolher_melhor_ativo()

                        if symbol:
                            criar_sinal(symbol, direcao, score)

            time.sleep(15)

        except Exception as e:
            print("Erro geral:", e)
            time.sleep(10)


if __name__ == "__main__":
    main()
