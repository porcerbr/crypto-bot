# -*- coding: utf-8 -*-
import os
import time
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

# ========================================
# CONFIGURAÇÕES DE TRADING
# ========================================
class Config:
    BOT_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    CHAT_ID: str = "1056795017"
    BR_TIMEZONE: timezone = timezone(timedelta(hours=-3))
    
    # Ativos para monitorar
    FOREX_ASSETS: List[str] = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS: List[str] = ["BTC-USD", "ETH-USD", "SOL-USD"]

    # Estratégia
    SIGNAL_STRENGTH_THRESHOLD: float = 2.5  # Sensibilidade (Menor = Mais sinais)
    CHECK_RESULT_MINUTES: int = 5           # Tempo para validar o Win/Loss

# ========================================
# MOTOR DE DADOS
# ========================================
def log(msg: str):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def fetch_price_data(symbol: str):
    import yfinance as yf
    yf_symbol = f"{symbol}=X" if "-" not in symbol and "JPY" not in symbol else symbol
    if "JPY" in symbol and "=" not in symbol: yf_symbol = f"{symbol}=X"
    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period="1d", interval="1m")
        return df if not df.empty else None
    except: return None

# ========================================
# GESTÃO DE ESTADO E INTERFACE
# ========================================
class BotManager:
    def __init__(self):
        self.market_mode = "FOREX"
        self.wins = 0
        self.losses = 0
        self.active_trades = [] # Guarda sinais para checar resultado depois
        self.last_update_id = 0

    def send(self, text, markup=None):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML"}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=5)
        except: pass

    def show_menu(self):
        winrate = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
        markup = {
            "inline_keyboard": [
                [{"text": f"📍 Mercado: {self.market_mode}", "callback_data": "ignore"}],
                [{"text": "📈 FOREX", "callback_data": "set_forex"}, {"text": "₿ CRIPTO", "callback_data": "set_crypto"}],
                [{"text": "🔄 Atualizar Painel", "callback_data": "refresh"}]
            ]
        }
        msg = (f"<b>📊 DASHBOARD DE TRADING</b>\n"
               f"---------------------------\n"
               f"Placar: <b>{self.wins}W - {self.losses}L</b>\n"
               f"Assertividade: <code>{winrate:.1f}%</code>\n"
               f"Modo: <b>{self.market_mode}</b>\n"
               f"---------------------------\n"
               f"🔎 Monitorando oportunidades...")
        self.send(msg, markup)

    def process_signals(self):
        log(f"🔎 Varrendo {self.market_mode}...")
        universe = Config.FOREX_ASSETS if self.market_mode == "FOREX" else Config.CRYPTO_ASSETS
        
        for symbol in universe:
            df = fetch_price_data(symbol)
            if df is None: continue

            # Lógica de Médias Móveis (EMA 9 e 21)
            closes = df['Close'].tolist()
            ema9 = sum(closes[-9:]) / 9
            ema21 = sum(closes[-21:]) / 21
            
            strength = abs(ema9 - ema21) / closes[-1] * 1000
            direction = "BUY 🟢" if ema9 > ema21 else "SELL 🔴"

            # Se a tendência for forte, manda o sinal
            if strength > Config.SIGNAL_STRENGTH_THRESHOLD:
                # Evita mandar sinal repetido do mesmo ativo muito rápido
                if not any(t['symbol'] == symbol for t in self.active_trades):
                    price = closes[-1]
                    self.send(f"⚡ <b>NOVO SINAL: {symbol}</b>\nDireção: {direction}\nPreço: {price:.5f}\nForça: {strength:.2f}")
                    
                    # Salva para checar resultado daqui a X minutos
                    self.active_trades.append({
                        "symbol": symbol,
                        "entry_price": price,
                        "direction": "BUY" if "BUY" in direction else "SELL",
                        "check_at": datetime.now() + timedelta(minutes=Config.CHECK_RESULT_MINUTES)
                    })

    def check_results(self):
        now = datetime.now()
        for trade in self.active_trades[:]:
            if now >= trade['check_at']:
                df = fetch_price_data(trade['symbol'])
                if df is not None:
                    current_price = df['Close'].iloc[-1]
                    diff = current_price - trade['entry_price']
                    
                    win = (diff > 0 and trade['direction'] == "BUY") or (diff < 0 and trade['direction'] == "SELL")
                    
                    if win:
                        self.wins += 1
                        self.send(f"✅ <b>RESULTADO: {trade['symbol']}</b>\nStatus: WIN! 🎉\nPreço Saída: {current_price:.5f}")
                    else:
                        self.losses += 1
                        self.send(f"❌ <b>RESULTADO: {trade['symbol']}</b>\nStatus: LOSS\nPreço Saída: {current_price:.5f}")
                    
                    self.active_trades.remove(trade)
                    self.show_menu() # Atualiza o placar no Telegram

# ========================================
# LOOP PRINCIPAL
# ========================================
def main():
    bot = BotManager()
    log("🚀 Bot de Sinais Reiniciado.")
    bot.show_menu()

    while True:
        try:
            # 1. Checa comandos do usuário
            url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates?offset={bot.last_update_id + 1}"
            updates = requests.get(url, timeout=5).json()
            for u in updates.get("result", []):
                bot.last_update_id = u["update_id"]
                if "callback_query" in u:
                    data = u["callback_query"]["data"]
                    if data == "set_forex": bot.market_mode = "FOREX"
                    elif data == "set_crypto": bot.market_mode = "CRYPTO"
                    bot.show_menu()

            # 2. Varredura e Resultados
            bot.process_signals()
            bot.check_results()
            
            time.sleep(30)
        except Exception as e:
            log(f"Erro: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
