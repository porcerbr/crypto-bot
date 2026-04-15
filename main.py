# -*- coding: utf-8 -*-
"""
Bot Forex para Railway usando Yahoo Finance via yfinance.

Fonte de dados:
- yfinance é um wrapper open-source para as APIs públicas do Yahoo Finance,
  com suporte a mercados de câmbio (currencies) e intervalos de 1m.
- É indicado para uso pessoal / pesquisa.

Observação importante:
- Os dados de mercado de fontes públicas podem sofrer atraso, limite de uso
  ou mudanças no provedor. O bot abaixo foi escrito para ser robusto, com cache,
  retries e fallback no próprio histórico local.
"""

import os
import time
import json
import math
from collections import deque
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import yfinance as yf

# ==========================
# CONFIGURAÇÕES
# ==========================
TOKEN = os.getenv("BOT_TOKEN", "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ")
CHAT_ID = os.getenv("CHAT_ID", "1056795017")

# Apenas 3 pares para reduzir carga e ficar mais estável
ACTIVE_ASSETS = [
    {"id": "EURUSD", "label": "EUR/USD", "source": "EURUSD=X"},
    {"id": "GBPUSD", "label": "GBP/USD", "source": "GBPUSD=X"},
    {"id": "USDJPY", "label": "USD/JPY", "source": "USDJPY=X"},
]

TIMEFRAME_MINUTES = 1
SIGNAL_INTERVAL = 75
UNIVERSE_REFRESH = 900
COOLDOWN_MINUTES = 5
EVAL_GRACE_SECONDS = 15
EXTRA_EVAL_DELAY_SECONDS = 2
REPORT_INTERVAL_SECONDS = 6 * 60 * 60
REPORT_AFTER_TRADES = 15
TOLERANCIA = 0.00015

BR_TZ = timezone(timedelta(hours=-3))
DEBUG_REJEICOES = True
POLL_SECONDS = 75
CACHE_SECONDS = 50
BOOTSTRAP_LIMIT = 180

MODEL_FILE = "hedge_model.json"

# ==========================
# ESTADO
# ==========================
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

# cache local por símbolo
CANDLE_CACHE: dict[str, list[dict]] = {}
CANDLE_CACHE_TIME: dict[str, float] = {}
PRICE_CACHE: dict[str, tuple[float, float]] = {}

performance = {asset["id"]: {"win": 0, "loss": 0} for asset in ACTIVE_ASSETS}

learning_data = {
    "asset_stats": {},
    "hour_stats": {},
    "regime_stats": {},
    "pattern_stats": {},
}

model_state = {
    "feature_weights": {
        "trend_strength": 1.15,
        "rsi_alignment": 1.00,
        "atr_strength": 0.90,
        "pullback_strength": 1.00,
        "momentum_strength": 0.85,
        "wick_strength": 0.75,
    },
    "bias": 0.0,
}

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

# ==========================
# MODELO / APRENDIZADO
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
        payload = {"learning_data": learning_data, "model_state": model_state}
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
    _bump_bucket("pattern_stats", meta.get("pattern"), win)
    salvar_modelo()

def bucket_multiplier(bucket_name, key, min_total=5, high=0.65, low=0.40, up=1.12, down=0.88):
    if not key:
        return 1.0
    data = learning_data.get(bucket_name, {}).get(key)
    if not data:
        return 1.0
    total = data["win"] + data["loss"]
    if total < min_total:
        return 1.0
    wr = data["win"] / total
    if wr > high:
        return up
    if wr < low:
        return down
    return 1.0

def learning_multiplier(asset_id):
    return bucket_multiplier("asset_stats", asset_id, min_total=5, high=0.65, low=0.40, up=1.15, down=0.85)

def hour_multiplier():
    return bucket_multiplier("hour_stats", str(br_now().hour), min_total=5, high=0.65, low=0.40, up=1.10, down=0.90)

def regime_multiplier(regime):
    return bucket_multiplier("regime_stats", regime, min_total=8, high=0.60, low=0.40, up=1.10, down=0.90)

def pattern_multiplier(pattern):
    return bucket_multiplier("pattern_stats", pattern, min_total=8, high=0.60, low=0.40, up=1.10, down=0.90)

def online_update(features, win):
    target = 1.0 if win else 0.0
    pred = model_probability(features)
    error = target - pred
    lr = 0.04

    for k, v in features.items():
        if k not in model_state["feature_weights"]:
            continue
        old = model_state["feature_weights"][k]
        delta = lr * error * (float(v) - 0.5)
        model_state["feature_weights"][k] = clamp(old + delta, 0.35, 2.50)

    model_state["bias"] = clamp(model_state["bias"] + lr * error * 0.25, -2.5, 2.5)
    salvar_modelo()

def atualizar_pesos(features, win):
    online_update(features, win)

# ==========================
# TELEGRAM
# ==========================
def enviar(msg):
    try:
        if TOKEN == "COLOQUE_SEU_TOKEN_AQUI" or CHAT_ID == "COLOQUE_SEU_CHAT_ID_AQUI":
            log("Telegram não configurado.")
            return

        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": msg}
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code != 200:
            log(f"Erro Telegram: {r.status_code} | {r.text}")
    except Exception as e:
        log(f"Erro envio Telegram: {e}")

def remover_webhook():
    try:
        if TOKEN == "COLOQUE_SEU_TOKEN_AQUI":
            return
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"
        requests.get(url, timeout=10)
    except Exception:
        pass

def verificar_comandos():
    global LAST_UPDATE_ID, BOT_ATIVO

    if TOKEN == "COLOQUE_SEU_TOKEN_AQUI":
        return

    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
        params = {}
        if LAST_UPDATE_ID is not None:
            params["offset"] = LAST_UPDATE_ID + 1

        r = requests.get(url, params=params, timeout=15)
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
# DADOS DE MERCADO (YAHOO / YFINANCE)
# ==========================
def _symbol_key(asset):
    return asset["source"]

def bootstrap_symbol_history(symbol, limit=BOOTSTRAP_LIMIT):
    """
    Busca candles 1m do Yahoo Finance via yfinance.
    Para FX, os tickers vêm com sufixo =X (ex.: EURUSD=X).
    """
    t = yf.Ticker(symbol)
    df = t.history(period="1d", interval="1m", auto_adjust=False, actions=False)

    if df is None or df.empty:
        raise RuntimeError(f"Sem dados para {symbol}")

    # remove linhas sem OHLC válidos
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if df.empty:
        raise RuntimeError(f"Sem candles válidos para {symbol}")

    candles = deque(maxlen=300)
    for ts, row in df.tail(limit).iterrows():
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        candles.append({
            "time": ts.to_pydatetime(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0,
        })
    return candles

def init_market_data():
    global CANDLE_CACHE, CANDLE_CACHE_TIME, PRICE_CACHE
    for asset in ACTIVE_ASSETS:
        symbol = _symbol_key(asset)
        try:
            candles = bootstrap_symbol_history(symbol)
            CANDLE_CACHE[symbol] = list(candles)
            CANDLE_CACHE_TIME[symbol] = time.time()
            if candles:
                PRICE_CACHE[symbol] = (float(candles[-1]["close"]), time.time())
            log(f"Bootstrap ok: {asset['label']} ({len(candles)} candles)")
        except Exception as e:
            log(f"Bootstrap falhou {asset['label']}: {e}")
            CANDLE_CACHE[symbol] = []

def refresh_symbol_history(asset):
    symbol = _symbol_key(asset)
    now = time.time()
    last_ts = CANDLE_CACHE_TIME.get(symbol, 0.0)

    if now - last_ts < CACHE_SECONDS and symbol in CANDLE_CACHE:
        return

    try:
        candles = bootstrap_symbol_history(symbol)
        CANDLE_CACHE[symbol] = list(candles)
        CANDLE_CACHE_TIME[symbol] = now
        if candles:
            PRICE_CACHE[symbol] = (float(candles[-1]["close"]), now)
    except Exception as e:
        log(f"Refresh falhou {asset['label']}: {e}")

def get_candles(asset, limit=150):
    symbol = _symbol_key(asset)
    refresh_symbol_history(asset)
    data = CANDLE_CACHE.get(symbol, [])
    if not data:
        return None
    return data[-limit:] if len(data) > limit else list(data)

def get_price(asset):
    symbol = _symbol_key(asset)
    cached = PRICE_CACHE.get(symbol)
    if cached and (time.time() - cached[1] < CACHE_SECONDS):
        return float(cached[0])

    candles = get_candles(asset, limit=2)
    if candles:
        price = float(candles[-1]["close"])
        PRICE_CACHE[symbol] = (price, time.time())
        return price
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

def atr_like(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period

def volume_strength(candles, window=20):
    if len(candles) < window + 1:
        return None
    vols = [c["volume"] for c in candles]
    avg = sum(vols[-(window + 1):-1]) / window
    if avg <= 0:
        return None
    return vols[-1] / avg

# ==========================
# CONTEXTO
# ==========================
def market_regime(candles):
    closes = [c["close"] for c in candles]
    if len(closes) < 60:
        return "UNKNOWN"

    e9 = ema_last(closes, 9)
    e21 = ema_last(closes, 21)
    e50 = ema_last(closes, 50)
    if e9 is None or e21 is None or e50 is None:
        return "UNKNOWN"

    trend_strength = abs(e21 - e50) / closes[-1]
    slope = abs(e9 - ema_last(closes[:-3], 9)) / closes[-1] if len(closes) > 20 else 0.0

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
        return "breakout"
    if fib_zone in ("0.382", "near_0.382"):
        return "fib_38"
    if fib_zone in ("0.500", "near_0.500"):
        return "fib_50"
    if fib_zone in ("0.618", "near_0.618"):
        return "fib_62"
    if regime == "TREND" and trend_pct > 0.0008:
        return "trend_continuation"
    return "range_reversal" if regime != "TREND" else "trend_continuation"

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
    pattern = meta.get("pattern")

    mult = 1.0
    mult *= learning_multiplier(asset_id)
    mult *= hour_multiplier()
    mult *= regime_multiplier(regime)
    mult *= pattern_multiplier(pattern)
    return mult

# ==========================
# IA / SCORE
# ==========================
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

# ==========================
# ANÁLISE
# ==========================
def analisar_ativo(asset, candles):
    if not candles or len(candles) < 50:
        return None

    closes = [c["close"] for c in candles]
    price = closes[-1]

    e9 = ema_last(closes, 9)
    e21 = ema_last(closes, 21)
    rsi = rsi_last(closes, 14)
    atr_val = atr_like(candles, 14)
    vol_ratio = volume_strength(candles, 20)

    if e9 is None or e21 is None or rsi is None or atr_val is None:
        return None

    regime = market_regime(candles)
    direction = "BUY" if e9 > e21 else "SELL"
    fib_ctx = fib_analysis(candles, direction)

    trend_pct = abs(e9 - e21) / price
    last_move = abs(closes[-1] - closes[-2]) / closes[-2]
    atr_norm = atr_val / price
    vol_ratio = vol_ratio if vol_ratio is not None else 1.0

    # pullback simples
    if direction == "BUY":
        pullback_strength = 1.0 if candles[-2]["close"] < candles[-2]["open"] and candles[-1]["close"] > candles[-1]["open"] else 0.45
        rsi_alignment = clamp((rsi - 45) / 25, 0.0, 1.0)
    else:
        pullback_strength = 1.0 if candles[-2]["close"] > candles[-2]["open"] and candles[-1]["close"] < candles[-1]["open"] else 0.45
        rsi_alignment = clamp((55 - rsi) / 25, 0.0, 1.0)

    trend_strength = clamp(trend_pct / 0.0010, 0.0, 1.0)
    atr_strength = clamp(atr_norm / 0.00060, 0.0, 1.0)
    momentum_strength = clamp(last_move / 0.0015, 0.0, 1.0)
    wick_strength = 0.35 if liquidity_sweep(candles) else 1.0
    fib_confluence = fib_ctx["fib_score"]

    features = {
        "trend_strength": trend_strength,
        "rsi_alignment": rsi_alignment,
        "atr_strength": atr_strength,
        "pullback_strength": pullback_strength,
        "momentum_strength": momentum_strength,
        "wick_strength": wick_strength,
    }

    rule_score = (
        0.30 * trend_strength +
        0.22 * pullback_strength +
        0.16 * rsi_alignment +
        0.14 * atr_strength +
        0.10 * momentum_strength +
        0.08 * wick_strength
    )

    model_prob = model_probability(features)
    combined = (0.72 * rule_score) + (0.28 * model_prob)
    combined *= score_from_learning({
        "asset_id": asset["id"],
        "regime": regime,
        "fib_zone": fib_ctx["fib_zone"],
        "pattern": identificar_padrao({"regime": regime, "fib_zone": fib_ctx["fib_zone"], "trend_pct": trend_pct, "last_move": last_move}),
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
        "last_move": last_move,
        "features": features,
        "rule_score": rule_score,
        "model_prob": model_prob,
        "combined": combined,
        "pattern": identificar_padrao({"regime": regime, "fib_zone": fib_ctx["fib_zone"], "trend_pct": trend_pct, "last_move": last_move}),
    }

    return {
        "asset": asset,
        "direction": direction,
        "score": combined,
        "meta": meta,
    }

# ==========================
# HISTÓRICO / RESULTADOS
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

def maybe_send_learning_report(force=False):
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

    add_section("Melhores ativos", bucket_rank("asset_stats", True, limit=5))
    add_section("Ativos a evitar", bucket_rank("asset_stats", False, limit=5))
    add_section("Melhores horários", bucket_rank("hour_stats", True, limit=5))
    add_section("Melhores regimes", bucket_rank("regime_stats", True, limit=5))
    add_section("Melhores padrões", bucket_rank("pattern_stats", True, limit=5))

    lines.append("Pesos atuais:")
    for k, v in model_state["feature_weights"].items():
        lines.append(f"- {k}: {v:.2f}")
    lines.append(f"- bias: {model_state['bias']:.2f}")
    lines.append("")
    lines.append(f"Universo atual: {', '.join([a['label'] for a in ACTIVE_ASSETS])}")

    enviar("\n".join(lines))
    last_learning_report_time = now
    last_learning_report_trade_count = total_closed_trades

def report_learning_to_telegram(force=False):
    maybe_send_learning_report(force=force)

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
def avaliar_por_vela(asset, direcao):
    candles = get_candles(asset, limit=3)
    if not candles or len(candles) < 2:
        return None
    candle = candles[-2]  # última vela fechada
    entrada = candle["open"]
    saida = candle["close"]
    if direcao == "BUY":
        return saida > entrada
    return saida < entrada

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
# SELEÇÃO
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
        min_combined = 0.60
    elif adaptive_mode == "NORMAL":
        min_trend = 0.00065
        min_atr = 0.00035
        min_combined = 0.55
    else:
        min_trend = 0.00045
        min_atr = 0.00025
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
        if not candles or len(candles) < 50:
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
        regime = meta["regime"]
        fib_zone = meta["fib_zone"]
        model_prob = meta["model_prob"]
        rule_score = meta["rule_score"]

        if score > fallback_score:
            fallback_score = score
            fallback_asset = asset
            fallback_direcao = direction
            fallback_meta = meta

        reasons = []
        if trend_pct < min_trend:
            reasons.append(f"TREND {trend_pct:.6f}")
        if atr_norm < min_atr:
            reasons.append(f"ATR {atr_norm:.6f}")

        if reasons:
            if DEBUG_REJEICOES:
                log(f"{asset_label} -> REJECT ({', '.join(reasons)}) | score={score:.3f} | fib={fib_zone} | p={model_prob:.2f}")
            continue

        if DEBUG_REJEICOES:
            log(
                f"{asset_label} -> OK score={score:.3f} "
                f"regime={regime} fib={fib_zone} "
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
    entrada_time = next_timeframe(agora_utc) + timedelta(minutes=1)

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
        f"📊 Regime: {setup_pendente['meta'].get('regime', 'unknown')}\n"
        f"🧠 Padrão: {setup_pendente['meta'].get('pattern', 'unknown')}"
    )
    log(f"SINAL | {asset['label']} | {direcao} | {score:.3f}")

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
# MAIN
# ==========================
def main():
    global last_signal_time, last_universe_update

    if TOKEN == "COLOQUE_SEU_TOKEN_AQUI" or CHAT_ID == "COLOQUE_SEU_CHAT_ID_AQUI":
        log("ERRO: configure BOT_TOKEN e CHAT_ID nas variáveis de ambiente do Railway.")
        return

    carregar_modelo()
    remover_webhook()
    log("BOT INICIANDO...")

    init_market_data()
    log("Mercado inicial carregado.")

    enviar("🤖 BOT INICIADO COM SUCESSO")

    while True:
        try:
            verificar_comandos()

            if BOT_ATIVO:
                if last_universe_update is None or (utc_now() - last_universe_update).total_seconds() > UNIVERSE_REFRESH:
                    last_universe_update = utc_now()
                    log(f"Universo atualizado: {len(ACTIVE_ASSETS)} ativos")

                processar_setup_pendente()
                verificar_resultados()

                agora_utc = utc_now()

                if setup_pendente is None and not operacoes_ativas:
                    if last_signal_time is None or (agora_utc - last_signal_time).total_seconds() >= SIGNAL_INTERVAL:
                        asset, direcao, score, meta = escolher_melhor_ativo()
                        if asset:
                            criar_sinal(asset, direcao, score, meta)

                maybe_send_learning_report()

            time.sleep(POLL_SECONDS)

        except Exception as e:
            log(f"Erro geral: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
