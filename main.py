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

INTERVAL = "1min"
TREND_INTERVAL = "15min"
SIGNAL_INTERVAL = 120
BR_TZ = timezone(timedelta(hours=-3))

wins = 0
losses = 0

operacoes_ativas = []
setup_pendente = None
last_signal_time = None

LAST_UPDATE_ID = None
BOT_ATIVO = False

# ==========================
# COOLDOWN POR ATIVO
# ==========================
COOLDOWN_MINUTOS = 7  # pode ajustar 5–10
ultimo_trade_por_ativo = {}

# ==========================
# UNIVERSO DINÂMICO
# ==========================
ACTIVE_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "XRPUSDT",
    "SOLUSDT",
    "ADAUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "XLMUSDT"
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
    "LTCUSDT": {"win": 0, "loss": 0},
    "XLMUSDT": {"win": 0, "loss": 0},
}

# ==========================
# APRENDIZADO AUTOMÁTICO
# ==========================
learning_data = {
    "asset_stats": {},
    "hour_stats": {}
}

LEARNING_FILE = "learning.json"

def ensure_symbol_state(symbol):
    if symbol not in performance:
        performance[symbol] = {"win": 0, "loss": 0}
    if symbol not in learning_data["asset_stats"]:
        learning_data["asset_stats"][symbol] = {"win": 0, "loss": 0}

def carregar_aprendizado():
    global learning_data

    if os.path.exists(LEARNING_FILE):
        try:
            with open(LEARNING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    learning_data = data
                    if "asset_stats" not in learning_data:
                        learning_data["asset_stats"] = {}
                    if "hour_stats" not in learning_data:
                        learning_data["hour_stats"] = {}
            log("Aprendizado carregado.")
        except Exception as e:
            log(f"Erro ao carregar aprendizado: {e}")

def salvar_aprendizado():
    try:
        with open(LEARNING_FILE, "w", encoding="utf-8") as f:
            json.dump(learning_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Erro ao salvar aprendizado: {e}")

def registrar_resultado_aprendizado(symbol, win):
    hour = str(br_now().hour)

    ensure_symbol_state(symbol)

    if win:
        learning_data["asset_stats"][symbol]["win"] += 1
    else:
        learning_data["asset_stats"][symbol]["loss"] += 1

    if hour not in learning_data["hour_stats"]:
        learning_data["hour_stats"][hour] = {"win": 0, "loss": 0}

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
        if not TOKEN or not CHAT_ID:
            log("BOT_TOKEN ou CHAT_ID não configurado.")
            return

        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        log(f"Erro envio Telegram: {e}")

def remover_webhook():
    try:
        if not TOKEN:
            return
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
        if not TOKEN:
            return

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
# MULTIPLICADOR POR ATIVO
# ==========================
def asset_multiplier(symbol):
    ensure_symbol_state(symbol)

    data = performance.get(symbol, {"win": 0, "loss": 0})
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
# KUCOIN HELPERS
# ==========================
def to_kucoin_symbol(symbol):
    return symbol.replace("USDT", "-USDT")

def get_candles(symbol, interval="1min", limit=120):
    try:
        kucoin_symbol = to_kucoin_symbol(symbol)

        url = "https://api.kucoin.com/api/v1/market/candles"
        params = {
            "type": interval,
            "symbol": kucoin_symbol
        }

        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        if "data" not in data or not isinstance(data["data"], list):
    log(f"Resposta inválida candles {symbol} ({interval}) -> {data}")
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
            except:
                continue

        return candles

    except Exception as e:
        log(f"Erro candles {symbol} ({interval}): {e}")
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
        ema_val = ((price - ema_val) * k) + ema_val

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
# FILTROS INTELIGENTES
# ==========================
def volume_confirmation(candles):
    if not candles or len(candles) < 25:
        return False, 0.0

    vols = [c["volume"] for c in candles[-21:-1]]
    if not vols:
        return False, 0.0

    avg_vol = sum(vols) / len(vols)
    last_vol = candles[-1]["volume"]

    if avg_vol <= 0:
        return False, 0.0

    ratio = last_vol / avg_vol
    return ratio >= 0.95, ratio

def should_trade(symbol, closes_1m, closes_15m, candles_1m, candles_15m):
    e9_1m = ema_last(closes_1m, 9)
    e21_1m = ema_last(closes_1m, 21)
    rsi_1m = rsi_last(closes_1m, 14)

    e9_15m = ema_last(closes_15m, 9)
    e21_15m = ema_last(closes_15m, 21)
    rsi_15m = rsi_last(closes_15m, 14)

    if None in [e9_1m, e21_1m, rsi_1m, e9_15m, e21_15m, rsi_15m]:
        return None

    # Evita lateralidade muito fraca
    trend_1m = abs(e9_1m - e21_1m) / closes_1m[-1]
    trend_15m = abs(e9_15m - e21_15m) / closes_15m[-1]

    if trend_1m < 0.00035:
        return None

    if trend_15m < 0.00025:
        return None

    # Evita zona morta do RSI
    if 45 <= rsi_1m <= 55:
        return None

    # Confirmar volume
    vol_ok, vol_ratio = volume_confirmation(candles_1m)
    if not vol_ok:
        return None

    # Direção principal
    if e9_1m > e21_1m and e9_15m > e21_15m and rsi_1m >= 50:
        direction = "BUY"
    elif e9_1m < e21_1m and e9_15m < e21_15m and rsi_1m <= 50:
        direction = "SELL"
    else:
        return None

    # Score mais inteligente
    score = 0.0
    score += trend_1m * 120
    score += trend_15m * 90
    score += abs(rsi_1m - 50) * 0.05
    score += min(vol_ratio, 2.0) * 0.08

    return {
        "direction": direction,
        "score": score,
        "trend_1m": trend_1m,
        "trend_15m": trend_15m,
        "rsi_1m": rsi_1m,
        "rsi_15m": rsi_15m,
        "vol_ratio": vol_ratio,
    }

# ==========================
# AUTO SELEÇÃO DE UNIVERSO
# ==========================
def get_market_symbols():
    return [
        "BTCUSDT",
        "ETHUSDT",
        "XRPUSDT",
        "SOLUSDT",
        "ADAUSDT",
        "BNBUSDT",
        "DOGEUSDT",
        "LTCUSDT",
        "XLMUSDT"
    ]

# ==========================
# QUALITY SCORE DO ATIVO
# ==========================
def asset_quality_score(symbol):
    candles_1m = get_candles(symbol, interval=INTERVAL, limit=120)
    candles_15m = get_candles(symbol, interval=TREND_INTERVAL, limit=120)

    if not candles_1m or not candles_15m or len(candles_1m) < 60 or len(candles_15m) < 60:
        return 0

    closes_1m = [c["close"] for c in candles_1m]
    closes_15m = [c["close"] for c in candles_15m]

    e9_1m = ema_last(closes_1m, 9)
    e21_1m = ema_last(closes_1m, 21)
    rsi_1m = rsi_last(closes_1m, 14)

    e9_15m = ema_last(closes_15m, 9)
    e21_15m = ema_last(closes_15m, 21)
    rsi_15m = rsi_last(closes_15m, 14)

    if None in [e9_1m, e21_1m, rsi_1m, e9_15m, e21_15m, rsi_15m]:
        return 0

    volatility = abs(closes_1m[-1] - closes_1m[-10]) / closes_1m[-1]
    trend_1m = abs(e9_1m - e21_1m) / closes_1m[-1]
    trend_15m = abs(e9_15m - e21_15m) / closes_15m[-1]

    vol_ok, vol_ratio = volume_confirmation(candles_1m)

    score = 0.0
    score += volatility * 35
    score += trend_1m * 110
    score += trend_15m * 90
    score += abs(rsi_1m - 50) * 0.18
    score += abs(rsi_15m - 50) * 0.08
    score += (vol_ratio * 0.12) if vol_ok else 0

    return score

# ==========================
# ATUALIZAR UNIVERSO
# ==========================
def update_active_symbols():
    global ACTIVE_SYMBOLS
    global last_universe_update

    log("ATUALIZANDO UNIVERSO...")

    market = get_market_symbols()
    scored = []

    for symbol in market:
        try:
            ensure_symbol_state(symbol)
            score = asset_quality_score(symbol)
            scored.append((symbol, score))
            log(f"{symbol} SCORE {score:.2f}")
        except Exception as e:
            log(f"Erro scoring {symbol}: {e}")

    if len(scored) == 0:
        ACTIVE_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
        log("Fallback universo BTC/ETH")
        return

    scored.sort(key=lambda x: x[1], reverse=True)

    top = [s[0] for s in scored[:8]]

    if len(top) < 3:
        top = ["BTCUSDT", "ETHUSDT"]

    ACTIVE_SYMBOLS = top
    last_universe_update = utc_now()

    log(f"NOVO UNIVERSO: {ACTIVE_SYMBOLS}")

# ==========================
# ESCOLHER MELHOR ATIVO
# ==========================
def escolher_melhor_ativo():
    melhor_symbol = None
    melhor_score = -1
    melhor_direcao = None

    for symbol in ACTIVE_SYMBOLS:
        ensure_symbol_state(symbol)

        if symbol in ultimo_trade_por_ativo:
            tempo_passado = (utc_now() - ultimo_trade_por_ativo[symbol]).total_seconds()
            if tempo_passado < COOLDOWN_MINUTOS * 60:
                log(f"{symbol} em cooldown")
                continue

        candles_1m = get_candles(symbol, interval=INTERVAL, limit=120)
        candles_15m = get_candles(symbol, interval=TREND_INTERVAL, limit=120)

        if not candles_1m or not candles_15m or len(candles_1m) < 60 or len(candles_15m) < 60:
            continue

        closes_1m = [c["close"] for c in candles_1m]
        closes_15m = [c["close"] for c in candles_15m]

        setup = should_trade(symbol, closes_1m, closes_15m, candles_1m, candles_15m)
        if not setup:
            continue

        direction = setup["direction"]
        score = setup["score"]

        score *= asset_multiplier(symbol)
        score *= learning_multiplier(symbol)
        score *= hour_multiplier()

        if score > melhor_score:
            melhor_score = score
            melhor_symbol = symbol
            melhor_direcao = direction

    return melhor_symbol, melhor_direcao, melhor_score

# ==========================
# CRIAR SINAL
# ==========================
def criar_sinal(symbol, direcao, score):
    global setup_pendente
    global last_signal_time

    agora_utc = utc_now()

    entrada_time = next_minute(agora_utc) + timedelta(minutes=1)

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

        ultimo_trade_por_ativo[symbol] = utc_now()

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
    taxa = (wins / total) * 100 if total > 0 else 0

    enviar(
        "🏆 RESULTADO\n\n"
        f"🌎 {symbol}\n"
        f"{'✅' if 'WIN' in resultado else '❌'} {resultado}\n\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Precisão: {round(taxa, 1)}%"
    )

def verificar_resultados():
    global wins
    global losses

    agora_utc = utc_now()
    novas_operacoes = []

    for op in operacoes_ativas:
        symbol = op["symbol"]
        direcao = op["direcao"]

        candles = get_candles(symbol, interval=INTERVAL, limit=120)
        if candles is None:
            novas_operacoes.append(op)
            continue

        # ==========================
        # ETAPA 0 — ENTRADA
        # ==========================
        if op["etapa"] == 0:
            if agora_utc < op["tempo_entrada"] + timedelta(minutes=1, seconds=5):
                novas_operacoes.append(op)
                continue

            vela_atual = candle_por_abertura(candles, op["tempo_entrada"])
            vela_anterior = candle_por_abertura(candles, op["tempo_entrada"] - timedelta(minutes=1))

            if vela_atual is None or vela_anterior is None:
                novas_operacoes.append(op)
                continue

            win = (
                vela_atual["close"] > vela_anterior["close"]
                if direcao == "BUY"
                else vela_atual["close"] < vela_anterior["close"]
            )

            if win:
                wins += 1
                performance[symbol]["win"] += 1
                registrar_resultado_aprendizado(symbol, True)
                enviar_resultado(symbol, "WIN na Entrada")
                continue

            op["etapa"] = 1
            novas_operacoes.append(op)
            continue

        # ==========================
        # ETAPA 1 — PROTEÇÃO 1
        # ==========================
        if op["etapa"] == 1:
            if agora_utc < op["tempo_protecao1"] + timedelta(minutes=1, seconds=5):
                novas_operacoes.append(op)
                continue

            vela_atual = candle_por_abertura(candles, op["tempo_protecao1"])
            vela_anterior = candle_por_abertura(candles, op["tempo_protecao1"] - timedelta(minutes=1))

            if vela_atual is None or vela_anterior is None:
                novas_operacoes.append(op)
                continue

            win = (
                vela_atual["close"] > vela_anterior["close"]
                if direcao == "BUY"
                else vela_atual["close"] < vela_anterior["close"]
            )

            if win:
                wins += 1
                performance[symbol]["win"] += 1
                registrar_resultado_aprendizado(symbol, True)
                enviar_resultado(symbol, "WIN na Proteção 1")
                continue

            op["etapa"] = 2
            novas_operacoes.append(op)
            continue

        # ==========================
        # ETAPA 2 — PROTEÇÃO 2
        # ==========================
        if op["etapa"] == 2:
            if agora_utc < op["tempo_protecao2"] + timedelta(minutes=1, seconds=5):
                novas_operacoes.append(op)
                continue

            vela_atual = candle_por_abertura(candles, op["tempo_protecao2"])
            vela_anterior = candle_por_abertura(candles, op["tempo_protecao2"] - timedelta(minutes=1))

            if vela_atual is None or vela_anterior is None:
                novas_operacoes.append(op)
                continue

            win = (
                vela_atual["close"] > vela_anterior["close"]
                if direcao == "BUY"
                else vela_atual["close"] < vela_anterior["close"]
            )

            if win:
                wins += 1
                performance[symbol]["win"] += 1
                registrar_resultado_aprendizado(symbol, True)
                enviar_resultado(symbol, "WIN na Proteção 2")
            else:
                losses += 1
                performance[symbol]["loss"] += 1
                registrar_resultado_aprendizado(symbol, False)
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
                    or (utc_now() - last_universe_update).total_seconds() > UNIVERSE_REFRESH
                ):
                    update_active_symbols()

                processar_setup_pendente()
                verificar_resultados()

                # Gera novo sinal respeitando intervalo mínimo
                if setup_pendente is None:
                    if last_signal_time is None or (utc_now() - last_signal_time).total_seconds() >= SIGNAL_INTERVAL:
                        symbol, direcao, score = escolher_melhor_ativo()
                        if symbol and direcao:
                            criar_sinal(symbol, direcao, score)

            time.sleep(5)

        except Exception as e:
            log(f"ERRO NO LOOP PRINCIPAL: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
