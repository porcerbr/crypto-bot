import os
import time
import requests
import json

from datetime import datetime, timedelta, timezone

# ==========================
# CONFIGURAÇÕES
# ==========================
TOKEN = os.getenv("BOT_TOKEN", "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ")
CHAT_ID = os.getenv("CHAT_ID", "1056795017")

INTERVAL = "1m"
SIGNAL_INTERVAL = 300
BR_TZ = timezone(timedelta(hours=-3))

wins = 0
losses = 0

operacoes_ativas = []
setup_pendente = None
last_signal_time = None

LAST_UPDATE_ID = None
BOT_ATIVO = False

# ==========================
# UNIVERSO DINÂMICO
# ==========================
ACTIVE_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
]

last_universe_update = None
UNIVERSE_REFRESH = 900

performance = {
    "BTCUSDT": {"win": 0, "loss": 0},
    "ETHUSDT": {"win": 0, "loss": 0},
    "XRPUSDT": {"win": 0, "loss": 0},
    "SOLUSDT": {"win": 0, "loss": 0},
    "ADAUSDT": {"win": 0, "loss": 0},
    "BNBUSDT": {"win": 0, "loss": 0},
    "DOGEUSDT": {"win": 0, "loss": 0},
    "TRXUSDT": {"win": 0, "loss": 0},
    "TONUSDT": {"win": 0, "loss": 0},
    "AVAXUSDT": {"win": 0, "loss": 0},
    "LINKUSDT": {"win": 0, "loss": 0},
}

# ==========================
# APRENDIZADO AUTOMÁTICO
# ==========================
learning_data = {
    "asset_stats": {},
    "hour_stats": {}
}

LEARNING_FILE = "learning.json"

def carregar_aprendizado():
    global learning_data

    if os.path.exists(LEARNING_FILE):
        try:
            with open(LEARNING_FILE, "r") as f:
                learning_data = json.load(f)
            log("Aprendizado carregado.")
        except:
            log("Erro ao carregar aprendizado.")

def salvar_aprendizado():
    try:
        with open(LEARNING_FILE, "w") as f:
            json.dump(learning_data, f)
    except:
        log("Erro ao salvar aprendizado.")

def registrar_resultado_aprendizado(symbol, win):

    hour = str(br_now().hour)

    if symbol not in learning_data["asset_stats"]:
        learning_data["asset_stats"][symbol] = {
            "win": 0,
            "loss": 0
        }

    if win:
        learning_data["asset_stats"][symbol]["win"] += 1
    else:
        learning_data["asset_stats"][symbol]["loss"] += 1

    if hour not in learning_data["hour_stats"]:
        learning_data["hour_stats"][hour] = {
            "win": 0,
            "loss": 0
        }

    if win:
        learning_data["hour_stats"][hour]["win"] += 1
    else:
        learning_data["hour_stats"][hour]["loss"] += 1

    salvar_aprendizado()

def learning_multiplier(symbol):

    data = learning_data["asset_stats"].get(symbol)

    if not data:
        return 1.0

    total = data["win"] + data["loss"]

    if total < 5:
        return 1.0

    winrate = data["win"] / total

    if winrate > 0.65:
        return 1.2

    if winrate < 0.40:
        return 0.8

    return 1.0

def hour_multiplier():

    hour = str(br_now().hour)

    data = learning_data["hour_stats"].get(hour)

    if not data:
        return 1.0

    total = data["win"] + data["loss"]

    if total < 5:
        return 1.0

    winrate = data["win"] / total

    if winrate > 0.65:
        return 1.15

    if winrate < 0.40:
        return 0.85

    return 1.0

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
# LOG
# ==========================
def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

# ==========================
# TELEGRAM
# ==========================
def enviar(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        log(f"Erro envio Telegram: {e}")

def remover_webhook():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        requests.get(url, timeout=10)
    except:
        pass

# ==========================
# TELEGRAM COMMANDS
# ==========================

def verificar_comandos():

    global LAST_UPDATE_ID
    global BOT_ATIVO

    try:

        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

        params = {}

        if LAST_UPDATE_ID is not None:
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

            texto = update["message"].get(
                "text",
                ""
            ).strip()

            if texto == "/start":

                BOT_ATIVO = True

                enviar("🟢 BOT ATIVADO")

                log("BOT ATIVADO")

            elif texto == "/stop":

                BOT_ATIVO = False

                enviar("🔴 BOT PARADO")

                log("BOT PARADO")

    except Exception as e:

        log(f"Erro comandos: {e}")

# ==========================
# MULTIPLICADOR POR ATIVO
# ==========================
def asset_multiplier(symbol):

    data = performance.get(symbol, {"win": 1, "loss": 1})
    total = data["win"] + data["loss"]

    if total < 10:
        return 1.0

    winrate = data["win"] / total

    if winrate > 0.65:
        return 1.15

    if winrate < 0.40:
        return 0.85

    return 1.0

# ==========================
# ESCOLHER MELHOR ATIVO
# ==========================
def escolher_melhor_ativo():

    melhor_symbol = None
    melhor_score = -1
    melhor_direcao = None

    for symbol in ACTIVE_SYMBOLS:

        candles = get_candles(symbol)

        if not candles or len(candles) < 60:
            continue

        closes = [c["close"] for c in candles]

        e9 = ema_last(closes, 9)
        e21 = ema_last(closes, 21)
        rsi = rsi_last(closes, 14)

        if e9 is None or e21 is None or rsi is None:
            continue

        trend_pct = abs(e9 - e21) / closes[-1]

        score = trend_pct + abs(rsi - 50) * 0.05

        score *= asset_multiplier(symbol)
        score *= learning_multiplier(symbol)
        score *= hour_multiplier()

        if e9 > e21 and rsi >= 50:
            direcao = "BUY"

        elif e9 < e21 and rsi <= 50:
            direcao = "SELL"

        else:
            continue

        if score > melhor_score:
            melhor_score = score
            melhor_symbol = symbol
            melhor_direcao = direcao

    return melhor_symbol, melhor_direcao, melhor_score

# ==========================
# KUCOIN HELPERS
# ==========================

def to_kucoin_symbol(symbol):
    return symbol.replace("USDT", "-USDT")

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

        if "data" not in data:
            log(f"Resposta inválida candles {symbol}")
            return None

        rows = data["data"][:limit]

        candles = []

        for row in reversed(rows):

            try:

                open_ts = int(float(row[0]))

                open_dt = datetime.fromtimestamp(
                    open_ts,
                    tz=timezone.utc
                )

                candles.append({
                    "time": open_dt,
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                })

            except:
                continue

        return candles

    except Exception as e:

        log(f"Erro candles {symbol}: {e}")

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

        ema_val = (
            (price - ema_val) * k
            + ema_val
        )

    return ema_val


def rsi_last(prices, period=14):

    if len(prices) < period + 1:
        return None

    gains = 0
    losses = 0

    for i in range(1, period + 1):

        diff = prices[i] - prices[i - 1]

        if diff >= 0:
            gains += diff
        else:
            losses += abs(diff)

    avg_gain = gains / period
    avg_loss = losses / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


# ==========================
# AUTO SELEÇÃO DE UNIVERSO
# ==========================

 def get_market_symbols():

    try:

        url = "https://api.binance.com/api/v3/ticker/24hr"

        r = requests.get(url, timeout=10)

        if r.status_code != 200:

            log(f"Market scan HTTP erro {r.status_code}")

            return ["BTCUSDT", "ETHUSDT"]

        try:

            data = r.json()

        except Exception:

            log("Market scan JSON inválido")

            return ["BTCUSDT", "ETHUSDT"]

        # Se não for lista → erro Binance
        if not isinstance(data, list):

            log("Market scan retornou erro da Binance")

            return ["BTCUSDT", "ETHUSDT"]

        symbols = []

        for item in data:

            try:

                if not isinstance(item, dict):
                    continue

                symbol = item.get("symbol")

                if not symbol:
                    continue

                if not symbol.endswith("USDT"):
                    continue

                if "UP" in symbol or "DOWN" in symbol:
                    continue

                volume = float(
                    item.get("quoteVolume", 0)
                )

                if volume < 50000000:
                    continue

                symbols.append(
                    (symbol, volume)
                )

            except Exception:
                continue

        if len(symbols) == 0:

            log("Market scan vazio — fallback")

            return ["BTCUSDT", "ETHUSDT"]

        symbols.sort(
            key=lambda x: x[1],
            reverse=True
        )

        top_symbols = [
            s[0] for s in symbols[:30]
        ]

        return top_symbols

    except Exception as e:

        log(f"Erro market scan geral: {e}")

        return ["BTCUSDT", "ETHUSDT"]

# ==========================
# CRIAR SINAL
# ==========================

def criar_sinal(symbol, direcao, score):

    global setup_pendente
    global last_signal_time

    agora_utc = utc_now()

    entrada_time = (
        next_minute(agora_utc)
        + timedelta(minutes=2)
    )

    setup_pendente = {

        "symbol": symbol,
        "direcao": direcao,
        "score": score,
        "entrada_time": entrada_time,
        "preparado": False,
    }

    last_signal_time = agora_utc

    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 Ativo: {symbol}\n"
        f"📊 Estratégia: {'🟢 COMPRA' if direcao == 'BUY' else '🔴 VENDA'}\n"
        f"⏰ Entrada prevista: {fmt_br(entrada_time)}\n"
        f"📈 Força: {score:.3f}"
    )

    log(
        f"SINAL | {symbol} | {direcao} | {score:.3f}"
    )


# ==========================
# PROCESSAR SETUP
# ==========================

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
            f"⚠️ Proteção 1: {fmt_br(p1)}\n"
            f"⚠️ Proteção 2: {fmt_br(p2)}"
        )

        setup_pendente = None


# ==========================
# RESULTADOS
# ==========================

def enviar_resultado(symbol, resultado):

    total = wins + losses

    taxa = (
        (wins / total) * 100
        if total > 0
        else 0
    )

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

        if candles is None:

            novas_operacoes.append(op)

            continue


        # ETAPA 0

        if op["etapa"] == 0:

            if agora_utc < op["tempo_entrada"] + timedelta(minutes=1):

                novas_operacoes.append(op)

                continue

            vela_atual = candle_por_abertura(
                candles,
                op["tempo_entrada"]
            )

            vela_anterior = candle_por_abertura(
                candles,
                op["tempo_entrada"]
                - timedelta(minutes=1)
            )

            if vela_atual is None:

                novas_operacoes.append(op)

                continue

            win = (

                vela_atual["close"]
                > vela_anterior["close"]

                if direcao == "BUY"

                else

                vela_atual["close"]
                < vela_anterior["close"]

            )

            if win:

                wins += 1

                performance[symbol]["win"] += 1

                registrar_resultado_aprendizado(
                    symbol,
                    True
                )

                enviar_resultado(
                    symbol,
                    "WIN na Entrada"
                )

                continue

            op["etapa"] = 1

            novas_operacoes.append(op)

            continue


        # ETAPA 1

        if op["etapa"] == 1:

            if agora_utc < op["tempo_protecao1"] + timedelta(minutes=1):

                novas_operacoes.append(op)

                continue

            vela_atual = candle_por_abertura(
                candles,
                op["tempo_protecao1"]
            )

            vela_anterior = candle_por_abertura(
                candles,
                op["tempo_protecao1"]
                - timedelta(minutes=1)
            )

            if vela_atual is None:

                novas_operacoes.append(op)

                continue

            win = (

                vela_atual["close"]
                > vela_anterior["close"]

                if direcao == "BUY"

                else

                vela_atual["close"]
                < vela_anterior["close"]

            )

            if win:

                wins += 1

                performance[symbol]["win"] += 1

                registrar_resultado_aprendizado(
                    symbol,
                    True
                )

                enviar_resultado(
                    symbol,
                    "WIN na Proteção 1"
                )

                continue

            op["etapa"] = 2

            novas_operacoes.append(op)

            continue


        # ETAPA 2

        if op["etapa"] == 2:

            if agora_utc < op["tempo_protecao2"] + timedelta(minutes=1):

                novas_operacoes.append(op)

                continue

            vela_atual = candle_por_abertura(
                candles,
                op["tempo_protecao2"]
            )

            vela_anterior = candle_por_abertura(
                candles,
                op["tempo_protecao2"]
                - timedelta(minutes=1)
            )

            if vela_atual is None:

                novas_operacoes.append(op)

                continue

            win = (

                vela_atual["close"]
                > vela_anterior["close"]

                if direcao == "BUY"

                else

                vela_atual["close"]
                < vela_anterior["close"]

            )

            if win:

                wins += 1

                performance[symbol]["win"] += 1

                registrar_resultado_aprendizado(
                    symbol,
                    True
                )

                enviar_resultado(
                    symbol,
                    "WIN na Proteção 2"
                )

            else:

                losses += 1

                performance[symbol]["loss"] += 1

                registrar_resultado_aprendizado(
                    symbol,
                    False
                )

                enviar_resultado(
                    symbol,
                    "LOSS após Proteção 2"
                )

            continue

    operacoes_ativas.clear()

    operacoes_ativas.extend(
        novas_operacoes
    )


# ==========================
# LOOP PRINCIPAL
# ==========================

def main():

    global last_signal_time
    global last_universe_update

    remover_webhook()

    carregar_aprendizado()

    log("BOT INICIANDO...")

    enviar("🤖 BOT INICIADO COM SUCESSO")

    while True:

        try:

            verificar_comandos()

            if BOT_ATIVO:

                if (
                    last_universe_update is None
                    or
                    (
                        utc_now()
                        - last_universe_update
                    ).total_seconds()
                    > UNIVERSE_REFRESH
                ):

                    update_active_symbols()

                processar_setup_pendente()

                verificar_resultados()

                agora_utc = utc_now()

                if (
                    setup_pendente is None
                    and
                    not operacoes_ativas
                ):

                    if (

                        last_signal_time is None
                        or

                        (
                            agora_utc
                            - last_signal_time
                        ).total_seconds()
                        >= SIGNAL_INTERVAL

                    ):

                        symbol, direcao, score = escolher_melhor_ativo()

                        if symbol:

                            criar_sinal(
                                symbol,
                                direcao,
                                score
                            )

            time.sleep(15)

        except Exception as e:

            log(f"Erro geral: {e}")

            time.sleep(10)


if __name__ == "__main__":

    main()
