# -*- coding: utf-8 -*-
import os
import time
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass

# ========================================
# CONFIGURAÇÕES ATUALIZADAS
# ========================================
class Config:
    BOT_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "7952260034:AAGVE78Dy81Uyms4oWGH_9rvW7CYA6iSncY")
    CHAT_ID: str = "1056795017"
    BR_TIMEZONE: timezone = timezone(timedelta(hours=-3))
    
    # Universos de Ativos
    FOREX_ASSETS: List[str] = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURGBP"]
    CRYPTO_ASSETS: List[str] = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD"]

    # Indicadores
    EMA_SHORT: int = 9
    EMA_LONG: int = 21
    RSI_PERIOD: int = 14

@dataclass
class Candle:
    time: datetime
    open: float
    close: float
    high: float
    low: float
    volume: float

# ========================================
# ESTADO DO BOT (MODOS DE MERCADO)
# ========================================
class BotState:
    def __init__(self):
        self.market_mode: str = "FOREX" # Modos: "FOREX" ou "CRYPTO"
        self.is_active: bool = True
        self.last_update_id: Optional[int] = None
        self.last_used_symbols: Dict[str, datetime] = {}

    def get_current_universe(self) -> List[str]:
        return Config.FOREX_ASSETS if self.market_mode == "FOREX" else Config.CRYPTO_ASSETS

# ========================================
# BUSCA DE DADOS (YAHOO FINANCE)
# ========================================
def fetch_candles(symbol: str, limit: int = 60) -> Optional[List[Candle]]:
    import yfinance as yf
    # Ajusta o sufixo: Forex precisa de =X, Cripto no Yahoo já é BTC-USD
    yf_symbol = f"{symbol}=X" if "-" not in symbol and "JPY" not in symbol else symbol
    if "JPY" in symbol and "=" not in symbol: yf_symbol = f"{symbol}=X"

    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period="1d", interval="1m")
        if df.empty: return None
        
        raw = []
        for index, row in df.iterrows():
            ts = index.astimezone(timezone.utc).to_pydatetime()
            raw.append(Candle(ts, float(row['Open']), float(row['Close']), float(row['High']), float(row['Low']), float(row.get('Volume', 0))))
        return raw[-limit:]
    except:
        return None

# ========================================
# CÁLCULOS TÉCNICOS
# ========================================
def get_score(candles: List[Candle]) -> Tuple[float, str]:
    closes = [c.close for c in candles]
    
    # Lógica simples de EMA
    ema_s = sum(closes[-9:]) / 9
    ema_l = sum(closes[-21:]) / 21
    
    # Lógica simples de RSI
    diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = sum(d for d in diffs if d > 0) / 14
    losses = abs(sum(d for d in diffs if d < 0)) / 14
    rsi = 100 - (100 / (1 + (gains/losses if losses != 0 else 1)))
    
    trend_strength = (abs(ema_s - ema_l) / closes[-1]) * 1000
    total_score = trend_strength + abs(rsi - 50)
    
    direction = "COMPRA 🟢" if ema_s > ema_l else "VENDA 🔴"
    return total_score, direction

# ========================================
# INTERFACE TELEGRAM
# ========================================
def send_telegram(msg: str, markup: Optional[Dict] = None):
    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
    payload = {"chat_id": Config.CHAT_ID, "text": msg, "parse_mode": "HTML"}
    if markup: payload["reply_markup"] = json.dumps(markup)
    requests.post(url, json=payload)

def show_main_menu(state: BotState):
    mode_icon = "💵" if state.market_mode == "FOREX" else "₿"
    markup = {
        "inline_keyboard": [
            [{"text": f"📍 Modo Atual: {state.market_mode} {mode_icon}", "callback_data": "ignore"}],
            [{"text": "📈 Trocar para FOREX", "callback_data": "set_forex"}, {"text": "₿ Trocar para CRIPTO", "callback_data": "set_crypto"}],
            [{"text": "🏆 Melhores Ativos (Ranking)", "callback_data": "get_ranking"}],
            [{"text": "🔄 Atualizar Status", "callback_data": "refresh"}]
        ]
    }
    msg = f"<b>PAINEL MULTIMERCADO</b>\nO bot está monitorando <b>{state.market_mode}</b>.\nO que deseja fazer?"
    send_telegram(msg, markup)

def handle_updates(state: BotState):
    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates"
    params = {"offset": state.last_update_id + 1 if state.last_update_id else None}
    try:
        resp = requests.get(url, params=params).json()
        for update in resp.get("result", []):
            state.last_update_id = update["update_id"]
            if "callback_query" in update:
                data = update["callback_query"]["data"]
                if data == "set_forex":
                    state.market_mode = "FOREX"
                    send_telegram("✅ Modo alterado para <b>FOREX</b>.")
                elif data == "set_crypto":
                    state.market_mode = "CRYPTO"
                    send_telegram("✅ Modo alterado para <b>CRIPTO</b>.")
                elif data == "get_ranking":
                    send_ranking(state)
                show_main_menu(state)
            elif "message" in update:
                show_main_menu(state)
    except: pass

def send_ranking(state: BotState):
    send_telegram("🔍 <i>Analisando o mercado, aguarde...</i>")
    universe = state.get_current_universe()
    results = []
    
    for symbol in universe:
        candles = fetch_candles(symbol)
        if candles:
            score, direction = get_score(candles)
            results.append({"symbol": symbol, "score": score, "direction": direction})
    
    results.sort(key=lambda x: x["score"], reverse=True)
    
    msg = f"🏆 <b>MELHORES DO DIA ({state.market_mode})</b>\n\n"
    for i, res in enumerate(results[:3], 1):
        msg += f"{i}º <b>{res['symbol']}</b>\nForça: {res['score']:.2f}\nSinal: {res['direction']}\n\n"
    
    send_telegram(msg)

# ========================================
# LOOP PRINCIPAL
# ========================================
def main():
    state = BotState()
    # Limpeza inicial do Telegram
    requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook")
    show_main_menu(state)
    
    while True:
        handle_updates(state)
        time.sleep(5)

if __name__ == "__main__":
    main()
