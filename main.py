# -*- coding: utf-8 -*-
import os
import time
import json
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIGURAÇÕES
# ==========================
TOKEN = os.getenv("BOT_TOKEN", "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ")
CHAT_ID = os.getenv("CHAT_ID", "1056795017")

TIMEFRAME_MINUTES = 15
CANDLE_TYPE = "15min"

SIGNAL_INTERVAL = 900  # 15 minutos
UNIVERSE_REFRESH = 1800  # 30 minutos
COOLDOWN_MINUTES = 30
EVAL_GRACE_SECONDS = 90

BR_TZ = timezone(timedelta(hours=-3))

DEBUG_REJEICOES = True

wins = 0
losses = 0

operacoes_ativas = []
setup_pendente = None
last_signal_time = None
last_trade_time = None

LAST_UPDATE_ID = None
BOT_ATIVO = False

last_universe_update = None
adaptive_mode = "NORMAL"

ultimo_trade_por_ativo = {}

# Universo base para seleção automática
MARKET_CANDIDATES = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "ADAUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "XLMUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "TRXUSDT",
    "TONUSDT",
    "DOTUSDT",
    "ATOMUSDT",
    "NEARUSDT",
]

ACTIVE_SYMBOLS = MARKET_CANDIDATES[:8]

performance = {s: {"win": 0, "loss": 0} for s in MARKET_CANDIDATES}

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
            with open(LEARNING_FILE, "r", encoding="utf-8") as f:
                learning_data = json.load(f)
            log("Aprendizado carregado.")
        except Exception as e:
            log(f"Erro ao carregar aprendizado: {e}")


def salvar_aprendizado():
    try:
        with open(LEARNING_FILE, "w", encoding="utf-8") as f:
            json.dump(learning_data, f)
    except Exception as e:
        log(f"Erro ao salvar aprendizado: {e}")


def registrar_resultado_aprendizado(symbol, win):
    hour = str(br_now().hour)

    if symbol not in learning_data["asset_stats"]:
        learning_data["asset_stats"][symbol] = {"win": 0, "loss": 0}

    if hour not in learning_data["hour_stats"]:
        learning_data["hour_stats"][hour] = {"win": 0, "loss": 0}

    if win:
        learning_data["asset_stats"][symbol]["win"] += 1
        learning_data["hour_stats"][hour]["win"] += 1
    else:
        learning_data["asset_stats"][symbol]["loss"] += 1
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
        return 1.20
    if winrate < 0.40:
        return 0.80
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


def session_multiplier():
    hour = br_now().hour

    # evita horário muito morto no Brasil
    if 1 <= hour <= 6:
        return 0.85

    # sessão mais ativa
    if 8 <= hour <= 18:
        return 1.10

    return 1.0


# ==========================
# TEMPO
# ==========================
def utc_now():
    return datetime.now(timezone.utc)


def br_now():
    return utc_now().astimezone(BR_TZ)


def floor_timeframe(dt):
    minute = (dt.minute // TIMEFRAME_MINUTES) * TIMEFRAME_MINUTES
    return dt.replace(minute=minute, second=0, microsecond=0)


def next_timeframe(dt):
    return floor_timeframe(dt) + timedelta(minutes=TIMEFRAME_MINUTES)


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
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code != 200:
            log(f"Erro Telegram: {r.status_code} | {r.text}")
    except Exception as e:
        log(f"Erro envio Telegram: {e}")


def remover_webhook():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        requests.get(url, timeout=10)
    except Exception:
        pass


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

def ja_tem_operacao(symbol):
    for op in operacoes_ativas:
        if op["symbol"] == symbol:
            return True
    return False

def to_kucoin_symbol(symbol):
    return symbol.replace("USDT", "-USDT")


def get_candles(symbol, limit=150):
    try:
        kucoin_symbol = to_kucoin_symbol(symbol)
        url = "https://api.kucoin.com/api/v1/market/candles"
        params = {
            "type": CANDLE_TYPE,
            "symbol": kucoin_symbol
        }

        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        if "data" not in data or not isinstance(data["data"], list):
            log(f"Resposta inválida candles {symbol}: {data}")
            return None

        rows = data["data"][:limit]
        candles = []

        for row in reversed(rows):
            try:
                open_ts = int(float(row[0]))
                open_dt = datetime.fromtimestamp(open_ts, tz=timezone.utc)
                candles.append({
                    "time": open_dt,
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                })
            except Exception:
                continue

        return candles

    except Exception as e:
        log(f"Erro candles {symbol}: {e}")
        return None


def candle_por_abertura(candles, abertura_utc):
    alvo = floor_timeframe(abertura_utc)
    for candle in candles:
        if floor_timeframe(candle["time"]) == alvo:
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


# ==========================
# FILTROS / REGIME
# ==========================
def market_regime(closes):
    if len(closes) < 60:
        return "UNKNOWN"

    ema9 = ema_last(closes, 9)
    ema21 = ema_last(closes, 21)
    ema50 = ema_last(closes, 50)

    if ema9 is None or ema21 is None or ema50 is None:
        return "UNKNOWN"

    trend_strength = abs(ema21 - ema50) / closes[-1]
    slope = abs(ema9 - ema_last(closes[:-3], 9)) / closes[-1] if len(closes) > 20 else 0

    if trend_strength < 0.0010:
        return "RANGE"

    if slope < 0.00025:
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


def em_cooldown(symbol):
    if symbol not in ultimo_trade_por_ativo:
        return False

    delta = (utc_now() - ultimo_trade_por_ativo[symbol]).total_seconds()
    return delta < COOLDOWN_MINUTES * 60


def update_mode():
    global adaptive_mode, last_trade_time

    if last_trade_time is None:
        adaptive_mode = "AGRESSIVO"
        return

    idle_minutes = (utc_now() - last_trade_time).total_seconds() / 60

    if idle_minutes > 90:
        adaptive_mode = "AGRESSIVO"
    elif idle_minutes > 45:
        adaptive_mode = "NORMAL"
    else:
        adaptive_mode = "CONSERVADOR"


# ==========================
# UNIVERSO DINÂMICO
# ==========================
def get_market_symbols():
    return MARKET_CANDIDATES[:]


def asset_quality_score(symbol):
    candles = get_candles(symbol)
    if not candles or len(candles) < 60:
        return 0

    closes = [c["close"] for c in candles]

    e9 = ema_last(closes, 9)
    e21 = ema_last(closes, 21)
    rsi = rsi_last(closes, 14)

    if e9 is None or e21 is None or rsi is None:
        return 0

    volatility = abs(closes[-1] - closes[-12]) / closes[-1]
    trend = abs(e9 - e21) / closes[-1]
    regime = market_regime(closes)

    score = (volatility * 120) + (trend * 180) + (abs(rsi - 50) * 0.35)

    if regime == "RANGE":
        score *= 0.85
    elif regime == "CHOP":
        score *= 0.70

    return score


def update_active_symbols():
    global ACTIVE_SYMBOLS, last_universe_update

    log("ATUALIZANDO UNIVERSO...")

    market = get_market_symbols()
    scored = []

    for symbol in market:
        try:
            score = asset_quality_score(symbol)
            scored.append((symbol, score))
            log(f"{symbol} SCORE {score:.2f}")
        except Exception as e:
            log(f"Erro scoring {symbol}: {e}")

    if not scored:
        ACTIVE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
        last_universe_update = utc_now()
        log("Fallback universo BTC/ETH")
        return

    scored.sort(key=lambda x: x[1], reverse=True)

    top = [s[0] for s in scored[:8]]

    extras = ["SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT"]
    for e in extras:
        if e not in top and e in market:
            top.append(e)

    if len(top) < 3:
        top = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    ACTIVE_SYMBOLS = top[:10]
    last_universe_update = utc_now()

    log(f"NOVO UNIVERSO: {ACTIVE_SYMBOLS}")


# ==========================
# ESCOLHER MELHOR ATIVO
# ==========================
def escolher_melhor_ativo():
    update_mode()

    melhor_symbol = None
    melhor_score = -1
    melhor_direcao = None

    fallback_symbol = None
    fallback_score = -1
    fallback_direcao = None

    if adaptive_mode == "CONSERVADOR":
        min_trend = 0.0012
        min_atr = 0.00075
        rsi_buy = 56
        rsi_sell = 44
        rsi_neutro_min = 47
        rsi_neutro_max = 53
        allow_chop = False
        move_max = 0.015
    elif adaptive_mode == "NORMAL":
        min_trend = 0.0009
        min_atr = 0.00060
        rsi_buy = 54
        rsi_sell = 46
        rsi_neutro_min = 46
        rsi_neutro_max = 54
        allow_chop = False
        move_max = 0.020
    else:
        min_trend = 0.0006
        min_atr = 0.00045
        rsi_buy = 52
        rsi_sell = 48
        rsi_neutro_min = 44
        rsi_neutro_max = 56
        allow_chop = True
        move_max = 0.028

    log(f"MODO: {adaptive_mode}")

    for symbol in ACTIVE_SYMBOLS:
        if ja_tem_operacao(symbol):
            if DEBUG_REJEICOES:
                log(f"{symbol} -> IGNORADO (já em operação)")
            continue

        if em_cooldown(symbol):
            if DEBUG_REJEICOES:
                log(f"{symbol} -> IGNORADO (cooldown)")
            continue

        candles = get_candles(symbol)
        if not candles or len(candles) < 60:
            if DEBUG_REJEICOES:
                log(f"{symbol} -> REJECT (sem candles)")
            continue

        closes = [c["close"] for c in candles]

        e9 = ema_last(closes, 9)
        e21 = ema_last(closes, 21)
        rsi = rsi_last(closes, 14)
        atr_val = atr_like(closes, 14)

        if e9 is None or e21 is None or rsi is None or atr_val is None:
            if DEBUG_REJEICOES:
                log(f"{symbol} -> REJECT (indicadores None)")
            continue

        regime = market_regime(closes)
        trend_pct = abs(e9 - e21) / closes[-1]
        ema_slope = abs(e9 - ema_last(closes[:-3], 9)) / closes[-1] if len(closes) > 20 else 0
        last_move = abs(closes[-1] - closes[-2]) / closes[-2]
        direction = "BUY" if e9 > e21 else "SELL"

        base_score = (
            (trend_pct * 1500) +
            (abs(rsi - 50) * 0.12) +
            ((atr_val / closes[-1]) * 1200) +
            (ema_slope * 1000)
        )

        base_score *= asset_multiplier(symbol)
        base_score *= learning_multiplier(symbol)
        base_score *= hour_multiplier()
        base_score *= session_multiplier()

        if liquidity_sweep(candles):
            base_score *= 0.65

        if regime == "RANGE":
            base_score *= 0.85
        elif regime == "CHOP":
            base_score *= 0.70

        # fallback sempre existe se houver direção minimamente alinhada
        if base_score > fallback_score:
            fallback_score = base_score
            fallback_symbol = symbol
            fallback_direcao = direction

        reasons = []

        if not allow_chop and regime != "TREND":
            reasons.append(f"REGIME {regime}")

        if trend_pct < min_trend:
            reasons.append(f"TREND {trend_pct:.6f}")

        if atr_val < closes[-1] * min_atr:
            reasons.append(f"ATR {atr_val:.6f}")

        if rsi_neutro_min < rsi < rsi_neutro_max:
            reasons.append(f"RSI NEUTRO {rsi:.2f}")

        if last_move > move_max:
            reasons.append("MOVE SPIKE")

        if ema_slope < 0.00020:
            reasons.append("SLOPE FLAT")

        if not ((direction == "BUY" and rsi >= rsi_buy) or (direction == "SELL" and rsi <= rsi_sell)):
            reasons.append("DIR/RSI")

        if reasons:
            if DEBUG_REJEICOES:
                log(f"{symbol} -> REJECT ({', '.join(reasons)}) | score={base_score:.3f}")
            continue

        if DEBUG_REJEICOES:
            log(f"{symbol} -> OK score={base_score:.3f} regime={regime}")

        if base_score > melhor_score:
            melhor_score = base_score
            melhor_symbol = symbol
            melhor_direcao = direction

    if melhor_symbol is not None:
        log(f"ESCOLHIDO: {melhor_symbol} | {melhor_direcao} | {melhor_score:.3f}")
        return melhor_symbol, melhor_direcao, melhor_score

    if fallback_symbol is not None:
        log(f"FALLBACK: {fallback_symbol} | {fallback_direcao} | {fallback_score:.3f}")
        return fallback_symbol, fallback_direcao, fallback_score

    log("Nenhum ativo disponível no fallback")
    return None, None, None


# ==========================
# SINAL
# ==========================
def criar_sinal(symbol, direcao, score):
    global setup_pendente, last_signal_time

    agora_utc = utc_now()

    # entrada no próximo candle de 15m
    entrada_time = next_timeframe(agora_utc)

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
    log(f"SINAL | {symbol} | {direcao} | {score:.3f}")


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
        p1 = entrada_time + timedelta(minutes=TIMEFRAME_MINUTES)
        p2 = entrada_time + timedelta(minutes=TIMEFRAME_MINUTES * 2)

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


def marcar_trade(symbol):
    global last_trade_time
    ultimo_trade_por_ativo[symbol] = utc_now()
    last_trade_time = utc_now()


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

        # ETAPA 0 — ENTRADA
        if op["etapa"] == 0:
            if agora_utc < op["tempo_entrada"] + timedelta(minutes=TIMEFRAME_MINUTES, seconds=EVAL_GRACE_SECONDS):
                novas_operacoes.append(op)
                continue

            vela_atual = candle_por_abertura(candles, op["tempo_entrada"])
            vela_anterior = candle_por_abertura(candles, op["tempo_entrada"] - timedelta(minutes=TIMEFRAME_MINUTES))

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
                registrar_resultado_aprendizado(symbol, True)
                marcar_trade(symbol)
                enviar_resultado(symbol, "WIN na Entrada")
                continue

            op["etapa"] = 1
            novas_operacoes.append(op)
            continue

        # ETAPA 1 — PROTEÇÃO 1
        if op["etapa"] == 1:
            if agora_utc < op["tempo_protecao1"] + timedelta(minutes=TIMEFRAME_MINUTES, seconds=EVAL_GRACE_SECONDS):
                novas_operacoes.append(op)
                continue

            vela_atual = candle_por_abertura(candles, op["tempo_protecao1"])
            vela_anterior = candle_por_abertura(candles, op["tempo_protecao1"] - timedelta(minutes=TIMEFRAME_MINUTES))

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
                registrar_resultado_aprendizado(symbol, True)
                marcar_trade(symbol)
                enviar_resultado(symbol, "WIN na Proteção 1")
                continue

            op["etapa"] = 2
            novas_operacoes.append(op)
            continue

        # ETAPA 2 — PROTEÇÃO 2
        if op["etapa"] == 2:
            if agora_utc < op["tempo_protecao2"] + timedelta(minutes=TIMEFRAME_MINUTES, seconds=EVAL_GRACE_SECONDS):
                novas_operacoes.append(op)
                continue

            vela_atual = candle_por_abertura(candles, op["tempo_protecao2"])
            vela_anterior = candle_por_abertura(candles, op["tempo_protecao2"] - timedelta(minutes=TIMEFRAME_MINUTES))

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
                registrar_resultado_aprendizado(symbol, True)
                marcar_trade(symbol)
                enviar_resultado(symbol, "WIN na Proteção 2")
            else:
                losses += 1
                performance[symbol]["loss"] += 1
                registrar_resultado_aprendizado(symbol, False)
                marcar_trade(symbol)
                enviar_resultado(symbol, "LOSS após Proteção 2")

            continue

    operacoes_ativas.clear()
    operacoes_ativas.extend(novas_operacoes)


# ==========================
# LOOP PRINCIPAL
# ==========================
def main():
    global last_signal_time
    global last_universe_update

    if TOKEN == "COLOQUE_SEU_TOKEN_AQUI" or CHAT_ID == "COLOQUE_SEU_CHAT_ID_AQUI":
        log("ERRO: configure BOT_TOKEN e CHAT_ID nas variáveis de ambiente do Railway.")
        return

    remover_webhook()
    carregar_aprendizado()
    log("BOT INICIANDO...")
    enviar("🤖 BOT INICIADO COM SUCESSO")

    while True:
        try:
            verificar_comandos()

            if BOT_ATIVO:
                if last_universe_update is None or (utc_now() - last_universe_update).total_seconds() > UNIVERSE_REFRESH:
                    update_active_symbols()

                processar_setup_pendente()
                verificar_resultados()

                agora_utc = utc_now()

                if setup_pendente is None and not operacoes_ativas:
                    if last_signal_time is None or (agora_utc - last_signal_time).total_seconds() >= SIGNAL_INTERVAL:
                        symbol, direcao, score = escolher_melhor_ativo()
                        if symbol:
                            criar_sinal(symbol, direcao, score)

            time.sleep(15)

        except Exception as e:
            log(f"Erro geral: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
