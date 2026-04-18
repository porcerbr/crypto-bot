# -*- coding: utf-8 -*-
import os
import time
import requests
import json
import pandas as pd
from datetime import datetime, timedelta, timezone

# ========================================
# CONFIGURAÇÕES (GERENCIAMENTO 2 PRA 1)
# ========================================
class Config:
    BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID = "1056795017" 
    BR_TIMEZONE = timezone(timedelta(hours=-3))
    
    FOREX_ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    CRYPTO_ASSETS = ["BTC-USD", "ETH-USD", "SOL-USD"]
    
    # Relação Risco/Retorno 2x1 do Curinga
    TP_PERCENT = 1.0  # Take Profit alvo
    SL_PERCENT = 0.50  # Stop Loss curto
    TIMEFRAME = "15m"   # Tempo gráfico de 5 minutos

def log(msg):
    ts = datetime.now(Config.BR_TIMEZONE).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ========================================
# MOTOR DE ANÁLISE: O CÉREBRO DO CURINGA
# ========================================
def get_analysis(symbol):
    import yfinance as yf
    yf_symbol = f"{symbol}=X" if "-" not in symbol and "JPY" not in symbol else symbol
    if "JPY" in symbol and "=" not in symbol: yf_symbol = f"{symbol}=X"
    
    try:
        # Puxando 5 dias para ter velas suficientes para a EMA 200
        df = yf.Ticker(yf_symbol).history(period="5d", interval=Config.TIMEFRAME)
        if len(df) < 200: return None
        
        closes = df['Close']
        highs = df['High']
        lows = df['Low']
        
        # 1. TENDÊNCIA MÃE (EMA 200)
        ema200 = closes.ewm(span=200, adjust=False).mean().iloc[-1]
        
        # 2. EXAUSTÃO (Bandas de Bollinger 20, 2)
        sma20 = closes.rolling(window=20).mean().iloc[-1]
        std20 = closes.rolling(window=20).std().iloc[-1]
        upper_band = sma20 + (std20 * 2)
        lower_band = sma20 - (std20 * 2)

        # 3. TENDÊNCIA CURTA E FORÇA (EMA 9 e 21 + RSI)
        ema9 = closes.tail(9).mean()
        ema21 = closes.tail(21).mean()
        
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        cur_rsi = (100 - (100 / (1 + rs))).iloc[-1]

        cur_price = closes.iloc[-1]
        
        # 4. PRICE ACTION (Gatilhos de Rompimento - Últimas 5 velas)
        trigger_buy = highs.tail(5).max()
        trigger_sell = lows.tail(5).min()

        # --- AVALIAÇÃO DE CONFLUÊNCIA ---
        # Definindo o cenário base
        cenario = "NEUTRO"
        if cur_price > ema200 and ema9 > ema21:
            cenario = "ALTA"
        elif cur_price < ema200 and ema9 < ema21:
            cenario = "BAIXA"

        return {
            "symbol": symbol, "price": cur_price, 
            "cenario": cenario, "rsi": cur_rsi,
            "ema200": ema200, "upper": upper_band, "lower": lower_band,
            "t_buy": trigger_buy, "t_sell": trigger_sell
        }
    except: return None

# ========================================
# CLASSE DO BOT
# ========================================
class TradingBot:
    def __init__(self):
        self.mode = "CRYPTO" 
        self.wins = 0
        self.losses = 0
        self.active_trades = []
        self.last_id = 0
        self.radar_list = {}
        
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
            [{"text": "🔄 ATUALIZAR", "callback_data": "refresh"}]
        ]}
        winrate = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
        msg = (f"<b>🎛 BOT SNIPER (ESTRATÉGIA CURINGA)</b>\n"
               f"Placar: <code>{self.wins}W - {self.losses}L</code> ({winrate:.1f}%)\n"
               f"Modo: <b>{self.mode}</b>\n"
               f"Timeframe: <code>{Config.TIMEFRAME}</code>\n"
               f"Gestão Risco: 2x1 (TP {Config.TP_PERCENT}% | SL {Config.SL_PERCENT}%)")
        self.send(msg, markup)

    def scan(self):
        log(f"🔎 Varrendo {self.mode}...")
        universe = Config.FOREX_ASSETS if self.mode == "FOREX" else Config.CRYPTO_ASSETS
        
        for s in universe:
            if any(t['symbol'] == s for t in self.active_trades): continue
            
            res = get_analysis(s)
            if not res or res['cenario'] == "NEUTRO": continue

            price = res['price']

            # --- LÓGICA 1: O RADAR (PREPARAÇÃO) ---
            # Se as médias alinharam, mas o preço ainda não rompeu
            last_alert = self.radar_list.get(s, 0)
            if time.time() - last_alert > 1800: # Evita spam a cada 30 min
                gatilho = res['t_buy'] if res['cenario'] == "ALTA" else res['t_sell']
                msg = (f"⚠️ <b>RADAR SNIPER: {s}</b>\n"
                       f"Tendência macro de <b>{res['cenario']}</b> confirmada pela EMA 200.\n"
                       f"<b>Ação:</b> Aguardando rompimento em <code>{gatilho:.5f}</code>.")
                self.send(msg)
                self.radar_list[s] = time.time()

            # --- LÓGICA 2: A EXECUÇÃO (GATILHO) ---
            # Para COMPRAR: Rompeu a máxima + Longe da banda superior + RSI sadio
            pode_comprar = (res['cenario'] == "ALTA" and price >= res['t_buy'] and price < res['upper'] and res['rsi'] < 70)
            
            # Para VENDER: Rompeu a mínima + Longe da banda inferior + RSI sadio
            pode_vender = (res['cenario'] == "BAIXA" and price <= res['t_sell'] and price > res['lower'] and res['rsi'] > 30)

            if pode_comprar or pode_vender:
                direcao = "BUY 🟢" if pode_comprar else "SELL 🔴"
                dir_simple = "BUY" if pode_comprar else "SELL"
                
                tp = price * (1 + Config.TP_PERCENT/100) if dir_simple == "BUY" else price * (1 - Config.TP_PERCENT/100)
                sl = price * (1 - Config.SL_PERCENT/100) if dir_simple == "BUY" else price * (1 + Config.SL_PERCENT/100)
                
                msg = (f"🎯 <b>SINAL CONFIRMADO (ROMPIMENTO)</b>\n\n"
                       f"Ativo: <b>{s}</b>\n"
                       f"Ação: {direcao}\n"
                       f"Preço de Entrada: <code>{price:.5f}</code>\n"
                       f"----------------------\n"
                       f"🎯 Alvo (TP): <code>{tp:.5f}</code>\n"
                       f"🛡 Proteção (SL): <code>{sl:.5f}</code>")
                self.send(msg)
                
                self.active_trades.append({
                    "symbol": s, "entry": price, "tp": tp, "sl": sl, "dir": dir_simple
                })
                # Reseta o radar para este ativo, pois já entrou
                self.radar_list[s] = time.time() 

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
# INICIALIZAÇÃO
# ========================================
def main():
    log("🔌 Iniciando sistema Curinga Econômico...")
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
                        elif data == "refresh": pass
                        bot.build_menu()
            
            bot.scan()
            bot.monitor_trades()
            time.sleep(30) # Analisa o mercado a cada 30 segundos
            
        except Exception as e:
            log(f"Erro: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
