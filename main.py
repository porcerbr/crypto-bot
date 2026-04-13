# bot.py
import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIGURAÇÃO
# ==========================
TOKEN = os.getenv("BOT_TOKEN", "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ")
CHAT_ID = os.getenv("CHAT_ID", "1056795017")

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "ADAUSDT",
]

INTERVAL = "1m"
SIGNAL_INTERVAL = 300  # 5 minutos
BR_TZ = timezone(timedelta(hours=-3))

wins = 0
losses = 0
operacoes_ativas = []
setup_pendente = None
last_signal_time = None
LAST_UPDATE_ID = None
BOT_ATIVO = False

performance = {
    "BTCUSDT": {"win": 0, "loss": 0},
    "ETHUSDT": {"win": 0, "loss": 0},
    "XRPUSDT": {"win": 0, "loss": 0},
    "SOLUSDT": {"win": 0, "loss": 0},
    "ADAUSDT": {"win": 0, "loss": 0},
}

# ==========================
# LOG
# ==========================
def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

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
        if r.status_code != 200:
            log(f"Erro Telegram: {r.status_code} | {r.text}")
    except Exception as e:
        log(f"Erro envio Telegram: {e}")

def remover_webhook():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        requests.get(url, timeout=10)
    except Exception as e:
        log(f"Erro ao remover webhook: {e}")

def verificar_comandos():
    global LAST_UPDATE_ID, BOT_ATIVO
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
                log("BOT ATIVADO")

            elif texto == "/stop":
                BOT_ATIVO = False
                enviar("🔴 BOT PARADO")
                log("BOT PARADO")

    except Exception as e:
        log(f"Erro comandos: {e}")

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

        if "data" not in data or not isinstance(data["data"], list):
            log(f"Resposta inválida candles {symbol}: {data}")
            return None

        rows = data["data"]
        candles = []

        for row in reversed(rows[-limit:]):
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

def atr_like(closes, period=14):
    if len(closes) < period + 1:
        return None
    vals = []
    start = max(1, len(closes) - period)
    for i in range(start, len(closes)):
        vals.append(abs(closes[i] - closes[i - 1]))
    if not vals:
        return None
    return sum(vals) / len(vals)

def adx_like(closes, period=14):
    if len(closes) < period + 2:
        return None

    tr = []
    dm_plus = []
    dm_minus = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        tr.append(abs(diff))
        dm_plus.append(max(diff, 0))
        dm_minus.append(max(-diff, 0))

    tr_v = sum(tr[-period:]) / period
    plus_v = sum(dm_plus[-period:]) / period
    minus_v = sum(dm_minus[-period:]) / period

    denom = plus_v + minus_v
    if tr_v == 0 or denom == 0:
        return 0.0

    dx = abs(plus_v - minus_v) / denom
    return dx * 100

# ==========================
# FILTROS
# ==========================
def market_regime(closes):
    if len(closes) < 60:
        return "UNKNOWN"

    ema9 = ema_last(closes, 9)
    ema21 = ema_last(closes, 21)
    ema50 = ema_last(closes, 50)

    if ema9 is None or ema21 is None or ema50 is None:
        return "UNKNOWN"

    slope = abs(ema9 - ema_last(closes[:-10], 9)) if len(closes) > 20 else 0
    trend_strength = abs(ema21 - ema50) / closes[-1]

    if trend_strength < 0.0015:
        return "RANGE"

    if slope < closes[-1] * 0.0003:
        return "CHOP"

    return "TREND"

def liquidity_sweep(candles):
    if len(candles) < 6:
        return False

    prev_high = max(c["high"] for c in candles[-6:-1])
    prev_low = min(c["low"] for c in candles[-6:-1])
    last = candles[-1]

    if last["high"] > prev_high and last["close"] < prev_high:
        return True

    if last["low"] < prev_low and last["close"] > prev_low:
        return True

    return False

def session_filter():
    hour = br_now().hour
    if 1 <= hour <= 6:
        return False
    return True

def asset_multiplier(symbol):
    data = performance.get(symbol, {"win": 1, "loss": 1})
    total = data["win"] + data["loss"]

    if total < 10:
        return 1.0

    winrate = data["win"] / total

    if winrate > 0.65:
        return 1.2
    if winrate < 0.4:
        return 0.7

    return 1.0

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
    melhor_score = -999
    melhor_direcao = None

    for symbol in SYMBOLS:
        if ja_tem_operacao(symbol):
            continue

        candles = get_candles(symbol)
        if not candles or len(candles) < 60:
            continue

        closes = [c["close"] for c in candles]

        e9 = ema_last(closes, 9)
        e21 = ema_last(closes, 21)
        rsi = rsi_last(closes, 14)
        adx_val = adx_like(closes, 14)
        atr_val = atr_like(closes, 14)

        if e9 is None or e21 is None or rsi is None or adx_val is None or atr_val is None:
            continue

        if not session_filter():
            continue

        if liquidity_sweep(candles):
            continue

        regime = market_regime(closes)
        if regime != "TREND":
            continue

        if adx_val < 18:
            continue

        if atr_val < closes[-1] * 0.0009:
            continue

        if 48 < rsi < 52:
            continue

        if abs(closes[-1] - closes[-2]) / closes[-2] > 0.0025:
            continue

        ema_slope = abs(e9 - ema_last(closes[:-5], 9)) if len(closes) > 15 else 0
        if ema_slope < closes[-1] * 0.0004:
            continue

        trend_pct = abs(e9 - e21) / closes[-1] * 100

        if e9 > e21 and rsi >= 55:
            direcao = "BUY"
        elif e9 < e21 and rsi <= 45:
            direcao = "SELL"
        else:
            continue

        score = (
            trend_pct * 2.5 +
            abs(rsi - 50) * 0.2 +
            adx_val * 0.3 +
            (atr_val / closes[-1]) * 100
        )

        score *= asset_multiplier(symbol)

        if score > melhor_score:
            melhor_score = score
            melhor_symbol = symbol
            melhor_direcao = direcao

    return melhor_symbol, melhor_direcao, melhor_score

# ==========================
# SINAL
# ==========================
def criar_sinal(symbol, direcao, score):
    global setup_pendente, last_signal_time

    agora_utc = utc_now()
    entrada_time = next_minute(agora_utc) + timedelta(minutes=2)

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
    log(f"SINAL CRIADO | {symbol} | {direcao} | {score:.3f}")

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
        log(f"ENTRADA CONFIRMADA | {symbol} | {direcao}")

        setup_pendente = None

# ==========================
# RESULTADOS
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
        f"Precisão: {round(taxa, 1)}%"
    )
    log(f"RESULTADO | {symbol} | {resultado} | W={wins} L={losses}")

def verificar_resultados():
    global wins, losses

    agora_utc = utc_now()
    novas_operacoes = []

    for op in operacoes_ativas:
        symbol = op["symbol"]
        direcao = op["direcao"]
        candles = get_candles(symbol)

        if candles is None or len(candles) < 5:
            novas_operacoes.append(op)
            continue

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
                performance[symbol]["win"] += 1
                enviar_resultado(symbol, "WIN na Entrada")
                continue

            op["etapa"] = 1
            novas_operacoes.append(op)
            continue

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
                performance[symbol]["win"] += 1
                enviar_resultado(symbol, "WIN na Proteção 1")
                continue

            op["etapa"] = 2
            novas_operacoes.append(op)
            continue

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
                performance[symbol]["win"] += 1
                enviar_resultado(symbol, "WIN na Proteção 2")
            else:
                losses += 1
                performance[symbol]["loss"] += 1
                enviar_resultado(symbol, "LOSS após Proteção 2")

            continue

    operacoes_ativas.clear()
    operacoes_ativas.extend(novas_operacoes)

# ==========================
# MAIN
# ==========================
def main():
    global last_signal_time

    if TOKEN == "COLOQUE_SEU_TOKEN_AQUI" or CHAT_ID == "COLOQUE_SEU_CHAT_ID_AQUI":
        log("ERRO: configure BOT_TOKEN e CHAT_ID nas variáveis de ambiente do Railway.")
        return

    remover_webhook()
    log("BOT INICIANDO...")
    enviar("🤖 BOT INICIADO COM SUCESSO")

    while True:
        try:
            verificar_comandos()

            if BOT_ATIVO:
                processar_setup_pendente()
                verificar_resultados()

                agora_utc = utc_now()

                if setup_pendente is None and not operacoes_ativas:
                    if last_signal_time is None or (agora_utc - last_signal_time).seconds >= SIGNAL_INTERVAL:
                        symbol, direcao, score = escolher_melhor_ativo()
                        if symbol:
                            criar_sinal(symbol, direcao, score)

            time.sleep(15)

        except Exception as e:
            log(f"Erro geral: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
