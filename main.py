# -*- coding: utf-8 -*-
import os
import time
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

# ========================================
# CONFIGURAÇÕES
# ========================================
class Config:
    BOT_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID: str = "1056795017"
    BR_TIMEZONE: timezone = timezone(timedelta(hours=-3))
    
    FOREX_ASSETS: List[str] = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS: List[str] = ["BTC-USD", "ETH-USD", "SOL-USD"]

    # Sensibilidade: 1.5 é equilibrado com a nova normalização
    THRESHOLD: float = 1.5
    CHECK_TIME: int = 5 # Minutos para conferir o resultado

# ========================================
# MOTOR TÉCNICO
# ========================================
def log(msg: str):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def fetch_data(symbol: str):
    import yfinance as yf
    yf_symbol = f"{symbol}=X" if "-" not in symbol and "JPY" not in symbol else symbol
    if "JPY" in symbol and "=" not in symbol: yf_symbol = f"{symbol}=X"
    try:
        df = yf.Ticker(yf_symbol).history(period="1d", interval="1m")
        return df if not df.empty else None
    except: return None

def get_analysis(symbol: str):
    df = fetch_data(symbol)
    if df is None: return None
    
    closes = df['Close'].tolist()
    ema9 = sum(closes[-9:]) / 9
    ema21 = sum(closes[-21:]) / 21
    
    # Normalização para equilibrar Forex e Cripto
    diff = (ema9 - ema21)
    std_dev = df['Close'].std()
    score = abs(diff / std_dev) * 10 if std_dev > 0 else 0
    
    return {
        "symbol": symbol,
        "price": closes[-1],
        "score": score,
        "direction": "BUY 🟢" if diff > 0 else "SELL 🔴",
        "dir_simple": "BUY" if diff > 0 else "SELL"
    }

# ========================================
# GESTÃO DO BOT
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
        try: requests.post(url, json=payload, timeout=5)
        except: pass

    def build_menu(self):
        markup = {
            "inline_keyboard": [
                [{"text": f"📍 Mercado: {self.mode}", "callback_data": "ignore"}],
                [{"text": "📈 FOREX", "callback_data": "set_fx"}, {"text": "₿ CRIPTO", "callback_data": "set_crypto"}],
                [{"text": "🏆 VER RANKING", "callback_data": "get_rank"}],
                [{"text": "🔄 ATUALIZAR", "callback_data": "refresh"}]
            ]
        }
        winrate = (self.wins/(self.wins+self.losses)*100) if (self.wins+self.losses)>0 else 0
        msg = (f"<b>🎛 DASHBOARD TRADING</b>\n"
               f"Placar: <code>{self.wins}W - {self.losses}L</code>\n"
               f"Assertividade: <code>{winrate:.1f}%</code>\n"
               f"Status: 🟢 Ativo")
        self.send_msg(msg, markup)

    def run_ranking(self):
        self.send_msg("⏳ <i>Analisando ranking de ativos...</i>")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS
        ranks = []
        for s in universe:
            res = get_analysis(s)
            if res: ranks.append(res)
        
        ranks.sort(key=lambda x: x['score'], reverse=True)
        msg = f"🏆 <b>MELHORES OPORTUNIDADES ({self.mode})</b>\n\n"
        for i, r in enumerate(ranks[:3], 1):
            msg += f"{i}º <b>{r['symbol']}</b>\nForça: {r['score']:.2f} | {r['direction']}\nPreço: {r['price']:.5f}\n\n"
        self.send_msg(msg)

    def scan(self):
        log(f"🔎 Varrendo {self.mode}...")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS
        for s in universe:
            res = get_analysis(s)
            if res and res['score'] > Config.THRESHOLD:
                if not any(t['symbol'] == s for t in self.trades):
                    self.send_msg(f"⚡ <b>SINAL DE ENTRADA</b>\n\nAtivo: {s}\nDireção: <b>{res['direction']}</b>\nPreço Entrada: <code>{res['price']:.5f}</code>\nForça: {res['score']:.2f}")
                    self.trades.append({
                        "symbol": s, "entry": res['price'], "dir": res['dir_simple'],
                        "time": datetime.now() + timedelta(minutes=Config.CHECK_TIME)
                    })

    def check(self):
        now = datetime.now()
        for t in self.trades[:]:
            if now >= t['time']:
                res = get_analysis(t['symbol'])
                if res:
                    exit_price = res['price']
                    win = (exit_price > t['entry'] and t['dir'] == "BUY") or (exit_price < t['entry'] and t['dir'] == "SELL")
                    
                    status = "✅ WIN" if win else "❌ LOSS"
                    if win: self.wins += 1
                    else: self.losses += 1
                    
                    msg = (f"🏁 <b>RESULTADO DA OPERAÇÃO</b>\n\n"
                           f"Ativo: {t['symbol']}\n"
                           f"Status: <b>{status}</b>\n"
                           f"Entrada: <code>{t['entry']:.5f}</code>\n"
                           f"Saída: <code>{exit_price:.5f}</code>")
                    self.send_msg(msg)
                    self.trades.remove(t)
                    self.build_menu()

# ========================================
# LOOP
# ========================================
def main():
    bot = TradingBot()
    bot.build_menu()
    while True:
        try:
            # Updates Telegram
            url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates?offset={bot.last_id + 1}"
            r = requests.get(url, timeout=5).json()
            for u in r.get("result", []):
                bot.last_id = u["update_id"]
                if "callback_query" in u:
                    data = u["callback_query"]["data"]
                    if data == "set_fx": bot.mode = "FOREX"
                    elif data == "set_crypto": bot.mode = "CRYPTO"
                    elif data == "get_rank": bot.run_ranking()
                    bot.build_menu()
            
            bot.scan()
            bot.check()
            time.sleep(30)
        except Exception as e:
            log(f"Erro: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
