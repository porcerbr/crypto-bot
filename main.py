import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIG
# ==========================

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]

EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50

RSI_PERIOD = 14
ATR_PERIOD = 14

CHECK_INTERVAL = 60
SIGNAL_INTERVAL = 300          # 5 minutos entre sinais
MIN_SCORE = 40                 # ajuste para mais/menos oportunidades

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BOT_ATIVO = False
LAST_UPDATE_ID = None

wins = 0
losses = 0

last_signal_time_global = None
pending_ops = []  # cada item: symbol, direction, score, prepared_at, confirm_at, entry_at, result_at, entry_price, confirmed, entry_captured


# ==========================
# LOG
# ==========================

def log(msg: str) -> None:
    now = datetime.now(timezone.utc) - timedelta(hours=3)
    print(f"[{now.strftime('%H:%M:%S')}] {msg}", flush=True)


# ==========================
# HORÁRIO BR
# ==========================

def agora():
    return datetime.now(timezone.utc) - timedelta(hours=3)


# ==========================
# TELEGRAM
# ==========================

def enviar(msg: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=15)
        log("Telegram enviado")
    except Exception as e:
        log(f"Erro Telegram: {e}")


def verificar_comandos() -> None:
    global BOT_ATIVO, LAST_UPDATE_ID

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        params = {"timeout": 0}

        if LAST_UPDATE_ID is not None:
            params["offset"] = LAST_UPDATE_ID + 1

        response = requests.get(url, params=params, timeout=15)
        data = response.json()

        for update in data.get("result", []):
            LAST_UPDATE_ID = update["update_id"]

            message = update.get("message")
            if not message:
                continue

            texto = message.get("text", "").strip()

            if texto == "/start":
                if not BOT_ATIVO:
                    BOT_ATIVO = True
                    enviar("🟢 BOT ATIVADO")
                    log("BOT ATIVADO por comando /start")

            elif texto == "/stop":
                if BOT_ATIVO:
                    BOT_ATIVO = False
                    enviar("🔴 BOT PARADO")
                    log("BOT PARADO por comando /stop")

            elif texto == "/status":
                status = "ATIVO" if BOT_ATIVO else "PARADO"
                enviar(f"📊 STATUS: {status}")
                log(f"Status solicitado: {status}")

    except Exception as e:
        log(f"Erro comandos: {e}")


# ==========================
# DADOS DE MERCADO
# ==========================

def get_data(symbol):
    try:
        url = "https://data-api.binance.vision/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 100}

        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if isinstance(data, dict):
            log(f"Erro dados {symbol}: {data}")
            return None, None, None

        closes = [float(c[4]) for c in data]
        highs = [float(c[2]) for c in data]
        lows = [float(c[3]) for c in data]

        return closes, highs, lows

    except Exception as e:
        log(f"Erro dados {symbol}: {e}")
        return None, None, None


def get_price(symbol):
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        params = {"symbol": symbol}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()

        if isinstance(data, dict) and "price" in data:
            return float(data["price"])

        log(f"Erro preço {symbol}: {data}")
        return None

    except Exception as e:
        log(f"Erro preço {symbol}: {e}")
        return None


# ==========================
# INDICADORES
# ==========================

def ema(prices, period):
    if len(prices) < period:
        return None

    k = 2 / (period + 1)
    e = sum(prices[:period]) / period

    for p in prices[period:]:
        e = (p - e) * k + e

    return e


def rsi(prices):
    if len(prices) < RSI_PERIOD + 1:
        return None

    gains = []
    losses = []

    for i in range(1, RSI_PERIOD + 1):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains) / RSI_PERIOD
    avg_loss = sum(losses) / RSI_PERIOD

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(highs, lows):
    if len(highs) < ATR_PERIOD or len(lows) < ATR_PERIOD:
        return None

    trs = []
    for i in range(1, ATR_PERIOD):
        trs.append(highs[i] - lows[i])

    if not trs:
        return None

    return sum(trs) / len(trs)


# ==========================
# SINAIS
# ==========================

def analisar_ativos():
    """
    Retorna o melhor ativo do momento:
    {
        symbol, direction, score, e9, e21, e50, rsi, atr, price
    }
    """

    melhor = None

    log("BOT ATIVO - analisando ativos")

    for symbol in SYMBOLS:
        closes, highs, lows = get_data(symbol)
        if not closes:
            continue

        e9 = ema(closes, EMA_FAST)
        e21 = ema(closes, EMA_SLOW)
        e50 = ema(closes, EMA_TREND)
        r = rsi(closes)
        vol = atr(highs, lows)

        if None in (e9, e21, e50, r, vol):
            log(f"{symbol} | indicadores insuficientes")
            continue

        price = closes[-1]
        momentum = closes[-1] - closes[-2]
        distancia = abs(e9 - e21)
        vol_rel = (vol / price) * 100 if price else 0

        # score de compra e venda
        buy_score = 0
        sell_score = 0

        if e9 > e21:
            buy_score += 25
        else:
            sell_score += 25

        if e21 > e50:
            buy_score += 15
        else:
            sell_score += 15

        if r >= 55:
            buy_score += 20
        elif r <= 45:
            sell_score += 20
        else:
            buy_score += 10
            sell_score += 10

        if momentum > 0:
            buy_score += 10
        else:
            sell_score += 10

        if vol_rel >= 0.10:
            buy_score += 10
            sell_score += 10

        if distancia >= 0.04:
            buy_score += 5
            sell_score += 5

        direction = "BUY" if buy_score >= sell_score else "SELL"
        score = max(buy_score, sell_score)

        log(
            f"{symbol} | "
            f"EMA9:{e9:.4f} EMA21:{e21:.4f} EMA50:{e50:.4f} "
            f"RSI:{r:.1f} ATR:{vol:.4f} "
            f"Score:{score} Dir:{direction}"
        )

        candidate = {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "e9": e9,
            "e21": e21,
            "e50": e50,
            "rsi": r,
            "atr": vol,
            "price": price,
        }

        if melhor is None or candidate["score"] > melhor["score"]:
            melhor = candidate

    return melhor


def preparar_msg(item):
    entrada = item["prepared_at"] + timedelta(minutes=2)
    emoji = "🟢 COMPRA" if item["direction"] == "BUY" else "🔴 VENDA"

    return (
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 Ativo: {item['symbol']}\n"
        f"⏳ Expiração: M1\n"
        f"📊 Estratégia: {emoji}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}\n"
        f"⭐ Score: {item['score']}"
    )


def confirmacao_msg(item):
    entrada = item["prepared_at"] + timedelta(minutes=2)
    p1 = entrada + timedelta(minutes=1)
    p2 = entrada + timedelta(minutes=2)
    emoji = "🟢 COMPRA" if item["direction"] == "BUY" else "🔴 VENDA"

    return (
        "✅ ENTRADA CONFIRMADA ✅\n\n"
        f"🌎 Ativo: {item['symbol']}\n"
        f"⏳ Expiração: M1\n"
        f"📊 Estratégia: {emoji}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}\n\n"
        f"⚠️ Proteção 1: {p1.strftime('%H:%M')}\n"
        f"⚠️ Proteção 2: {p2.strftime('%H:%M')}\n"
        f"⭐ Score: {item['score']}"
    )


def resultado_msg(item, resultado, wins_count, losses_count):
    emoji = "✅ WIN" if resultado == "WIN" else "❌ LOSS"
    total = wins_count + losses_count
    taxa = (wins_count / total) * 100 if total else 0

    return (
        "🏆 RESULTADO\n\n"
        f"🌎 Ativo: {item['symbol']}\n"
        f"📊 Resultado: {emoji}\n\n"
        f"Wins: {wins_count}\n"
        f"Loss: {losses_count}\n"
        f"Precisão: {taxa:.1f}%"
    )


def registrar_sinal(item):
    global last_signal_time_global, pending_ops

    now = agora()

    entry = {
        "symbol": item["symbol"],
        "direction": item["direction"],
        "score": item["score"],
        "prepared_at": now,
        "confirm_at": now + timedelta(minutes=1),
        "entry_at": now + timedelta(minutes=2),
        "result_at": now + timedelta(minutes=5),
        "entry_price": None,
        "confirmed": False,
        "entry_logged": False,
        "done": False,
    }

    pending_ops.append(entry)
    last_signal_time_global = now

    enviar(preparar_msg(entry))
    log(f"PREPARAR enviado: {entry['symbol']} {entry['direction']} score={entry['score']}")


# ==========================
# WIN / LOSS
# ==========================

def verificar_resultados():
    global wins, losses, pending_ops

    now = agora()
    restantes = []

    for op in pending_ops:
        try:
            if not op["confirmed"] and now >= op["confirm_at"]:
                enviar(confirmacao_msg(op))
                op["confirmed"] = True
                log(f"CONFIRMAÇÃO enviada: {op['symbol']}")

            if op["confirmed"] and not op["entry_logged"] and now >= op["entry_at"]:
                preco = get_price(op["symbol"])
                if preco is None:
                    restantes.append(op)
                    continue

                op["entry_price"] = preco
                op["entry_logged"] = True
                log(f"Entrada registrada: {op['symbol']} preço={preco:.6f}")

            if op["entry_logged"] and now >= op["result_at"]:
                preco_atual = get_price(op["symbol"])
                if preco_atual is None:
                    restantes.append(op)
                    continue

                if op["direction"] == "BUY":
                    resultado = "WIN" if preco_atual > op["entry_price"] else "LOSS"
                else:
                    resultado = "WIN" if preco_atual < op["entry_price"] else "LOSS"

                if resultado == "WIN":
                    wins += 1
                else:
                    losses += 1

                enviar(resultado_msg(op, resultado, wins, losses))
                log(
                    f"RESULTADO {resultado}: {op['symbol']} "
                    f"entrada={op['entry_price']:.6f} atual={preco_atual:.6f}"
                )
                op["done"] = True
                continue

            if not op["done"]:
                restantes.append(op)

        except Exception as e:
            log(f"Erro ao verificar operação {op.get('symbol')}: {e}")
            restantes.append(op)

    pending_ops = restantes


# ==========================
# MAIN
# ==========================

def main():
    global BOT_ATIVO, last_signal_time_global

    enviar("🤖 BOT ATIVO. Use /start, /stop e /status.")
    log("BOT iniciado")

    while True:
        verificar_comandos()
        verificar_resultados()

        if BOT_ATIVO:
            log("BOT ATIVO - varredura iniciada")

            agora_time = agora()
            pode_enviar = False

            if last_signal_time_global is None:
                pode_enviar = True
            else:
                elapsed = (agora_time - last_signal_time_global).total_seconds()
                if elapsed >= SIGNAL_INTERVAL:
                    pode_enviar = True

            if pode_enviar and not pending_ops:
                melhor = analisar_ativos()

                if melhor and melhor["score"] >= MIN_SCORE:
                    registrar_sinal(melhor)
                else:
                    log("Nenhuma oportunidade forte encontrada neste ciclo")
            else:
                if pending_ops:
                    log("Aguardando conclusão da operação anterior")
                else:
                    log("Cooldown ativo aguardando próxima janela")

        else:
            log("BOT PARADO - aguardando /start")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
