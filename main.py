# -*- coding: utf-8 -*-
import os
import time
import requests
import json
from datetime import datetime, timedelta, timezone

# ========================================
# CONFIGURAÇÕES - VERIFIQUE O CHAT_ID
# ========================================
class Config:
    BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID = "1056795017" 
    BR_TIMEZONE = timezone(timedelta(hours=-3))
    
    FOREX_ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS = ["BTC-USD", "ETH-USD", "SOL-USD"]
    THRESHOLD = 1.5
    CHECK_TIME = 15

def log(msg):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ========================================
# FUNÇÕES DE MERCADO
# ========================================

def get_analysis(symbol):
    import yfinance as yf
    import pandas as pd
    yf_symbol = f"{symbol}=X" if "-" not in symbol and "JPY" not in symbol else symbol
    if "JPY" in symbol and "=" not in symbol: yf_symbol = f"{symbol}=X"
    try:
        # 1. Mudança para o gráfico de 5 minutos (menos falsos sinais)
        df = yf.Ticker(yf_symbol).history(period="5d", interval="5m")
        if df.empty: return None
        
        closes = df['Close']
        
        # 2. Cálculo do RSI (Impede comprar no topo e vender no fundo)
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]

        # 3. Cálculo das Médias e Score
        ema9 = closes.tail(9).mean()
        ema21 = closes.tail(21).mean()
        diff = ema9 - ema21
        std = closes.std()
        score = abs(diff / std) * 10 if std > 0 else 0
        
        # 4. A TRAVA DE SEGURANÇA:
        # Só COMPRA se o RSI estiver abaixo de 70.
        # Só VENDE se o RSI estiver acima de 30.
        direction = None
        simple_dir = None
        
        if diff > 0 and current_rsi < 70:
            direction, simple_dir = "BUY 🟢", "BUY"
        elif diff < 0 and current_rsi > 30:
            direction, simple_dir = "SELL 🔴", "SELL"
            
        # Se as médias deram sinal, mas o RSI bloqueou, ele aborta e não envia nada.
        if direction is None: 
            return None 
        
        return {
            "symbol": symbol, 
            "price": closes.iloc[-1], 
            "score": score, 
            "dir": direction, 
            "simple": simple_dir
        }
    except Exception as e: 
        return None


# ========================================
# CLASSE DO BOT
# ========================================
class TradingBot:
    def __init__(self):
        self.mode = "FOREX"
        self.wins = 0
        self.losses = 0
        self.trades = []
        self.last_id = 0

    def send_msg(self, text, markup=None):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML"}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try:
            r = requests.post(url, json=payload, timeout=5)
            return r.json()
        except Exception as e:
            log(f"Erro ao enviar: {e}")
            return None

    def build_menu(self):
        markup = {"inline_keyboard": [
            [{"text": f"📍 Mercado: {self.mode}", "callback_data": "ignore"}],
            [{"text": "📈 FOREX", "callback_data": "set_fx"}, {"text": "₿ CRIPTO", "callback_data": "set_crypto"}],
            [{"text": "🏆 VER RANKING", "callback_data": "get_rank"}],
            [{"text": "🔄 ATUALIZAR", "callback_data": "refresh"}]
        ]}
        msg = f"<b>🎛 DASHBOARD ATIVO</b>\nPlacar: {self.wins}W - {self.losses}L\nModo: {self.mode}"
        self.send_msg(msg, markup)

# ========================================
# LOOP PRINCIPAL COM RESET
# ========================================
def main():
    log("🔌 Tentando conexão com Telegram...")
    
    # RESET DE SEGURANÇA: Deleta qualquer webhook antigo que possa estar travando o bot
    requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook")
    
    bot = TradingBot()
    # Mensagem de teste para saber se o Token está certo
    teste = bot.send_msg("🔌 <b>Bot Conectado!</b>\nSe você está lendo isso, a comunicação está OK.")
    
    if teste and not teste.get("ok"):
        log(f"❌ ERRO NO TOKEN: {teste.get('description')}")
        return

    bot.build_menu()

    while True:
        try:
            # Puxa atualizações
            url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates?offset={bot.last_id + 1}&timeout=20"
            r = requests.get(url, timeout=25).json()
            
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]
                    log(f"📩 Comando recebido: {u.get('callback_query', {}).get('data', 'Texto')}")
                    
                    if "callback_query" in u:
                        data = u["callback_query"]["data"]
                        if data == "set_fx": bot.mode = "FOREX"
                        elif data == "set_crypto": bot.mode = "CRYPTO"
                        elif data == "get_rank": bot.run_ranking()
                        bot.build_menu()
            
            # Varredura de Mercado
            log(f"🔎 Analisando {bot.mode}...")
            universe = Config.FOREX_ASSETS if bot.mode == "FOREX" else Config.CRYPTO_ASSETS
            for s in universe:
                res = get_analysis(s)
                if res and res['score'] > Config.THRESHOLD:
                    if not any(t['symbol'] == s for t in bot.trades):
                        bot.send_msg(f"⚡ <b>SINAL: {s}</b>\n{res['dir']}\nPreço: {res['price']:.5f}\nForça: {res['score']:.2f}")
                        bot.trades.append({"symbol": s, "entry": res['price'], "dir": res['simple'], "time": datetime.now() + timedelta(minutes=Config.CHECK_TIME)})
            
            # Checa resultados
            now = datetime.now()
            for t in bot.trades[:]:
                if now >= t['time']:
                    res = get_analysis(t['symbol'])
                    if res:
                        win = (res['price'] > t['entry'] and t['dir'] == "BUY") or (res['price'] < t['entry'] and t['dir'] == "SELL")
                        bot.wins += 1 if win else 0
                        bot.losses += 0 if win else 1
                        bot.send_msg(f"{'✅ WIN' if win else '❌ LOSS'}: {t['symbol']}\nE: {t['entry']:.5f} | S: {res['price']:.5f}")
                        bot.trades.remove(t)

            time.sleep(2)
        except Exception as e:
            log(f"⚠️ Erro no loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
