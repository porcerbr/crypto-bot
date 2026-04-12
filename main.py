import os
import time
import json
import requests
from datetime import datetime, timedelta, timezone

# ==========================
# CONFIGURAÇÃO
# ==========================
SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","XRPUSDT"]
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50  # (opcional, não usado no sinal principal)
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_MIN = 0.0          # Minimo ATR para filtrar (0 desabilita)
SIGNAL_INTERVAL = 300  # Intervalo global mínimo entre sinais (segundos)

# Variáveis de ambiente (definir em Railway ou .env)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BOT_ATIVO = False
LAST_UPDATE_ID = None
last_signal_time = None

# Estatísticas de resultados
wins = 0
losses = 0
# Operações pendentes (para WIN/LOSS futuro)
operacoes_ativas = []

# ==========================
# UTILITÁRIOS
# ==========================
def agora():
    """Retorna o horário atual (BR horário, UTC-3)."""
    return datetime.now(timezone.utc) - timedelta(hours=3)

# ==========================
# TELEGRAM API
# ==========================
def enviar(msg):
    """Envia uma mensagem via Telegram Bot API (sendMessage)【6†L4101-L4109】."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg})
        print("[Telegram] Mensagem enviada")
    except Exception as e:
        print("Erro Telegram:", e)

def verificar_comandos():
    """Verifica comandos /start e /stop usando getUpdates (polling com offset)."""
    global BOT_ATIVO, LAST_UPDATE_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        params = {}
        if LAST_UPDATE_ID:
            params["offset"] = LAST_UPDATE_ID + 1
        data = requests.get(url, params=params).json()
        for update in data.get("result", []):
            LAST_UPDATE_ID = update["update_id"]
            if "message" not in update: 
                continue
            texto = update["message"].get("text", "")
            if texto == "/start":
                BOT_ATIVO = True
                enviar("🟢 BOT ATIVADO")
            elif texto == "/stop":
                BOT_ATIVO = False
                enviar("🔴 BOT PARADO")
    except Exception as e:
        print("Erro em getUpdates:", e)

# ==========================
# BINANCE API
# ==========================
def get_data(symbol):
    """
    Retorna listas [fechamento], [high], [low] dos últimos 50 candles de 1m.
    Usa `/api/v3/klines`【14†L196-L203】.
    """
    try:
        print(f"Buscando candles de {symbol}")
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 50}
        data = requests.get(url, params=params).json()
        closes = [float(c[4]) for c in data]
        highs  = [float(c[2]) for c in data]
        lows   = [float(c[3]) for c in data]
        return closes, highs, lows
    except Exception as e:
        print(f"Erro dados {symbol}:", e)
        return None, None, None

 def get_price(symbol):
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        price = requests.get(url, params={"symbol":symbol}).json().get("price")
        if price: 
            return float(price)
    except:
        pass
    try:
        url = "https://api.binance.com/api/v3/ticker/bookTicker"
        data = requests.get(url, params={"symbol":symbol}).json()
        bid = float(data.get("bidPrice",0))
        ask = float(data.get("askPrice",0))
        return (bid+ask)/2 if bid and ask else None
    except Exception as e:
        print(f"Erro fallback preço {symbol}: {e}")
        return None

# ==========================
# INDICADORES TÉCNICOS
# ==========================
def ema(prices, period):
    """Calcula EMA do último preço."""
    k = 2/(period+1)
    e = sum(prices[:period]) / period
    for p in prices[period:]:
        e = (p - e)*k + e
    return e

def rsi(prices):
    """Calcula RSI último (período RSI_PERIOD)."""
    gains, losses = [], []
    for i in range(1, RSI_PERIOD+1):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains)/RSI_PERIOD
    avg_loss = sum(losses)/RSI_PERIOD
    if avg_loss == 0: return 100
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

def atr(highs, lows):
    """Calcula ATR simples (últimos ATR_PERIOD candles)."""
    if ATR_PERIOD >= len(highs): return 0
    trs = [h - l for h, l in zip(highs[1:], lows[1:])]
    return sum(trs[-ATR_PERIOD:]) / ATR_PERIOD

# ==========================
# LÓGICA DO SINAL
# ==========================
def escolher_ativo():
    """
    Escolhe ativo de maior tendência (|EMA9-EMA21|) e define direção.
    Retorna (symbol, direcao) ou (None, None) se falhar.
    """
    melhor_score = 0
    melhor_symbol = None
    direcao = None
    for symbol in SYMBOLS:
        closes, highs, lows = get_data(symbol)
        if not closes:
            continue
        # Filtrar ATR opcional
        if ATR_MIN > 0:
            vol = atr(highs, lows)
            if vol < ATR_MIN:
                print(f"{symbol} atolado (ATR={vol:.3f})")
                continue
        e9 = ema(closes, EMA_FAST)
        e21 = ema(closes, EMA_SLOW)
        score = abs(e9 - e21)
        if score > melhor_score:
            melhor_score = score
            melhor_symbol = symbol
            direcao = "BUY" if e9 > e21 else "SELL"
    return melhor_symbol, direcao

def criar_sinal(symbol, direcao):
    """
    Registra operação e envia mensagens PREPARAR e CONFIRMAR.
    Entrada em +2min, Proteções +1min/+2min.
    """
    global last_signal_time

    agora_time = agora()
    entrada = agora_time + timedelta(minutes=2)
    protecao1 = entrada + timedelta(minutes=1)
    protecao2 = entrada + timedelta(minutes=2)
    resultado = entrada + timedelta(minutes=3)

    preco = get_price(symbol)
    if preco is None:
        print(f"Falha ao obter preço de {symbol}")
        return

    # Registra operação para verificação futura
    operacoes_ativas.append({
        "symbol": symbol,
        "direcao": direcao,
        "preco": preco,
        "tempo_resultado": resultado
    })
    last_signal_time = agora_time

    estrategia = "🟢 COMPRA" if direcao=="BUY" else "🔴 VENDA"
    # Enviar alerta 2 min antes
    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 Ativo: {symbol}\n"
        f"📊 Estratégia: {estrategia}\n"
        f"⏰ Entrada prevista: {entrada.strftime('%H:%M')}"
    )
    time.sleep(60)
    # Enviar confirmação 1 min antes
    enviar(
        "✅ ENTRADA CONFIRMADA ✅\n\n"
        f"🌎 Ativo: {symbol}\n"
        f"📊 Estratégia: {estrategia}\n"
        f"⏰ Entrada: {entrada.strftime('%H:%M')}\n\n"
        f"⚠️ Proteção1: {protecao1.strftime('%H:%M')}\n"
        f"⚠️ Proteção2: {protecao2.strftime('%H:%M')}"
    )

def verificar_resultados():
    """Verifica operações concluídas e envia resultados (WIN/LOSS)."""
    global wins, losses
    agora_time = agora()
    pendentes = []
    for op in operacoes_ativas:
        if agora_time >= op["tempo_resultado"]:
            preco_atual = get_price(op["symbol"])
            if preco_atual is None:
                pendentes.append(op)
                continue
            if op["direcao"] == "BUY":
                ganhou = (preco_atual > op["preco"])
            else:
                ganhou = (preco_atual < op["preco"])
            if ganhou:
                wins += 1
                res = "WIN"
            else:
                losses += 1
                res = "LOSS"
            total = wins + losses
            taxa = (wins/total)*100 if total>0 else 0
            enviar(
                "🏆 RESULTADO\n\n"
                f"🌎 {op['symbol']}\n"
                f"{'✅ WIN' if res=='WIN' else '❌ LOSS'}\n\n"
                f"Wins: {wins}\n"
                f"Losses: {losses}\n"
                f"Precisão: {taxa:.1f}%"
            )
            # Gravar histórico em JSON
            entry = {
                "time": agora_time.strftime("%Y-%m-%d %H:%M"),
                "symbol": op["symbol"],
                "direcao": op["direcao"],
                "resultado": res,
                "price": op["preco"]
            }
            try:
                with open("history.json","a") as f:
                    f.write(json.dumps(entry)+"\n")
            except Exception as e:
                print("Erro ao salvar histórico:", e)
        else:
            pendentes.append(op)
    operacoes_ativas[:] = pendentes

# ==========================
# LOOP PRINCIPAL
# ==========================
def main():
    enviar("🤖 BOT INICIADO")
    while True:
        verificar_comandos()
        verificar_resultados()
        if BOT_ATIVO:
            agora_time = agora()
            pode_enviar = False
            if last_signal_time is None:
                pode_enviar = True
            else:
                if (agora_time - last_signal_time).seconds >= SIGNAL_INTERVAL:
                    pode_enviar = True
            if pode_enviar:
                symbol, direcao = escolher_ativo()
                if symbol and direcao:
                    criar_sinal(symbol, direcao)
        time.sleep(1)

if __name__ == "__main__":
    main()
