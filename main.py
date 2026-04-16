# -*- coding: utf-8 -*-
import os
import time
import json
import math
import requests
from collections import deque
from datetime import datetime, timedelta, timezone

# ==========================
# SESSÃO HTTP COM RETRY
# ==========================

SESSION = requests.Session()

def safe_get(url, params=None, timeout=10, retries=2, backoff=0.6):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return SESSION.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last_exc

def safe_post(url, data=None, timeout=10, retries=2, backoff=0.6):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return SESSION.post(url, data=data, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise last_exc

# ==========================
# CONFIGURAÇÕES
# ==========================

TWELVE_API_KEY = os.getenv("TWELVE_API_KEY", "59f633d02fdf48b4bbd66713cf3d6a81").strip()
TOKEN = os.getenv("BOT_TOKEN", "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ").strip()
CHAT_ID = os.getenv("CHAT_ID", "1056795017").strip()

TIMEFRAME_MINUTES = 1
CANDLE_TYPE = "1min"

# Menos frequência de sinais para economizar requisições
SIGNAL_INTERVAL = 180
UNIVERSE_REFRESH = 900
COOLDOWN_MINUTES = 5
EVAL_GRACE_SECONDS = 20

# Pequeno atraso extra para reduzir leitura antecipada da expiração
EXTRA_EVAL_DELAY_SECONDS = 2

# Tolerância para latência
TOLERANCIA = 0.00015

REPORT_INTERVAL_SECONDS = 6 * 60 * 60
REPORT_AFTER_TRADES = 25

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

last_learning_report_time = None
last_learning_report_trade_count = 0
total_closed_trades = 0

trade_history = deque(maxlen=500)

# ==========================
# CACHE INTELIGENTE
# ==========================

candles_cache = {}
candles_cache_expires = {}
PRICE_CACHE_SECONDS = 20
price_cache = {}
price_cache_expires = {}

# ==========================
# UNIVERSO FOREX
# ==========================

MARKET_CANDIDATES = [
    {"id": "EURUSD", "label": "EUR/USD", "source": "EUR/USD"},
    {"id": "GBPUSD", "label": "GBP/USD", "source": "GBP/USD"},
    {"id": "USDJPY", "label": "USD/JPY", "source": "USD/JPY"},
    {"id": "AUDUSD", "label": "AUD/USD", "source": "AUD/USD"},
    {"id": "USDCAD", "label": "USD/CAD", "source": "USD/CAD"},
]

ACTIVE_ASSETS = MARKET_CANDIDATES.copy()

performance = {
    asset["id"]: {"win": 0, "loss": 0}
    for asset in MARKET_CANDIDATES
}

def update_active_symbols():
    global ACTIVE_ASSETS, last_universe_update
    ACTIVE_ASSETS = MARKET_CANDIDATES.copy()
    last_universe_update = utc_now()
    log(f"Universo atualizado: {len(ACTIVE_ASSETS)} ativos")

# ==========================
# APRENDIZADO
# ==========================

FEATURE_ORDER = [
    "trend_strength",
    "rsi_alignment",
    "fib_confluence",
    "volume_strength",
    "atr_strength",
    "slope_strength",
    "regime_strength",
    "momentum_strength",
    "liquidity_strength",
]

DEFAULT_FEATURE_WEIGHTS = {
    "trend_strength": 1.15,
    "rsi_alignment": 1.00,
    "fib_confluence": 1.10,
    "volume_strength": 0.90,
    "atr_strength": 0.85,
    "slope_strength": 1.00,
    "regime_strength": 0.95,
    "momentum_strength": 0.75,
    "liquidity_strength": 0.90,
}

learning_data = {
    "asset_stats": {},
    "hour_stats": {},
    "regime_stats": {},
    "fib_stats": {},
    "direction_stats": {},
    "pattern_stats": {},
}

model_state = {
    "feature_weights": DEFAULT_FEATURE_WEIGHTS.copy(),
    "bias": 0.0,
}

MODEL_FILE = "hedge_model.json"

# ==========================
# TEMPO
# ==========================

def utc_now():
    return datetime.now(timezone.utc)

def br_now():
    return utc_now().astimezone(BR_TZ)

def floor_timeframe(dt):
    return dt.replace(second=0, microsecond=0)

def next_timeframe(dt):
    return floor_timeframe(dt) + timedelta(minutes=TIMEFRAME_MINUTES)

def fmt_br(dt):
    return dt.astimezone(BR_TZ).strftime("%H:%M")

def next_candle_refresh_time():
    # espera alguns segundos após virar o minuto para garantir candle fechado no provider
    return floor_timeframe(utc_now()) + timedelta(minutes=1, seconds=5)

# ==========================
# UTIL
# ==========================

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def sigmoid(x):
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 1.0 if x > 0 else 0.0

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def safe_bucket(bucket_name):
    if bucket_name not in learning_data:
        learning_data[bucket_name] = {}

def comparar_resultado(preco_entrada, preco_saida, direcao):
    if preco_entrada is None or preco_saida is None:
        return None

    if direcao == "BUY":
        return (float(preco_saida) - float(preco_entrada)) > TOLERANCIA
    return (float(preco_entrada) - float(preco_saida)) > TOLERANCIA

def parse_twelvedata_datetime(value):
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        pass

    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

# ==========================
# MODELO / PERSISTÊNCIA
# ==========================

def carregar_modelo():
    global learning_data, model_state

    if not os.path.exists(MODEL_FILE):
        return

    try:
        with open(MODEL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            ld = data.get("learning_data")
            if isinstance(ld, dict):
                for bucket in learning_data:
                    if bucket in ld and isinstance(ld[bucket], dict):
                        learning_data[bucket].update(ld[bucket])

            ms = data.get("model_state")
            if isinstance(ms, dict):
                fw = ms.get("feature_weights")
                if isinstance(fw, dict):
                    for k, v in fw.items():
                        try:
                            model_state["feature_weights"][k] = float(v)
                        except Exception:
                            pass
                try:
                    model_state["bias"] = float(ms.get("bias", 0.0))
                except Exception:
                    pass

        log("Aprendizado carregado.")
    except Exception as e:
        log(f"Erro ao carregar aprendizado: {e}")

def salvar_modelo():
    try:
        payload = {
            "learning_data": learning_data,
            "model_state": model_state,
        }
        with open(MODEL_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        log(f"Erro ao salvar aprendizado: {e}")

def _bump_bucket(bucket_name, key, win):
    if not key:
        return
    safe_bucket(bucket_name)
    if key not in learning_data[bucket_name]:
        learning_data[bucket_name][key] = {"win": 0, "loss": 0}
    if win:
        learning_data[bucket_name][key]["win"] += 1
    else:
        learning_data[bucket_name][key]["loss"] += 1

def registrar_resultado_aprendizado(asset_id, win, meta=None):
    meta = meta or {}
    hour = str(br_now().hour)

    _bump_bucket("asset_stats", asset_id, win)
    _bump_bucket("hour_stats", hour, win)
    _bump_bucket("regime_stats", meta.get("regime"), win)
    _bump_bucket("fib_stats", meta.get("fib_zone"), win)
    _bump_bucket("direction_stats", meta.get("direction"), win)
    _bump_bucket("pattern_stats", meta.get("pattern"), win)

    salvar_modelo()

def bucket_multiplier(bucket_name, key, min_total=5, high=0.65, low=0.40, up=1.15, down=0.85):
    if not key:
        return 1.0

    data = learning_data.get(bucket_name, {}).get(key)
    if not data:
        return 1.0

    total = data["win"] + data["loss"]
    if total < min_total:
        return 1.0

    winrate = data["win"] / total

    if winrate > high:
        return up
    if winrate < low:
        return down
    return 1.0

def learning_multiplier(asset_id):
    return bucket_multiplier("asset_stats", asset_id, min_total=5, high=0.65, low=0.40, up=1.20, down=0.80)

def hour_multiplier():
    return bucket_multiplier("hour_stats", str(br_now().hour), min_total=5, high=0.65, low=0.40, up=1.15, down=0.85)

def regime_multiplier(regime):
    return bucket_multiplier("regime_stats", regime, min_total=8, high=0.60, low=0.40, up=1.12, down=0.85)

def fib_multiplier(fib_zone):
    return bucket_multiplier("fib_stats", fib_zone, min_total=8, high=0.60, low=0.40, up=1.12, down=0.85)

def direction_multiplier(direction):
    return bucket_multiplier("direction_stats", direction, min_total=8, high=0.60, low=0.40, up=1.08, down=0.92)

def pattern_multiplier(pattern):
    return bucket_multiplier("pattern_stats", pattern, min_total=8, high=0.60, low=0.40, up=1.15, down=0.85)

def session_multiplier():
    hour = br_now().hour
    if 1 <= hour <= 6:
        return 0.85
    if 8 <= hour <= 18:
        return 1.10
    return 1.0

def online_update(features, win):
    target = 1.0 if win else 0.0
    pred = model_probability(features)
    error = target - pred
    lr = 0.05

    for k, v in features.items():
        if k not in model_state["feature_weights"]:
            continue
        old = model_state["feature_weights"][k]
        delta = lr * error * (float(v) - 0.5)
        model_state["feature_weights"][k] = clamp(old + delta, 0.35, 2.50)

    model_state["bias"] = clamp(model_state["bias"] + lr * error * 0.25, -2.5, 2.5)
    salvar_modelo()

# ==========================
# TELEGRAM
# ==========================

def enviar(msg):
    try:
        if not TOKEN or not CHAT_ID:
            log("Telegram não configurado: BOT_TOKEN ou CHAT_ID ausente.")
            return

        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg}
        r = safe_post(url, data=payload, timeout=10)

        if r.status_code != 200:
            log(f"Erro Telegram: {r.status_code} | {r.text}")
    except Exception as e:
        log(f"Erro envio Telegram: {e}")

def remover_webhook():
    try:
        if not TOKEN:
            return
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        safe_get(url, timeout=10)
    except Exception:
        pass

def verificar_comandos():
    global LAST_UPDATE_ID, BOT_ATIVO

    try:
        if not TOKEN:
            return

        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
        params = {}
        if LAST_UPDATE_ID is not None:
            params["offset"] = LAST_UPDATE_ID + 1

        r = safe_get(url, params=params, timeout=10)
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

            elif texto == "/report":
                report_learning_to_telegram(force=True)

            elif texto == "/status":
                total = wins + losses
                wr = (wins / total) * 100 if total else 0
                enviar(
                    "📌 STATUS\n\n"
                    f"Ativo: {BOT_ATIVO}\n"
                    f"Wins: {wins}\n"
                    f"Losses: {losses}\n"
                    f"Precisão: {wr:.1f}%\n"
                    f"Modo: {adaptive_mode}\n"
                    f"Universo: {', '.join([a['label'] for a in ACTIVE_ASSETS])}"
                )

    except Exception as e:
        log(f"Erro comandos: {e}")

# ==========================
# API / HELPERS
# ==========================

def get_price(asset):
    try:
        asset_id = asset["id"]
        symbol = asset["source"]

        agora = utc_now()
        if asset_id in price_cache:
            exp = price_cache_expires.get(asset_id)
            if exp and agora < exp:
                return price_cache[asset_id]

        url = "https://api.twelvedata.com/price"
        params = {
            "symbol": symbol,
            "apikey": TWELVE_API_KEY
        }

        r = safe_get(url, params=params, timeout=10)

        if r.status_code != 200:
            log(f"Erro HTTP preço {asset_id}: {r.status_code}")
            return None

        data = r.json()

        if isinstance(data, dict) and data.get("status") == "error":
            log(f"Erro API preço {asset_id}: {data}")
            return None

        price = data.get("price")
        if price is None:
            log(f"Erro API preço {asset_id}: {data}")
            return None

        val = float(price)
        price_cache[asset_id] = val
        price_cache_expires[asset_id] = agora + timedelta(seconds=PRICE_CACHE_SECONDS)
        time.sleep(0.2)
        return val

    except Exception as e:
        log(f"Erro preço {asset['id']}: {e}")
        return None

# ==========================
# INDICADORES
# ==========================

def avaliar_por_vela(asset, direcao):
    candles = get_candles(asset, limit=3)
    if not candles or len(candles) < 2:
        return None

    candle = candles[-2]  # última vela FECHADA

    entrada = candle["open"]
    saida = candle["close"]

    if direcao == "BUY":
        return saida > entrada
    else:
        return saida < entrada

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

def average_volume(candles, window=20):
    if len(candles) < window + 1:
        return None
    vols = [c["volume"] for c in candles]
    avg = sum(vols[-(window + 1):-1]) / window
    if avg <= 0:
        return None
    return vols[-1] / avg

# ==========================
# CONTEXTO / FIBONACCI
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

def identificar_padrao(meta):
    regime = meta.get("regime")
    fib_zone = meta.get("fib_zone")
    trend_pct = meta.get("trend_pct", 0.0)
    last_move = meta.get("last_move", 0.0)

    if last_move > 0.0025 and regime == "TREND":
        return "breakout_fib_extension"

    if fib_zone in ("0.236", "near_0.236"):
        return "fib_23_pullback"

    if fib_zone in ("0.382", "near_0.382"):
        return "fib_38_pullback"

    if fib_zone in ("0.500", "near_0.500"):
        return "fib_50_reversal"

    if regime == "TREND" and trend_pct > 0.0008:
        return "trend_continuation"

    return "trend_continuation" if regime == "TREND" else "fib_50_reversal"

def fib_analysis(candles, direction):
    closes = [c["close"] for c in candles]
    if len(closes) < 20:
        return {"fib_zone": "none", "fib_score": 0.0, "fib_dist": 1.0, "levels": {}}

    window = candles[-48:] if len(candles) > 48 else candles[:]
    swing_high = max(c["high"] for c in window)
    swing_low = min(c["low"] for c in window)

    if swing_high == swing_low:
        return {"fib_zone": "none", "fib_score": 0.0, "fib_dist": 1.0, "levels": {}}

    rng = swing_high - swing_low
    price = closes[-1]

    if direction == "BUY":
        levels = {
            "0.236": swing_low + rng * 0.236,
            "0.382": swing_low + rng * 0.382,
            "0.500": swing_low + rng * 0.500,
            "0.618": swing_low + rng * 0.618,
            "0.786": swing_low + rng * 0.786,
        }
    else:
        levels = {
            "0.236": swing_high - rng * 0.236,
            "0.382": swing_high - rng * 0.382,
            "0.500": swing_high - rng * 0.500,
            "0.618": swing_high - rng * 0.618,
            "0.786": swing_high - rng * 0.786,
        }

    preferred = ["0.382", "0.500", "0.618"]
    best_zone = None
    best_dist = 999.0

    for zone in preferred:
        dist = abs(price - levels[zone]) / price
        if dist < best_dist:
            best_dist = dist
            best_zone = zone

    if best_dist <= 0.0025:
        fib_zone = best_zone
    elif best_dist <= 0.005:
        fib_zone = f"near_{best_zone}"
    else:
        fib_zone = "none"

    fib_score = max(0.0, 1.0 - best_dist * 250)
    if fib_zone == "none":
        fib_score *= 0.35

    return {
        "fib_zone": fib_zone,
        "fib_score": fib_score,
        "fib_dist": best_dist,
        "levels": levels,
    }

def asset_multiplier(asset_id):
    data = performance.get(asset_id, {"win": 1, "loss": 1})
    total = data["win"] + data["loss"]
    if total < 10:
        return 1.0

    winrate = data["win"] / total
    if winrate > 0.65:
        return 1.15
    if winrate < 0.40:
        return 0.85
    return 1.0

def em_cooldown(asset_id):
    if asset_id not in ultimo_trade_por_ativo:
        return False
    delta = (utc_now() - ultimo_trade_por_ativo[asset_id]).total_seconds()
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

def ja_tem_operacao(asset_id):
    for op in operacoes_ativas:
        if op["asset_id"] == asset_id:
            return True
    return False

def score_from_learning(meta):
    asset_id = meta.get("asset_id")
    regime = meta.get("regime")
    fib_zone = meta.get("fib_zone")
    direction = meta.get("direction")
    pattern = meta.get("pattern")

    mult = 1.0
    mult *= learning_multiplier(asset_id)
    mult *= hour_multiplier()
    mult *= regime_multiplier(regime)
    mult *= fib_multiplier(fib_zone)
    mult *= direction_multiplier(direction)
    mult *= pattern_multiplier(pattern)
    mult *= session_multiplier()
    return mult

# ==========================
# IA / SCORE
# ==========================

def vector_from_features(features):
    return [float(features[k]) for k in FEATURE_ORDER]

def model_probability(features):
    weights = model_state["feature_weights"]
    total_w = 0.0
    total = 0.0

    for k, v in features.items():
        w = weights.get(k, 1.0)
        total += w * float(v)
        total_w += abs(w)

    if total_w <= 0:
        return 0.5

    avg = total / total_w
    logit = (avg - 0.5) * 8.0 + model_state["bias"]
    return sigmoid(logit)

def atualizar_pesos(features, win):
    online_update(features, win)

# ==========================
# CANDLES OTIMIZADO
# ==========================

def get_candles(asset, limit=150):
    try:
        asset_id = asset["id"]
        symbol = asset["source"]
        agora = utc_now()

        # Usa cache se ainda está válido
        exp = candles_cache_expires.get(asset_id)
        if asset_id in candles_cache and exp and agora < exp:
            return candles_cache[asset_id]

        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": symbol,
            "interval": "1min",
            "outputsize": limit,
            "apikey": TWELVE_API_KEY
        }

        r = safe_get(url, params=params, timeout=10)

        if r.status_code != 200:
            log(f"Erro HTTP candles {asset_id}: {r.status_code}")
            return None

        data = r.json()

        if isinstance(data, dict) and data.get("status") == "error":
            log(f"Erro API candles {asset_id}: {data}")
            return None

        rows = data.get("values")
        if not rows:
            log(f"Erro API candles {asset_id}: {data}")
            return None

        candles = []

        # TwelveData normalmente retorna do mais recente para o mais antigo
        for row in reversed(rows):
            dt = parse_twelvedata_datetime(row.get("datetime"))
            if dt is None:
                continue

            try:
                candles.append({
                    "time": dt,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0)
                })
            except Exception:
                continue

        if len(candles) < 20:
            return None

        candles_cache[asset_id] = candles
        candles_cache_expires[asset_id] = next_candle_refresh_time()

        # pequeno delay para evitar rate limit
        time.sleep(0.35)

        return candles

    except Exception as e:
        log(f"Erro candles {asset['id']}: {e}")
        return None

# ==========================
# ANÁLISE INTELIGENTE
# ==========================

def analisar_ativo(asset, candles):
    if not candles or len(candles) < 60:
        return None

    closes = [c["close"] for c in candles]
    price = closes[-1]

    e9 = ema_last(closes, 9)
    e21 = ema_last(closes, 21)
    e50 = ema_last(closes, 50)
    rsi = rsi_last(closes, 14)
    atr_val = atr_like(closes, 14)
    vol_ratio = average_volume(candles, 20)

    if e9 is None or e21 is None or e50 is None or rsi is None or atr_val is None:
        return None

    regime = market_regime(closes)
    direction = "BUY" if e9 > e21 else "SELL"
    fib_ctx = fib_analysis(candles, direction)

    trend_pct = abs(e9 - e21) / price
    ema_slope = abs(e9 - ema_last(closes[:-3], 9)) / price if len(closes) > 20 else 0.0
    last_move = abs(closes[-1] - closes[-2]) / closes[-2]
    atr_norm = atr_val / price
    vol_ratio = vol_ratio if vol_ratio is not None else 1.0

    if direction == "BUY":
        rsi_alignment = clamp((rsi - 45) / 25, 0.0, 1.0)
    else:
        rsi_alignment = clamp((55 - rsi) / 25, 0.0, 1.0)

    trend_strength = clamp(trend_pct / 0.0010, 0.0, 1.0)
    atr_strength = clamp(atr_norm / 0.00060, 0.0, 1.0)
    slope_strength = clamp(ema_slope / 0.00025, 0.0, 1.0)
    volume_strength = clamp((vol_ratio - 0.85) / 0.70, 0.0, 1.0)
    regime_strength = {
        "TREND": 1.00,
        "RANGE": 0.65,
        "CHOP": 0.45,
        "UNKNOWN": 0.30,
    }.get(regime, 0.50)
    momentum_strength = clamp(last_move / 0.0015, 0.0, 1.0)
    fib_confluence = fib_ctx["fib_score"]
    liquidity_strength = 0.35 if liquidity_sweep(candles) else 1.0

    pattern = identificar_padrao({
        "regime": regime,
        "fib_zone": fib_ctx["fib_zone"],
        "trend_pct": trend_pct,
        "last_move": last_move,
        "direction": direction,
    })

    features = {
        "trend_strength": trend_strength,
        "rsi_alignment": rsi_alignment,
        "fib_confluence": fib_confluence,
        "volume_strength": volume_strength,
        "atr_strength": atr_strength,
        "slope_strength": slope_strength,
        "regime_strength": regime_strength,
        "momentum_strength": momentum_strength,
        "liquidity_strength": liquidity_strength,
    }

    rule_score = (
        0.28 * trend_strength +
        0.20 * rsi_alignment +
        0.18 * fib_confluence +
        0.10 * volume_strength +
        0.10 * atr_strength +
        0.08 * slope_strength +
        0.06 * regime_strength +
        0.05 * momentum_strength +
        0.05 * liquidity_strength
    )

    model_prob = model_probability(features)
    combined = (0.62 * rule_score) + (0.38 * model_prob)

    combined *= asset_multiplier(asset["id"])
    combined *= score_from_learning({
        "asset_id": asset["id"],
        "regime": regime,
        "fib_zone": fib_ctx["fib_zone"],
        "direction": direction,
        "pattern": pattern,
    })

    if liquidity_sweep(candles):
        combined *= 0.92

    meta = {
        "asset_id": asset["id"],
        "asset_label": asset["label"],
        "direction": direction,
        "regime": regime,
        "fib_zone": fib_ctx["fib_zone"],
        "fib_score": fib_ctx["fib_score"],
        "trend_pct": trend_pct,
        "rsi": rsi,
        "atr_norm": atr_norm,
        "ema_slope": ema_slope,
        "volume_ratio": vol_ratio,
        "last_move": last_move,
        "features": features,
        "rule_score": rule_score,
        "model_prob": model_prob,
        "combined": combined,
        "pattern": pattern,
    }

    return {
        "asset": asset,
        "direction": direction,
        "score": combined,
        "meta": meta,
    }

# ==========================
# RESULTADOS / HISTÓRICO
# ==========================

def register_trade_history(asset_id, win, stage, meta):
    global total_closed_trades
    total_closed_trades += 1
    trade_history.append({
        "time": utc_now().isoformat(),
        "asset_id": asset_id,
        "win": bool(win),
        "stage": stage,
        "regime": meta.get("regime"),
        "fib_zone": meta.get("fib_zone"),
        "pattern": meta.get("pattern"),
        "direction": meta.get("direction"),
        "score": meta.get("combined", meta.get("rule_score", 0.0)),
    })

def report_learning_to_telegram(force=False):
    global last_learning_report_time, last_learning_report_trade_count

    total = wins + losses
    if total < 5 and not force:
        return

    now = utc_now()
    if not force and last_learning_report_time is not None:
        elapsed = (now - last_learning_report_time).total_seconds()
        trades_since = total_closed_trades - last_learning_report_trade_count
        if elapsed < REPORT_INTERVAL_SECONDS and trades_since < REPORT_AFTER_TRADES:
            return

    def bucket_rank(bucket_name, reverse=True, min_trades=5, limit=5):
        bucket = learning_data.get(bucket_name, {})
        rows = []
        for key, data in bucket.items():
            t = data["win"] + data["loss"]
            if t >= min_trades:
                wr = (data["win"] / t) * 100 if t else 0
                rows.append((wr, t, key))
        rows.sort(reverse=reverse)
        return rows[:limit]

    lines = []
    lines.append("📊 RELATÓRIO DE APRENDIZADO")
    lines.append("")
    lines.append(f"Trades fechados: {total}")
    lines.append(f"Wins: {wins}")
    lines.append(f"Losses: {losses}")
    lines.append(f"Precisão geral: {((wins / total) * 100) if total else 0:.1f}%")
    lines.append("")

    def add_section(title, rows):
        lines.append(title + ":")
        if not rows:
            lines.append("- sem dados suficientes")
        for wr, t, key in rows:
            lines.append(f"- {key}: {wr:.1f}% ({t})")
        lines.append("")

    add_section("Top 5 padrões Fibonacci", bucket_rank("pattern_stats", True, limit=5))
    add_section("Melhores ativos", bucket_rank("asset_stats", True, limit=5))
    add_section("Ativos a evitar", bucket_rank("asset_stats", False, limit=5))
    add_section("Melhores horários", bucket_rank("hour_stats", True, limit=5))
    add_section("Melhores regimes", bucket_rank("regime_stats", True, limit=5))
    add_section("Melhores zonas Fibonacci", bucket_rank("fib_stats", True, limit=5))

    lines.append("Pesos atuais:")
    for k, v in model_state["feature_weights"].items():
        lines.append(f"- {k}: {v:.2f}")
    lines.append(f"- bias: {model_state['bias']:.2f}")
    lines.append("")
    lines.append(f"Universo atual: {', '.join([a['label'] for a in ACTIVE_ASSETS])}")

    enviar("\n".join(lines))

    last_learning_report_time = now
    last_learning_report_trade_count = total_closed_trades

def maybe_send_learning_report(force=False):
    report_learning_to_telegram(force=force)

def enviar_resultado(asset_label, resultado):
    total = wins + losses
    taxa = (wins / total) * 100 if total > 0 else 0

    enviar(
        "🏆 RESULTADO\n\n"
        f"🌎 {asset_label}\n"
        f"{'✅' if 'WIN' in resultado else '❌'} {resultado}\n\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Precisão: {round(taxa, 1)}%"
    )
    log(f"RESULTADO | {asset_label} | {resultado} | W={wins} L={losses}")

# ==========================
# VERIFICAR RESULTADOS
# ==========================

def verificar_resultados():
    global wins, losses

    agora_utc = utc_now()
    novas_operacoes = []

    for op in operacoes_ativas:
        asset = op["asset"]
        asset_id = asset["id"]
        asset_label = asset["label"]
        direcao = op["direcao"]
        meta = op.get("meta", {})

        delay = EVAL_GRACE_SECONDS + EXTRA_EVAL_DELAY_SECONDS

        # ETAPA 0 — ENTRADA
        if op["etapa"] == 0:
            if agora_utc < op["tempo_entrada"] + timedelta(minutes=TIMEFRAME_MINUTES, seconds=delay):
                novas_operacoes.append(op)
                continue

            win = avaliar_por_vela(asset, direcao)

            if win is None:
                novas_operacoes.append(op)
                continue

            if win:
                wins += 1
                performance[asset_id]["win"] += 1
                registrar_resultado_aprendizado(asset_id, True, {**meta, "asset_id": asset_id, "direction": direcao})
                atualizar_pesos(meta.get("features", {}), True)
                register_trade_history(asset_id, True, "entrada", meta)
                enviar_resultado(asset_label, "WIN na Entrada")
                maybe_send_learning_report()
                continue

            op["etapa"] = 1
            op["preco_entrada_stage1"] = get_price(asset)
            novas_operacoes.append(op)
            continue

        # ETAPA 1 — PROTEÇÃO 1
        if op["etapa"] == 1:
            if agora_utc < op["tempo_protecao1"] + timedelta(minutes=TIMEFRAME_MINUTES, seconds=delay):
                novas_operacoes.append(op)
                continue

            win = avaliar_por_vela(asset, direcao)

            if win is None:
                novas_operacoes.append(op)
                continue

            if win:
                wins += 1
                performance[asset_id]["win"] += 1
                registrar_resultado_aprendizado(asset_id, True, {**meta, "asset_id": asset_id, "direction": direcao})
                atualizar_pesos(meta.get("features", {}), True)
                register_trade_history(asset_id, True, "proteção_1", meta)
                enviar_resultado(asset_label, "WIN na Proteção 1")
                maybe_send_learning_report()
                continue

            op["etapa"] = 2
            op["preco_entrada_stage2"] = get_price(asset)
            novas_operacoes.append(op)
            continue

        # ETAPA 2 — PROTEÇÃO 2
        if op["etapa"] == 2:
            if agora_utc < op["tempo_protecao2"] + timedelta(minutes=TIMEFRAME_MINUTES, seconds=delay):
                novas_operacoes.append(op)
                continue

            win = avaliar_por_vela(asset, direcao)

            if win is None:
                novas_operacoes.append(op)
                continue

            if win:
                wins += 1
                performance[asset_id]["win"] += 1
                registrar_resultado_aprendizado(asset_id, True, {**meta, "asset_id": asset_id, "direction": direcao})
                atualizar_pesos(meta.get("features", {}), True)
                register_trade_history(asset_id, True, "proteção_2", meta)
                enviar_resultado(asset_label, "WIN na Proteção 2")
            else:
                losses += 1
                performance[asset_id]["loss"] += 1
                registrar_resultado_aprendizado(asset_id, False, {**meta, "asset_id": asset_id, "direction": direcao})
                atualizar_pesos(meta.get("features", {}), False)
                register_trade_history(asset_id, False, "proteção_2", meta)
                enviar_resultado(asset_label, "LOSS após Proteção 2")

            maybe_send_learning_report()
            continue

    operacoes_ativas.clear()
    operacoes_ativas.extend(novas_operacoes)

# ==========================
# ESCOLHA INTELIGENTE
# ==========================

def escolher_melhor_ativo():
    update_mode()

    melhor_asset = None
    melhor_score = -1
    melhor_direcao = None
    melhor_meta = None

    fallback_asset = None
    fallback_score = -1
    fallback_direcao = None
    fallback_meta = None

    if adaptive_mode == "CONSERVADOR":
        min_trend = 0.0009
        min_atr = 0.00045
        min_vol = 0.95
        rsi_buy = 56
        rsi_sell = 44
        allow_chop = False
        max_move = 0.012
        min_combined = 0.58
    elif adaptive_mode == "NORMAL":
        min_trend = 0.00065
        min_atr = 0.00035
        min_vol = 0.90
        rsi_buy = 54
        rsi_sell = 46
        allow_chop = False
        max_move = 0.016
        min_combined = 0.54
    else:
        min_trend = 0.00045
        min_atr = 0.00025
        min_vol = 0.85
        rsi_buy = 52
        rsi_sell = 48
        allow_chop = True
        max_move = 0.022
        min_combined = 0.50

    log(f"MODO: {adaptive_mode}")

    for asset in ACTIVE_ASSETS:
        asset_id = asset["id"]
        asset_label = asset["label"]

        if ja_tem_operacao(asset_id):
            if DEBUG_REJEICOES:
                log(f"{asset_label} -> IGNORADO (já em operação)")
            continue

        if em_cooldown(asset_id):
            if DEBUG_REJEICOES:
                log(f"{asset_label} -> IGNORADO (cooldown)")
            continue

        candles = get_candles(asset)
        if not candles or len(candles) < 60:
            if DEBUG_REJEICOES:
                log(f"{asset_label} -> REJECT (sem candles)")
            continue

        analysis = analisar_ativo(asset, candles)
        if not analysis:
            if DEBUG_REJEICOES:
                log(f"{asset_label} -> REJECT (análise None)")
            continue

        score = analysis["score"]
        meta = analysis["meta"]
        direction = analysis["direction"]

        trend_pct = meta["trend_pct"]
        atr_norm = meta["atr_norm"]
        vol_ratio = meta["volume_ratio"]
        regime = meta["regime"]
        rsi = meta["rsi"]
        last_move = meta["last_move"]
        fib_zone = meta["fib_zone"]
        model_prob = meta["model_prob"]
        rule_score = meta["rule_score"]

        if score > fallback_score:
            fallback_score = score
            fallback_asset = asset
            fallback_direcao = direction
            fallback_meta = meta

        reasons = []

        if not allow_chop and regime != "TREND":
            reasons.append(f"REGIME {regime}")

        if trend_pct < min_trend:
            reasons.append(f"TREND {trend_pct:.6f}")

        if atr_norm < min_atr:
            reasons.append(f"ATR {atr_norm:.6f}")

        if vol_ratio < min_vol:
            reasons.append(f"VOLUME {vol_ratio:.2f}")

        if last_move > max_move:
            reasons.append("MOVE SPIKE")

        if not ((direction == "BUY" and rsi >= rsi_buy) or (direction == "SELL" and rsi <= rsi_sell)):
            reasons.append("DIR/RSI")

        if score < min_combined:
            reasons.append(f"SCORE {score:.3f}")

        if reasons:
            if DEBUG_REJEICOES:
                log(f"{asset_label} -> REJECT ({', '.join(reasons)}) | score={score:.3f} | fib={fib_zone} | p={model_prob:.2f}")
            continue

        if DEBUG_REJEICOES:
            log(
                f"{asset_label} -> OK score={score:.3f} "
                f"regime={regime} fib={fib_zone} rsi={rsi:.2f} "
                f"p={model_prob:.2f} rule={rule_score:.2f}"
            )

        if score > melhor_score:
            melhor_score = score
            melhor_asset = asset
            melhor_direcao = direction
            melhor_meta = meta

    if melhor_asset is not None:
        log(f"ESCOLHIDO: {melhor_asset['label']} | {melhor_direcao} | {melhor_score:.3f}")
        return melhor_asset, melhor_direcao, melhor_score, melhor_meta

    if fallback_asset is not None:
        log(f"FALLBACK: {fallback_asset['label']} | {fallback_direcao} | {fallback_score:.3f}")
        return fallback_asset, fallback_direcao, fallback_score, fallback_meta

    log("Nenhum ativo disponível no fallback")
    return None, None, None, None

# ==========================
# SINAL
# ==========================

def criar_sinal(asset, direcao, score, meta):
    global setup_pendente, last_signal_time

    agora_utc = utc_now()
    entrada_time = next_timeframe(agora_utc) + timedelta(minutes=2)

    setup_pendente = {
        "asset": asset,
        "direcao": direcao,
        "score": score,
        "entrada_time": entrada_time,
        "preparado": False,
        "meta": meta or {},
    }

    last_signal_time = agora_utc

    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 Ativo: {asset['label']}\n"
        f"📊 Estratégia: {'🟢 COMPRA' if direcao == 'BUY' else '🔴 VENDA'}\n"
        f"⏰ Entrada prevista: {fmt_br(entrada_time)}\n"
        f"📈 Força: {score:.3f}\n"
        f"🧠 Fibonacci: {setup_pendente['meta'].get('fib_zone', 'none')}\n"
        f"📊 Regime: {setup_pendente['meta'].get('regime', 'unknown')}"
    )
    log(f"SINAL | {asset['label']} | {direcao} | {score:.3f}")

# ==========================
# SETUP
# ==========================

def processar_setup_pendente():
    global setup_pendente, last_trade_time

    if setup_pendente is None:
        return

    agora_utc = utc_now()

    if agora_utc >= setup_pendente["entrada_time"]:
        asset = setup_pendente["asset"]
        direcao = setup_pendente["direcao"]
        entrada_time = setup_pendente["entrada_time"]
        p1 = entrada_time + timedelta(minutes=TIMEFRAME_MINUTES)
        p2 = entrada_time + timedelta(minutes=TIMEFRAME_MINUTES * 2)

        preco_entrada = get_price(asset)
        if preco_entrada is None:
            log(f"Preço de entrada indisponível para {asset['label']}, aguardando próximo ciclo.")
            return

        ultimo_trade_por_ativo[asset["id"]] = utc_now()
        last_trade_time = utc_now()

        operacoes_ativas.append({
            "asset": asset,
            "asset_id": asset["id"],
            "asset_label": asset["label"],
            "direcao": direcao,
            "etapa": 0,
            "tempo_entrada": entrada_time,
            "tempo_protecao1": p1,
            "tempo_protecao2": p2,
            "preco_entrada": preco_entrada,
            "preco_entrada_stage1": None,
            "preco_entrada_stage2": None,
            "meta": setup_pendente.get("meta", {}),
        })

        enviar(
            "✅ ENTRADA CONFIRMADA ✅\n\n"
            f"🌎 Ativo: {asset['label']}\n"
            f"📊 Estratégia: {'🟢 COMPRA' if direcao == 'BUY' else '🔴 VENDA'}\n"
            f"⏰ Entrada: {fmt_br(entrada_time)}\n\n"
            f"⚠️ Proteção 1: {fmt_br(p1)}\n"
            f"⚠️ Proteção 2: {fmt_br(p2)}"
        )

        log(f"ENTRADA CONFIRMADA | {asset['label']} | {direcao} | preco={preco_entrada}")
        setup_pendente = None

# ==========================
# LOOP AUXILIAR
# ==========================

def tempo_ate_proxima_checagem():
    agora = utc_now()
    seg = agora.second
    micro = agora.microsecond
    falta = 5 - (seg % 5)
    sleep_s = falta - (micro / 1_000_000)
    if sleep_s < 1:
        sleep_s = 1
    return sleep_s

# ==========================
# MAIN LOOP
# ==========================

def main():
    global last_signal_time
    global last_universe_update

    if not TWELVE_API_KEY:
        log("ERRO: configure TWELVE_API_KEY nas variáveis de ambiente do Railway.")
        return

    if not TOKEN or not CHAT_ID:
        log("ERRO: configure BOT_TOKEN e CHAT_ID nas variáveis de ambiente do Railway.")
        return

    remover_webhook()
    carregar_modelo()
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
                        asset, direcao, score, meta = escolher_melhor_ativo()
                        if asset:
                            criar_sinal(asset, direcao, score, meta)

                maybe_send_learning_report()

            time.sleep(tempo_ate_proxima_checagem())

        except Exception as e:
            log(f"Erro geral: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
