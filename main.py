import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIGURAÇÕES
# ==========================
TOKEN = "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ"
CHAT_ID = "1056795017"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT"]
INTERVAL = "1m"

wins = 0
losses = 0

operacoes_ativas = []
setup_pendente = None

last_signal_time = None
SIGNAL_INTERVAL = 300  # 5 min

BR_TZ = timezone(timedelta(hours=-3))

# Performance (ML simples)
performance = {
    "BTCUSDT": {"win": 0, "loss": 0},
    "ETHUSDT": {"win": 0, "loss": 0},
    "XRPUSDT": {"win": 0, "loss": 0},
    "SOLUSDT": {"win": 0, "loss": 0},
    "ADAUSDT": {"win": 0, "loss": 0},
}

# ==========================
# TEMPO
# ==========================
def utc_now():
    return datetime.now(timezone.utc)

def br_now():
    return utc_now().astimezone(BR_TZ)

def next_minute(dt):
    return dt.replace(second=0, microsecond=0) + timedelta(minutes=1)

def fmt_br(dt):
    return dt.astimezone(BR_TZ).strftime("%H:%M")

# ==========================
# TELEGRAM
# ==========================
def enviar(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ==========================
# COMANDOS
# ==========================
LAST_UPDATE_ID = None
BOT_ATIVO = False

def verificar_comandos():
    global LAST_UPDATE_ID, BOT_ATIVO

    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
        params = {}

        if LAST_UPDATE_ID:
            params["offset"] = LAST_UPDATE_ID + 1

        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        for update in data.get("result", []):
            LAST_UPDATE_ID = update["update_id"]

            msg = update.get("message", {})
            text = msg.get("text", "").strip()

            if text == "/start":
                BOT_ATIVO = True
                enviar("🟢 BOT ATIVADO")

            elif text == "/stop":
                BOT_ATIVO = False
                enviar("🔴 BOT PARADO")

    except Exception as e:
        print("comandos error:", e)

# ==========================
# KUCOIN
# ==========================
def to_symbol(s):
    return s.replace("USDT", "-USDT")

def get_candles(symbol, limit=120):
    try:
        url = "https://api.kucoin.com/api/v1/market/candles"
        params = {"type": "1min", "symbol": to_symbol(symbol)}

        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        rows = data.get("data", [])
        candles = []

        for row in reversed(rows[-limit:]):
            candles.append({
                "time": datetime.fromtimestamp(int(float(row[0])), tz=timezone.utc),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
            })

        return candles

    except Exception as e:
        print("candles error:", e)
        return None

# ==========================
# INDICADORES
# ==========================
def ema(prices, period):
    if len(prices) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period

    for p in prices[period:]:
        ema_val = (p - ema_val) * k + ema_val

    return ema_val

def rsi(prices, period=14):
    if len(prices) < period + 1:
        return None

    gains, losses = 0, 0

    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)

    if losses == 0:
        return 100

    rs = gains / losses
    return 100 - (100 / (1 + rs))

def adx_simple(closes):
    if len(closes) < 20:
        return 0

    tr = sum(abs(closes[i] - closes[i-1]) for i in range(1, len(closes)))
    return tr / len(closes)

def atr(closes):
    return sum(abs(closes[i] - closes[i-1]) for i in range(-14, -1)) / 14

# ==========================
# REGIME DE MERCADO
# ==========================
def market_regime(closes):
    if len(closes) < 60:
        return "UNKNOWN"

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)

    slope = abs(ema9 - ema(closes[:-10], 9))

    if abs(ema9 - ema21) / closes[-1] < 0.0015:
        return "RANGE"

    if slope < closes[-1] * 0.0003:
        return "CHOP"

    return "TREND"

# ==========================
# SMART MONEY (LIQUIDITY SWEEP)
# ==========================
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

# ==========================
# SESSÃO
# ==========================
def session_filter():
    h = br_now().hour
    if 1 <= h <= 6:
        return False
    return True

# ==========================
# PERFORMANCE ML
# ==========================
def asset_multiplier(symbol):
    data = performance.get(symbol, {"win": 1, "loss": 1})
    total = data["win"] + data["loss"]

    if total < 10:
        return 1

    winrate = data["win"] / total

    if winrate > 0.65:
        return 1.2
    if winrate < 0.4:
        return 0.7

    return 1

# ==========================
# MELHOR ATIVO
# ==========================
def escolher():
    best = None
    best_score = -999

    for s in SYMBOLS:
        candles = get_candles(s)
        if not candles:
            continue

        closes = [c["close"] for c in candles]

        e9 = ema(closes, 9)
        e21 = ema(closes, 21)
        rsi_val = rsi(closes)
        adx_val = adx_simple(closes)

        if not e9 or not e21 or not rsi_val:
            continue

        if not session_filter():
            continue

        if liquidity_sweep(candles):
            continue

        regime = market_regime(closes)
        if regime != "TREND":
            continue

        atr_val = atr(closes)
        if atr_val < closes[-1] * 0.0009:
            continue

        if e9 > e21 and rsi_val >= 55:
            direction = "BUY"
        elif e9 < e21 and rsi_val <= 45:
            direction = "SELL"
        else:
            continue

        score = (abs(e9 - e21) * 2) + (abs(rsi_val - 50)) + adx_val

        score *= asset_multiplier(s)

        if score > best_score:
            best_score = score
            best = (s, direction, score)

    return best

# ==========================
# SINAL
# ==========================
def criar_signal(symbol, direction, score):
    global setup_pendente, last_signal_time

    entry = next_minute(utc_now()) + timedelta(minutes=2)

    setup_pendente = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "score": score
    }

    last_signal_time = utc_now()

    enviar(f"""
⚠️ PREPARAR ENTRADA

Ativo: {symbol}
Direção: {direction}
Entrada: {fmt_br(entry)}
Força: {round(score,2)}
""")

# ==========================
# LOOP
# ==========================
def main():
    global setup_pendente

    enviar("🤖 BOT 2.0 INSTITUCIONAL ONLINE")

    while True:
        try:
            verificar_comandos()

            if not BOT_ATIVO:
                time.sleep(5)
                continue

            if setup_pendente is None:
                result = escolher()
                if result:
                    criar_signal(*result)

            time.sleep(10)

        except Exception as e:
            print("loop error:", e)
            time.sleep(5)

if __name__ == "__main__":
    main()
