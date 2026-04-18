# -*- coding: utf-8 -*-
import os
import time
import requests
import json
import pandas as pd
from datetime import datetime, timedelta, timezone

# ========================================
# CONFIGURAÇÕES DE GESTÃO
# ========================================
class Config:
    # Token mantido conforme sua versão anterior
    BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID = "1056795017" 
    BR_TIMEZONE = timezone(timedelta(hours=-3))
    
    FOREX_ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS = ["BTC-USD", "ETH-USD", "SOL-USD"]
    
    TP_PERCENT = 0.50  
    SL_PERCENT = 0.25  
    THRESHOLD = 1.8    
    TIMEFRAME = "5m"   

def log(msg):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ========================================
# MOTOR DE ANÁLISE TÉCNICA (ATUALIZADO)
# ========================================
def get_analysis(symbol):
    import yfinance as yf
    yf_symbol = f"{symbol}=X" if "-" not in symbol and "JPY" not in symbol else symbol
    if "JPY" in symbol and "=" not in symbol: yf_symbol = f"{symbol}=X"
    
    try:
        df = yf.Ticker(yf_symbol).history(period="2d", interval=Config.TIMEFRAME)
        if len(df) < 30: return None
        
        closes = df['Close']
        highs = df['High']
        lows = df['Low']
        
        # RSI e Médias
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        cur_rsi = rsi.iloc[-1]

        ema9 = closes.tail(9).mean()
        ema21 = closes.tail(21).mean()
        diff = ema9 - ema21
        std = closes.std()
        score = abs(diff / std) * 10 if std > 0 else 0
        
        # Gatilhos de Rompimento (Máxima/Mínima das últimas 5 velas)
        trigger_buy = highs.tail(5).max()
        trigger_sell = lows.tail(5).min()

        return {
            "symbol": symbol, "price": closes.iloc[-1], 
            "score": score, "diff": diff, "rsi": cur_rsi,
            "t_buy": trigger_buy, "t_sell": trigger_sell
        }
    except: return None

# ========================================
# CLASSE DO BOT (INTEGRADA COM RADAR)
# ========================================
class TradingBot:
    def __init__(self):
        self.mode = "CRYPTO" 
        self.wins = 0
        self.losses = 0
        self.active_trades = []
        self.last_id = 0
        self.radar_list = {} # Armazena tempo do último alerta para evitar spam
        
    def send(self, text, markup=None):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML"}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=5)
        except: pass

    def build_menu(self):
        markup = {"inline_keyboard": [
            [{"text": f"📍 Mercado: {self.mode}", "callback_data": "ignore"}],
            [{"text": "📈 FOREX", "callback_data": "set_fx"}, {"text": "₿ CRIPTO", "callback_data": "set_crypto"}],
            [{"text": "🏆 VER RANKING", "callback_data": "get_rank"}],
            [{"text": "🔄 ATUALIZAR", "callback_data": "refresh"}]
        ]}
        msg = (f"<b>🎛 DASHBOARD PRO</b>\n"
               f"Placar: <code>{self.wins}W - {self.losses}L</code>\n"
               f"Modo: <b>{self.mode}</b>\n"
               f"Timeframe: <code>{Config.TIMEFRAME}</code>")
        self.send(msg, markup)

    def run_ranking(self):
        self.send("⏳ <i>Gerando ranking de força...</i>")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS
        ranks = []
        for s in universe:
            res = get_analysis(s)
            if res: ranks.append(res)
        ranks.sort(key=lambda x: x['score'], reverse=True)
        
        msg = f"🏆 <b>RANKING {self.mode}</b>\n\n"
        for i, r in enumerate(ranks[:3], 1):
            sentido = "BUY" if r['diff'] > 0 else "SELL"
            msg += f"{i}º {r['symbol']}: {r['score']:.2f} ({sentido})\n"
        self.send(msg)

    def scan(self):
        log(f"🔎 Varrendo {self.mode}...")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS
        for s in universe:
            if any(t['symbol'] == s for t in self.active_trades): continue
            
            res = get_analysis(s)
            if not res: continue

            # --- LÓGICA 1: O RADAR (ANTECIPAÇÃO) ---
            if 0.8 < res['score'] < Config.THRESHOLD:
                # Cooldown de 30 minutos para o mesmo alerta
                last_alert = self.radar_list.get(s, 0)
                if time.time() - last_alert > 1800:
                    tipo = "ALTA" if res['diff'] > 0 else "BAIXA"
                    valor_x = res['t_buy'] if tipo == "ALTA" else res['t_sell']
                    
                    msg = (f"⚠️ <b>RADAR: {s}</b>\n"
                           f"Tendência de {tipo} em formação.\n"
                           f"<b>Gatilho:</b> Se romper <code>{valor_x:.5f}</code> a entrada é confirmada.\n"
                           f"Força Atual: {res['score']:.2f}")
                    self.send(msg)
                    self.radar_list[s] = time.time()

            # --- LÓGICA 2: SINAL DE ENTRADA ---
            if res['score'] >= Config.THRESHOLD:
                # Filtro RSI para segurança
                pode_entrar = (res['diff'] > 0 and res['rsi'] < 65) or (res['diff'] < 0 and res['rsi'] > 35)
                
                if pode_entrar:
                    price = res['price']
                    direcao = "BUY" if res['diff'] > 0 else "SELL"
                    tp = price * (1 + Config.TP_PERCENT/100) if direcao == "BUY" else price * (1 - Config.TP_PERCENT/100)
                    sl = price * (1 - Config.SL_PERCENT/100) if direcao == "BUY" else price * (1 + Config.SL_PERCENT/100)
                    
                    msg = (f"⚡ <b>SINAL DE ENTRADA</b>\n\n"
                           f"Ativo: <b>{s}</b>\n"
                           f"Ação: {'BUY 🟢' if direcao == 'BUY' else 'SELL 🔴'}\n"
                           f"Preço: <code>{price:.5f}</code>\n"
                           f"----------------------\n"
                           f"🎯 Alvo (TP): <code>{tp:.5f}</code>\n"
                           f"🛡 Proteção (SL): <code>{sl:.5f}</code>")
                    self.send(msg)
                    self.active_trades.append({
                        "symbol": s, "entry": price, "tp": tp, "sl": sl, "dir": direcao
                    })

    def monitor_trades(self):
        for t in self.active_trades[:]:
            res = get_analysis(t['symbol'])
            if not res: continue
            cur_price = res['price']
            
            is_win = (t['dir'] == "BUY" and cur_price >= t['tp']) or (t['dir'] == "SELL" and cur_price <= t['tp'])
            is_loss = (t['dir'] == "BUY" and cur_price <= t['sl']) or (t['dir'] == "SELL" and cur_price >= t['sl'])
            
            if is_win or is_loss:
                status = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                if is_win: self.wins += 1 
                else: self.losses += 1
                
                msg = (f"🏁 <b>OPERAÇÃO ENCERRADA</b>\n"
                       f"Ativo: {t['symbol']}\n"
                       f"Resultado: <b>{status}</b>\n\n"
                       f"Entrada: <code>{t['entry']:.5f}</code>\n"
                       f"Saída: <code>{cur_price:.5f}</code>")
                self.send(msg)
                self.active_trades.remove(t)
                self.build_menu()

# ========================================
# EXECUÇÃO
# ========================================
def main():
    log("🔌 Iniciando sistema PRO com Radar...")
    requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook")
    bot = TradingBot()
    bot.build_menu()

    while True:
        try:
            url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates?offset={bot.last_id + 1}&timeout=5"
            r = requests.get(url, timeout=10).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]
                    if "callback_query" in u:
                        data = u["callback_query"]["data"]
                        if data == "set_fx": bot.mode = "FOREX"
                        elif data == "set_crypto": bot.mode = "CRYPTO"
                        elif data == "get_rank": bot.run_ranking()
                        bot.build_menu()
            
            bot.scan()
            bot.monitor_trades()
            time.sleep(30)
            
        except Exception as e:
            log(f"Erro: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
