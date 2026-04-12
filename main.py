import os
import time
import requests
from datetime import datetime, timedelta, timezone

# ========== Configurações ==========
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]
EMA_FAST = 9      # Período da EMA rápida
EMA_SLOW = 21     # Período da EMA lenta
RSI_PERIOD = 14   # Período do RSI
SIGNAL_INTERVAL = 300  # Intervalo mínimo entre sinais (segundos)

# Variáveis de ambiente (configurar TELEGRAM_BOT_TOKEN e CHAT_ID)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Variáveis de controle
BOT_ATIVO = False
LAST_UPDATE_ID = None
last_signal_time = None  # hora do último sinal enviado

# Estatísticas de performance
wins = 0
losses = 0
operacoes_ativas = []  # Lista de operações pendentes (WIN/LOSS futuro)

# ========== Auxiliares de Data/Hora ==========
def agora():
    """Retorna o horário atual em horário de Brasília (UTC-3)."""
    return datetime.now(timezone.utc) - timedelta(hours=3)

# ========== Telegram API ==========
def enviar(msg):
    """Envia uma mensagem de texto ao chat do Telegram via sendMessage."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg})
        print("[Telegram] Mensagem enviada")
    except Exception as e:
        print("Erro ao enviar Telegram:", e)

def verificar_comandos():
    """Verifica comandos /start e /stop via getUpdates de forma robusta (offset)."""
    global BOT_ATIVO, LAST_UPDATE_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        params = {}
        if LAST_UPDATE_ID:
            params["offset"] = LAST_UPDATE_ID + 1
        data = requests.get(url, params=params).json()
        for update in data["result"]:
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

# ========== Binance API ==========
def get_data(symbol):
    """Obtém os preços de fechamento dos últimos 50 candles de 1m do símbolo."""
    try:
        url = "https://data-api.binance.vision/api/v3/klines"
        params = {"symbol": symbol, "interval": "1m", "limit": 50}
        data = requests.get(url, params=params).json()
        return [float(candle[4]) for candle in data]  # lista de preços de fechamento
    except Exception as e:
        print(f"Erro ao obter dados de {symbol}:", e)
        return None

def get_price(symbol):
    """Obtém o preço atual (ticker) do símbolo via Binance API【11†L642-L648】."""
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        params = {"symbol": symbol}
        data = requests.get(url, params=params).json()
        return float(data["price"])
    except:
        return None

# ========== Indicadores Técnicos ==========
def ema(prices, period):
    """Calcula média móvel exponencial (EMA) simples para os últimos preços."""
    k = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period
    for price in prices[period:]:
        ema_val = (price - ema_val) * k + ema_val
    return ema_val

def rsi(prices):
    """Calcula RSI baseado nas variações dos preços de fechamento."""
    gains, losses = [], []
    for i in range(1, RSI_PERIOD+1):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains)/RSI_PERIOD
    avg_loss = sum(losses)/RSI_PERIOD
    if avg_loss == 0:
        return 100
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))

# ========== Lógica de Escolha do Ativo ==========
def escolher_ativo():
    """
    Escolhe o ativo com maior "força de tendência" baseada na diferença EMA9-EMA21.
    Retorna (símbolo, direção). Se EMA9>EMA21 => BUY, senão SELL.
    """
    melhor_symbol = None
    melhor_score = 0
    melhor_direcao = None
    for symbol in SYMBOLS:
        closes = get_data(symbol)
        if not closes:
            continue
        e9 = ema(closes, EMA_FAST)
        e21 = ema(closes, EMA_SLOW)
        # Força da tendência = |EMA9 - EMA21|
        score = abs(e9 - e21)
        direcao = "BUY" if e9 > e21 else "SELL"
        if score > melhor_score:
            melhor_score = score
            melhor_symbol = symbol
            melhor_direcao = direcao
    return melhor_symbol, melhor_direcao

# ========== Gerenciamento de Resultados ==========
def verificar_resultados():
    """Verifica operações finalizadas e atualiza WIN/LOSS e estatísticas."""
    global wins, losses
    agora_time = agora()
    pendentes = []
    for op in operacoes_ativas:
        if agora_time >= op["tempo_resultado"]:
            print(f"Verificando resultado de {op['symbol']}")
            preco_atual = get_price(op["symbol"])
            if preco_atual is None:
                pendentes.append(op)
                continue
            preco_entrada = op["preco"]
            direcao = op["direcao"]
            if direcao == "BUY":
                if preco_atual > preco_entrada:
                    wins += 1
                    res = "WIN"
                else:
                    losses += 1
                    res = "LOSS"
            else:
                if preco_atual < preco_entrada:
                    wins += 1
                    res = "WIN"
                else:
                    losses += 1
                    res = "LOSS"
            total = wins + losses
            taxa = (wins/total)*100
            enviar(
                "🏆 RESULTADO\n\n"
                f"🌎 {op['symbol']}\n"
                f"{'✅ WIN' if res=='WIN' else '❌ LOSS'}\n\n"
                f"Wins: {wins}\n"
                f"Loss: {losses}\n"
                f"Precisão: {round(taxa,1)}%"
            )
        else:
            pendentes.append(op)
    operacoes_ativas.clear()
    operacoes_ativas.extend(pendentes)

# ========== Criação de Sinal ==========
def criar_sinal(symbol, direcao):
    """Registra operação futura e envia mensagens PREPARAR e CONFIRMAR."""
    global last_signal_time
    agora_time = agora()
    entrada = agora_time + timedelta(minutes=2)   # tempo do candle de entrada
    resultado = entrada + timedelta(minutes=3)   # 3 minutos após entrada
    preco = get_price(symbol)
    if preco is None:
        return
    # Registra operação pendente para WIN/LOSS
    operacoes_ativas.append({
        "symbol": symbol,
        "direcao": direcao,
        "preco": preco,
        "tempo_resultado": resultado
    })
    last_signal_time = agora_time
    emoji = "🟢 COMPRA" if direcao == "BUY" else "🔴 VENDA"
    # Mensagem de aviso antecipado (2 min antes)
    enviar(
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"🌎 {symbol}\n"
        f"{emoji}\n"
        f"⏰ Entrada prevista: {entrada.strftime('%H:%M')}"
    )

# ========== Loop Principal ==========
def main():
    enviar("🤖 BOT DE SINAIS ATIVO")
    while True:
        verificar_comandos()
        verificar_resultados()
        if BOT_ATIVO:
            agora_time = agora()
            pode_enviar = False
            # Controle para evitar enviar sinais em intervalos menores que SIGNAL_INTERVAL
            if last_signal_time is None:
                pode_enviar = True
            else:
                tempo = (agora_time - last_signal_time).seconds
                if tempo >= SIGNAL_INTERVAL:
                    pode_enviar = True
            # Se ok, escolhe o melhor ativo e envia sinal
            if pode_enviar:
                symbol, direcao = escolher_ativo()
                if symbol:
                    criar_sinal(symbol, direcao)
        time.sleep(1)  # Espera 1 segundo no loop para reagir rápido a comandos

if __name__ == "__main__":
    main()
