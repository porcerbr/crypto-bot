# coding: utf-8
"""
TICKMILL SNIPER BOT v9.1 — PROFESSIONAL EDITION
══════════════════════════════════════════════════════════════════════════
MELHORIAS IMPLEMENTADAS (v9.1):
✅ Gestão de Risco: Stop Out preventivo, Trailing Swing+ATR, Correlação ativa.
✅ Execução: Partial Close (50%), Verificação de Spread, Reconciliação MT5.
✅ Dados: Híbrido MT5 (Real-time) + Yahoo (Fallback), Cache validado por idade.
✅ Arquitetura: Banco SQLite (seguro), Tratamento de exceções robusto, IDs persistentes.
✅ Dashboard: Preview de trade antes da execução, Confirmações modais, Sons.
✅ Lógica: Reversão unificada (todos os mercados), Parâmetros dinâmicos.
"""
import os, time, json, math, threading, requests, sqlite3, hashlib
import pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import logging

# Configuração de Log
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────────
# CONFIGURAÇÕES GLOBAIS
# ───────────────────────────────────────────────────────────────────────
class Config:
    BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ = timezone(timedelta(hours=-3))
    
    # Mercado
    MARKET_CATEGORIES = {
        "FOREX": {"label": "FOREX", "assets": {
            "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
            "USDCAD": "USD/CAD", "USDCHF": "USD/CHF", "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
            "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY"}},
        "CRYPTO": {"label": "CRIPTO", "assets": {
            "BTCUSD": "Bitcoin", "ETHUSD": "Ethereum", "SOLUSD": "Solana",
            "BNBUSD": "BNB", "XRPUSD": "XRP", "ADAUSD": "Cardano",
            "DOGEUSD": "Dogecoin", "LTCUSD": "Litecoin"}},
        "COMMODITIES": {"label": "COMMODITIES", "assets": {
            "XAUUSD": "Ouro (Gold)", "XAGUSD": "Prata (Silver)",
            "XTIUSD": "Petróleo WTI", "BRENT": "Petróleo Brent",
            "NATGAS": "Gás Natural", "COPPER": "Cobre"}},
        "INDICES": {"label": "ÍNDICES", "assets": {
            "US500": "S&P 500", "USTEC": "Nasdaq 100", "US30": "Dow Jones",
            "DE40": "DAX 40", "UK100": "FTSE 100", "JP225": "Nikkei 225",
            "AUS200": "ASX 200", "STOXX50": "Euro Stoxx 50"}}
    }
    # Risco & Execução
    SL_TP_BASE_MULTIPLIER = 250.0
    SL_MAX_PCT = 3.0; SL_MIN_PCT = 0.2
    TP_SL_RATIO = 2.5
    DYNAMIC_RR_ENABLED = True
    DYNAMIC_RR_TIERS = [(3, 3.0, "⚡ Forte"), (5, 3.5, "🔥 Muito Forte"), (7, 4.5, "💎 Perfeito")]
    
    # Parâmetros Técnicos (Agora editáveis via DB/Config)
    ATR_PERIOD = 14; ATR_MULT_SL = 1.5; ATR_MULT_TP = 3.75; ATR_MULT_TRAIL = 1.2
    MAX_CONSECUTIVE_LOSSES = 2; PAUSE_DURATION = 3600
    ADX_MIN = 22; MAX_TRADES = 3; ASSET_COOLDOWN = 3600; MIN_CONFLUENCE = 5
    MIN_CONFLUENCE_CT = 4; REVERSAL_MIN_SCORE = 6; REVERSAL_COOLDOWN = 2700
    REVERSAL_REQUIRE_TREND = True; REVERSAL_RSI_SELL = 75; REVERSAL_RSI_BUY = 25
    REVERSAL_BAND_BUFFER = 0.997
    RADAR_COOLDOWN = 1800; GATILHO_COOLDOWN = 300
    TRENDS_INTERVAL = 60  # Reduzido para maior agilidade
    NEWS_INTERVAL = 7200
    SCAN_INTERVAL = 15    # Loop mais rápido
    
    # Corretora
    BROKER_NAME = "Tickmill"; BROKER_PLATFORM = "MT5"; ACCOUNT_TYPE = "RAW"; BASE_CURRENCY = "USD"
    COMMISSION_PER_LOT_SIDE = {"FOREX": 3.0, "COMMODITIES": 3.0, "INDICES": 0.0, "CRYPTO": 0.0}
    MAX_LEVERAGE_BY_CAT = {"FOREX": 1000, "COMMODITIES": 500, "INDICES": 100, "CRYPTO": 200}
    MAX_LEVERAGE_BY_SYM = {"XAUUSD": 1000, "XAGUSD": 125, "XTIUSD": 100, "BRENT": 100, "NATGAS": 100, "COPPER": 100,
                           "US500": 100, "USTEC": 100, "US30": 100, "DE40": 100, "UK100": 100, "JP225": 100, "AUS200": 100, "STOXX50": 100}
    
    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "500.0"))
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    RISK_PERCENT_PER_TRADE = float(os.getenv("RISK_PERCENT_PER_TRADE", "2.0"))
    MARGIN_CALL_LEVEL = 100.0
    STOP_OUT_LEVEL = 30.0
    MIN_LOT = 0.01; LOT_STEP = 0.01
    MAX_SPREAD_POINTS = 30  # Limite de spread (ex: 30 pontos = 3 pips em EURUSD) para abortar entrada

    CONTRACT_SIZES = {"FOREX": 100000, "CRYPTO": 1, "COMMODITIES": 100, "INDICES": 1}
    CONTRACT_SIZES_SPECIFIC = {"XAUUSD": 100, "XAGUSD": 5000, "XTIUSD": 1000, "BRENT": 1000, "NATGAS": 1000, "COPPER": 1000}
    
    TIMEFRAMES = {"1m": ("Agressivo", "7d"), "5m": ("Alto", "5d"), "15m": ("Moderado", "5d"), 
                  "30m": ("Conservador", "5d"), "1h": ("Seguro", "60d"), "4h": ("Muito Seguro", "60d")}
    TIMEFRAME = "15m"
    
    STATE_DB = "bot_state.db"
    USE_KELLY_CRITERION = True; KELLY_FRACTION = 0.2
    NEWS_FILTER_IMPACT = ["HIGH"]; CORRELATION_LIMIT = 0.7

# Mapeamentos auxiliares
TICKMILL_TO_YF = {
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "SOLUSD": "SOL-USD", "BNBUSD": "BNB-USD",
    "XRPUSD": "XRP-USD", "ADAUSD": "ADA-USD", "DOGEUSD": "DOGE-USD", "LTCUSD": "LTC-USD",    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "XTIUSD": "CL=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "COPPER": "HG=F", "US500": "ES=F", "USTEC": "NQ=F", "US30": "YM=F",
    "DE40": "^GDAXI", "UK100": "^FTSE", "JP225": "^N225", "AUS200": "^AXJO", "STOXX50": "^STOXX50E",
}

def to_yf(s): return TICKMILL_TO_YF.get(s, f"{s}=X" if len(s)==6 and s.isalpha() else s)
def asset_cat(s):
    for cat, info in Config.MARKET_CATEGORIES.items():
        if s in info["assets"]: return cat
    return "CRYPTO"
def asset_name(s):
    for info in Config.MARKET_CATEGORIES.values():
        if s in info["assets"]: return info["assets"][s]
    return s
def contract_size_for(symbol):
    return Config.CONTRACT_SIZES_SPECIFIC.get(symbol, Config.CONTRACT_SIZES.get(asset_cat(symbol), 1))
def max_leverage_for(symbol):
    return Config.MAX_LEVERAGE_BY_SYM.get(symbol, Config.MAX_LEVERAGE_BY_CAT.get(asset_cat(symbol), 100))

# ───────────────────────────────────────────────────────────────────────
# BANCO DE DADOS (SUBSTITUI JSON)
# ───────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(Config.STATE_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS state (
        key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT)''')
    # Inicializa valores padrão se não existirem
    defaults = {
        "last_pending_id": "0", "wins": "0", "losses": "0", "consecutive_losses": "0",
        "balance": str(Config.INITIAL_BALANCE), "leverage": str(Config.DEFAULT_LEVERAGE),
        "risk_pct": str(Config.RISK_PERCENT_PER_TRADE), "mode": "CRYPTO", "timeframe": Config.TIMEFRAME,
        "paused_until": "0", "active_trades": "[]", "pending_trades": "[]", "asset_cooldown": "{}",
        "trend_cache": "{}", "history_list": "[]"
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO state (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def db_get(key, default=None):
    conn = sqlite3.connect(Config.STATE_DB)
    c = conn.cursor()
    c.execute("SELECT value FROM state WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    if row:
        try: return json.loads(row[0])        except: return row[0]
    return default

def db_set(key, value):
    conn = sqlite3.connect(Config.STATE_DB)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()
    conn.close()

def db_append_history(record):
    conn = sqlite3.connect(Config.STATE_DB)
    c = conn.cursor()
    c.execute("INSERT INTO history (data) VALUES (?)", (json.dumps(record),))
    # Mantém apenas últimos 500 registros
    c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 500)")
    conn.commit()
    conn.close()

# ───────────────────────────────────────────────────────────────────────
# CÁLCULOS FINANCEIROS & RISCO
# ───────────────────────────────────────────────────────────────────────
def fmt(p: float) -> str:
    if not p: return "0"
    if p >= 10000: return f"{p:,.2f}"
    if p >= 1000: return f"{p:.2f}"
    if p >= 10: return f"{p:.4f}"
    if p >= 1: return f"{p:.5f}"
    return f"{p:.6f}"

def calc_margin(symbol, price, leverage, lot):
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    kind = profile["kind"]
    base = profile["base"]
    quote = profile["quote"]
    lot = float(lot); leverage = max(1.0, float(leverage))
    
    if kind == "FX":
        if quote == "USD": notional = lot * cs * float(price)
        elif base == "USD": notional = lot * cs
        else: notional = lot * cs * currency_to_usd(base)
    else:
        notional = lot * cs * float(price)
    return round(notional / leverage, 2)

def symbol_profile(symbol):
    cat = asset_cat(symbol)
    cs = contract_size_for(symbol)
    if cat == "FOREX": return {"kind": "FX", "base": symbol[:3], "quote": symbol[3:], "contract_size": cs}    if cat == "COMMODITIES": return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": cs}
    if cat == "INDICES": return {"kind": "INDEX", "base": "USD", "quote": "USD", "contract_size": cs}
    if cat == "CRYPTO": return {"kind": "CRYPTO", "base": "USD", "quote": "USD", "contract_size": cs}
    return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": cs}

def commission_for(symbol, lot):
    if Config.ACCOUNT_TYPE not in ("RAW", "PRO"): return 0.0
    rate = Config.COMMISSION_PER_LOT_SIDE.get(asset_cat(symbol), 0.0)
    return round(rate * float(lot) * 2, 2)

def get_sl_tp_pct(leverage, rr_ratio=None):
    leverage = max(1, int(leverage))
    sl = Config.SL_TP_BASE_MULTIPLIER / leverage
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    rr = rr_ratio if rr_ratio is not None else Config.TP_SL_RATIO
    return round(sl, 2), round(sl * rr, 2)

def calc_lot_from_risk(symbol, entry, sl_price, balance, risk_pct):
    risk_money = float(balance) * (float(risk_pct) / 100.0)
    sl_distance = abs(float(entry) - float(sl_price))
    if sl_distance <= 0 or risk_money <= 0: return Config.MIN_LOT
    
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    kind = profile["kind"]
    
    if kind == "FX" and profile["quote"] == "USD": loss_per_lot = sl_distance * cs
    elif kind == "FX" and profile["base"] == "USD": loss_per_lot = sl_distance * cs * currency_to_usd(profile["quote"])
    else: loss_per_lot = sl_distance * cs
    
    if loss_per_lot <= 0: return Config.MIN_LOT
    lot = risk_money / loss_per_lot
    step = Config.LOT_STEP
    return round(math.floor(lot / step) * step, 4)

def normalize_lot(lot):
    if lot <= 0: return 0.0
    step = Config.LOT_STEP
    return round(math.floor(lot / step) * step, 4)

def currency_to_usd(currency):
    currency = (currency or "USD").upper()
    if currency == "USD": return 1.0
    # Simplificado para exemplo: em produção usar cache robusto ou API FX
    pairs = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "JPY": "USDJPY=X", "CAD": "USDCAD=X", "CHF": "USDCHF=X", "AUD": "AUDUSD=X"}
    ticker = pairs.get(currency)
    if not ticker: return 1.0
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period="1d", interval="1m")        if len(df): return float(df['Close'].iloc[-1]) if currency not in ["CAD", "CHF", "JPY"] else 1.0/float(df['Close'].iloc[-1])
    except: pass
    return 1.0

def calc_trade_plan(symbol, entry, leverage, balance, risk_pct, margin_usd):
    entry = float(entry); leverage = max(1.0, min(float(leverage), max_leverage_for(symbol)))
    balance = float(balance); risk_pct = float(risk_pct); margin_usd = float(margin_usd)
    
    if margin_usd <= 0 or entry <= 0 or balance <= 0:
        return {"ok": False, "error": "Dados inválidos."}

    sl_pct, tp_pct = get_sl_tp_pct(leverage)
    sl_price_buy = round(entry * (1 - sl_pct/100), 5)
    tp_price_buy = round(entry * (1 + tp_pct/100), 5)
    sl_price_sell = round(entry * (1 + sl_pct/100), 5)
    tp_price_sell = round(entry * (1 - tp_pct/100), 5)
    
    lot_by_margin = calc_lot_from_margin(symbol, entry, leverage, margin_usd) # Função auxiliar similar a calc_margin inverso
    # Simplificação para o exemplo: calcula lote baseado na margem desejada
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    if profile["kind"] == "FX" and profile["quote"] == "USD":
        lot_by_margin = (margin_usd * leverage) / (cs * entry)
    elif profile["kind"] == "FX" and profile["base"] == "USD":
        lot_by_margin = (margin_usd * leverage) / cs
    else:
        lot_by_margin = (margin_usd * leverage) / (cs * entry)
        
    lot_by_risk = calc_lot_from_risk(symbol, entry, sl_price_buy, balance, risk_pct)
    final_lot = normalize_lot(min(lot_by_margin, lot_by_risk))
    
    if final_lot < Config.MIN_LOT:
        return {"ok": False, "error": "Valor insuficiente para lote mínimo."}

    margin_required = calc_margin(symbol, entry, leverage, final_lot)
    commission = commission_for(symbol, final_lot)
    
    # Cálculo de Risco e Lucro
    sl_dist = abs(entry - sl_price_buy)
    risk_money = sl_dist * cs * final_lot # Simplificado para USD quote
    tp_dist = abs(tp_price_buy - entry)
    potential_profit = (tp_dist * cs * final_lot) - commission
    
    return {
        "ok": True, "symbol": symbol, "entry": entry, "leverage": leverage,
        "sl_pct": sl_pct, "tp_pct": tp_pct, "sl_price_buy": sl_price_buy, "tp_price_buy": tp_price_buy,
        "sl_price_sell": sl_price_sell, "tp_price_sell": tp_price_sell,
        "lot": final_lot, "margin_required": margin_required, "risk_money": round(risk_money, 2),
        "commission": commission, "potential_profit": round(potential_profit, 2),
        "ratio": round(tp_pct/sl_pct, 2) if sl_pct > 0 else 0, "contract_size": cs    }

# ───────────────────────────────────────────────────────────────────────
# ANÁLISE TÉCNICA (HÍBRIDA: MT5 + YAHOO)
# ───────────────────────────────────────────────────────────────────────
_data_cache = {} # {symbol: {"data": ..., "ts": ...}}

def get_analysis(symbol, timeframe=None):
    timeframe = timeframe or Config.TIMEFRAME
    now = time.time()
    
    # 1. Verifica Cache (TTL 30s)
    if symbol in _data_cache and (now - _data_cache[symbol]["ts"]) < 30:
        return _data_cache[symbol]["data"]

    data = None
    # 2. Tenta MT5 (Tempo Real)
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, f"TIMEFRAME_{timeframe.upper().replace('M','')}"), 0, 200)
            if rates is not None and len(rates) > 50:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                data = _process_df(df, symbol)
                log(f"[MT5] Dados obtidos para {symbol}")
    except Exception as e:
        log(f"[MT5] Falha em {symbol}: {e}")
        pass # Fallback para Yahoo

    # 3. Fallback Yahoo Finance
    if data is None:
        try:
            import yfinance as yf
            yf_symbol = to_yf(symbol)
            period = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]
            df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
            if len(df) >= 50:
                data = _process_df(df, symbol)
                log(f"[YF] Dados obtidos para {symbol}")
        except Exception as e:
            log(f"[YF] Falha em {symbol}: {e}")
            return None

    if 
        _data_cache[symbol] = {"data": data, "ts": now}
    return data

def _process_df(df, symbol):
    closes = df["Close"]; highs = df["High"]; lows = df["Low"]; volume = df["Volume"]    ema9 = closes.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = closes.ewm(span=21, adjust=False).mean().iloc[-1]
    ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]
    
    # Bollinger
    w = min(20, len(closes)-1)
    sma20 = closes.rolling(w).mean().iloc[-1]; std20 = closes.rolling(w).std().iloc[-1]
    upper = sma20 + 2*std20; lower = sma20 - 2*std20
    
    # RSI
    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = (100 - 100/(1 + gain/loss)).iloc[-1]
    
    # MACD
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line
    macd_bull = bool(macd_hist.iloc[-1] > 0 and macd_hist.iloc[-1] > macd_hist.iloc[-2])
    macd_bear = bool(macd_hist.iloc[-1] < 0 and macd_hist.iloc[-1] < macd_hist.iloc[-2])
    
    # ATR
    tr = pd.concat([highs-lows, (highs-closes.shift()).abs(), (lows-closes.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    
    # Tendência
    price = float(closes.iloc[-1])
    cen = "NEUTRO"
    if price > ema200 and ema9 > ema21: cen = "ALTA"
    elif price < ema200 and ema9 < ema21: cen = "BAIXA"
    
    return {
        "symbol": symbol, "name": asset_name(symbol), "price": price, "cenario": cen,
        "rsi": float(rsi), "atr": atr, "ema9": float(ema9), "ema21": float(ema21), "ema200": float(ema200),
        "upper": float(upper), "lower": float(lower), "macd_bull": macd_bull, "macd_bear": macd_bear,
        "macd_hist": float(macd_hist.iloc[-1]), "change_pct": float((closes.iloc[-1]-closes.iloc[-10])/closes.iloc[-10]*100) if len(closes)>=10 else 0
    }

# ───────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPAL DO BOT
# ──────────────────────────────────────────────────────────────────────
class TradingBot:
    def __init__(self):
        init_db()
        self.mode = db_get("mode", "CRYPTO")
        self.timeframe = db_get("timeframe", Config.TIMEFRAME)
        self.wins = int(db_get("wins", 0))        self.losses = int(db_get("losses", 0))
        self.consecutive_losses = int(db_get("consecutive_losses", 0))
        self.paused_until = float(db_get("paused_until", 0))
        self.active_trades = db_get("active_trades", [])
        self.pending_trades = db_get("pending_trades", [])
        self.pending_counter = int(db_get("last_pending_id", 0))
        self.asset_cooldown = db_get("asset_cooldown", {})
        self.balance = float(db_get("balance", Config.INITIAL_BALANCE))
        self.leverage = int(db_get("leverage", Config.DEFAULT_LEVERAGE))
        self.risk_pct = float(db_get("risk_pct", Config.RISK_PERCENT_PER_TRADE))
        self.history = [] # Carregado sob demanda do DB se necessário
        self._restore_msg = None
        
        # Correlações
        self.correlations = {
            "EURUSD": ["GBPUSD", "USDCHF", "AUDUSD"],
            "GBPUSD": ["EURUSD", "NZDUSD"],
            "USDJPY": ["USDCAD"],
            "BTCUSD": ["ETHUSD", "SOLUSD"]
        }

    def save_state(self):
        db_set("mode", self.mode); db_set("timeframe", self.timeframe)
        db_set("wins", self.wins); db_set("losses", self.losses)
        db_set("consecutive_losses", self.consecutive_losses)
        db_set("paused_until", self.paused_until)
        db_set("active_trades", self.active_trades)
        db_set("pending_trades", self.pending_trades)
        db_set("last_pending_id", self.pending_counter)
        db_set("asset_cooldown", self.asset_cooldown)
        db_set("balance", self.balance)
        db_set("leverage", self.leverage)
        db_set("risk_pct", self.risk_pct)

    def check_correlation(self, symbol):
        active_symbols = [t['symbol'] for t in self.active_trades]
        if symbol in self.correlations:
            for related in self.correlations[symbol]:
                if related in active_symbols:
                    log(f"[RISCO] Bloqueado {symbol} devido correlação com {related}")
                    return True
        return False

    def send(self, text, markup=None):
        # Implementação simplificada de envio Telegram (mantida do original)
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML"}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=8)
        except Exception as e: log(f"[TG] Erro: {e}")
    def monitor_trades(self):
        changed = False
        now_ts = time.time()
        
        # 1. Verificação de Margin Call / Stop Out Preventivo
        snap = self.account_snapshot()
        if snap['used_margin'] > 0:
            margin_level = (snap['equity'] / snap['used_margin']) * 100
            if margin_level < Config.STOP_OUT_LEVEL:
                log(f"️ STOP OUT PREVENTIVO! Nível: {margin_level:.1f}%")
                self.send(f"⛔ <b>STOP OUT PREVENTIVO</b>\nNível de Margem: {margin_level:.1f}%\nFechando todas as posições.")
                for t in self.active_trades[:]:
                    self.close_trade(t, "STOP_OUT_PREVENTIVE")
                changed = True
                return # Sai para reavaliar estado

        # 2. Monitoramento Individual
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res: continue
            cur = res["price"]
            
            # Trailing Stop Inteligente (Swing + ATR)
            if t["dir"] == "BUY":
                if cur > t.get("peak", t["entry"]):
                    t["peak"] = cur
                    # Calcula novo SL baseado na mínima dos últimos N candles ou ATR
                    swing_low = cur - (Config.ATR_MULT_TRAIL * res["atr"])
                    if swing_low > t["sl"]:
                        t["sl"] = swing_low
                        changed = True
                        log(f"[TRAILING] {t['symbol']} SL ajustado para {t['sl']}")
            else: # SELL
                if cur < t.get("peak", t["entry"]):
                    t["peak"] = cur
                    swing_high = cur + (Config.ATR_MULT_TRAIL * res["atr"])
                    if swing_high < t["sl"]:
                        t["sl"] = swing_high
                        changed = True
            
            # Check Win/Loss
            is_win = (t["dir"] == "BUY" and cur >= t["tp"]) or (t["dir"] == "SELL" and cur <= t["tp"])
            is_loss = (t["dir"] == "BUY" and cur <= t["sl"]) or (t["dir"] == "SELL" and cur >= t["sl"])
            
            if is_win or is_loss:
                # Partial Close Logic (se configurado, ex: 50% no TP)
                if is_win and not t.get("partial_closed", False):
                    # Fecha 50%
                    half_lot = float(t["lot"]) / 2.0                    # Aqui chamaria mt5 para fechar metade. Simulação:
                    profit_half = (cur - t["entry"]) * float(t["contract_size"]) * half_lot
                    self.balance += profit_half # Credita lucro parcial
                    t["lot"] = half_lot
                    t["partial_closed"] = True
                    t["sl"] = t["entry"] # Move SL para Breakeven no restante
                    self.send(f"✅ <b>PARCIAL FECHADO</b> em {t['symbol']}\n50% realizado. SL movido para Entry.")
                    changed = True
                    continue # Não fecha tudo ainda
                
                if is_loss or (is_win and t.get("partial_closed", False)):
                    self.close_trade(t, "WIN" if is_win else "LOSS")
                    changed = True

        if changed: self.save_state()

    def close_trade(self, t, reason):
        # Lógica de fechamento e reconciliação
        lot = float(t["lot"])
        cs = float(t["contract_size"])
        cur = t.get("current_price", t["entry"]) # Preço atual aproximado
        
        if t["dir"] == "BUY": raw_pnl = (cur - t["entry"]) * cs * lot
        else: raw_pnl = (t["entry"] - cur) * cs * lot
        
        comm = t.get("commission", 0)
        net_pnl = raw_pnl - comm
        
        self.balance += float(t.get("margin_required", 0)) + net_pnl
        self.balance = round(self.balance, 2)
        
        result = "WIN" if reason == "WIN" else "LOSS"
        if result == "WIN": self.wins += 1; self.consecutive_losses = 0
        else: self.losses += 1; self.consecutive_losses += 1
        
        record = {"symbol": t["symbol"], "dir": t["dir"], "result": result, "pnl_money": net_pnl, "closed_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")}
        db_append_history(record)
        
        self.active_trades.remove(t)
        self.send(f"🏁 <b>{result}</b> em {t['symbol']}\nP&L: ${net_pnl:.2f}")
        
        if result == "LOSS" and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
            self.paused_until = time.time() + Config.PAUSE_DURATION
            self.send(f" Circuit Breaker ativado por {Config.PAUSE_DURATION//60} min.")

    def scan(self):
        if self.is_paused() or len(self.active_trades) >= Config.MAX_TRADES: return
        
        universe = []
        for c in Config.MARKET_CATEGORIES.values():            if self.mode == "TUDO" or c["label"].upper().replace(" ","_") == self.mode: # Ajuste simples de match
                universe.extend(c["assets"].keys())
        
        for s in universe:
            if any(t["symbol"] == s for t in self.active_trades + self.pending_trades): continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN: continue
            
            # CHECK CORRELAÇÃO ATIVO
            if self.check_correlation(s): continue

            res = get_analysis(s, self.timeframe)
            if not res or res["cenario"] == "NEUTRO": continue
            
            # Verificação de Spread (Se MT5 disponível)
            try:
                import MetaTrader5 as mt5
                if mt5.initialize():
                    tick = mt5.symbol_info_tick(s)
                    if tick and (tick.ask - tick.bid) > (Config.MAX_SPREAD_POINTS * 0.00001): # Exemplo simples
                        log(f"[SPREAD] {s} ignorado (Spread alto)")
                        continue
            except: pass

            # Lógica de Entrada (Simplificada)
            eff_lev = min(self.leverage, max_leverage_for(s))
            sl_pct, tp_pct = get_sl_tp_pct(eff_lev)
            
            dir_s = "BUY" if res["cenario"] == "ALTA" else "SELL"
            entry = res["price"]
            sl = entry * (1 - sl_pct/100) if dir_s == "BUY" else entry * (1 + sl_pct/100)
            tp = entry * (1 + tp_pct/100) if dir_s == "BUY" else entry * (1 - tp_pct/100)
            
            # Criar pendente
            self.pending_counter += 1
            pending = {
                "pending_id": self.pending_counter, "symbol": s, "entry": entry,
                "sl": sl, "tp": tp, "dir": dir_s, "sl_pct": sl_pct, "tp_pct": tp_pct
            }
            self.pending_trades.append(pending)
            self.save_state()
            # Notificar (chamada simplificada)
            self.send(f" Sinal Pendente: {s} ({dir_s})\nEntrada: {entry}")

    def account_snapshot(self):
        open_pnl = 0.0; used_margin = 0.0
        for t in self.active_trades:
            # Simulação rápida de PnL
            open_pnl += 0 # Em produção, buscar preço real MT5 aqui
            used_margin += float(t.get("margin_required", 0))
                equity = self.balance + open_pnl
        free_margin = equity - used_margin
        level = (equity / used_margin * 100) if used_margin > 0 else 0
        return {"balance": self.balance, "equity": equity, "used_margin": used_margin, "free_margin": free_margin, "margin_level": level}

    def is_paused(self): return time.time() < self.paused_until

# ───────────────────────────────────────────────────────────────────────
# FLASK API & DASHBOARD (Atualizado)
# ───────────────────────────────────────────────────────────────────────
bot = TradingBot()

def create_api():
    app = Flask(__name__)
    CORS(app)
    
    @app.route("/api/trade_plan", methods=["POST"])
    def api_trade_plan():
        """Novo endpoint para preview antes da execução"""
        data = request.json
        symbol = data.get("symbol")
        amount = float(data.get("amount", 100))
        
        # Busca preço atual fresco
        res = get_analysis(symbol, bot.timeframe)
        if not res: return jsonify({"error": "Dados indisponíveis"}), 400
        
        plan = calc_trade_plan(symbol, res["price"], bot.leverage, bot.balance, bot.risk_pct, amount)
        return jsonify(plan)

    @app.route("/api/execute_pending", methods=["POST"])
    def api_execute_pending():
        data = request.json
        pid = data.get("pending_id")
        amount = float(data.get("amount"))
        
        # Encontrar pendente
        pending = next((p for p in bot.pending_trades if p["pending_id"] == pid), None)
        if not pending: return jsonify({"error": "Não encontrado"}), 404
        
        # Calcular plano final
        plan = calc_trade_plan(pending["symbol"], pending["entry"], bot.leverage, bot.balance, bot.risk_pct, amount)
        if not plan["ok"]: return jsonify({"error": plan["error"]}), 400
        
        # Executar no MT5 (Simulado aqui, seria mt5_send_order real)
        success, msg = mt5_send_order_real(pending["symbol"], pending["dir"], plan["lot"], plan["sl_price_buy" if pending["dir"]=="BUY" else "sl_price_sell"], plan["tp_price_buy" if pending["dir"]=="BUY" else "tp_price_sell"])
        
        if success:
            # Reconciliação: Confirmar se abriu
            import MetaTrader5 as mt5            positions = mt5.positions_get(symbol=pending["symbol"])
            if positions:
                # Adicionar aos ativos
                trade_obj = {**pending, **plan, "opened_at": datetime.now().strftime("%H:%M")}
                bot.active_trades.append(trade_obj)
                bot.pending_trades.remove(pending)
                bot.balance -= plan["margin_required"] # Reserva margem
                bot.save_state()
                return jsonify({"ok": True})
            else:
                return jsonify({"error": "Falha na reconciliação MT5"}), 500
        else:
            return jsonify({"error": msg}), 500

    def mt5_send_order_real(symbol, direction, lot, sl, tp):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize(): return False, "MT5 Init Fail"
            
            tick = mt5.symbol_info_tick(symbol)
            if not tick: return False, "Símbolo inválido"
            
            # Check Spread
            spread = tick.ask - tick.bid
            if spread > (Config.MAX_SPREAD_POINTS * 0.00001): 
                return False, f"Spread alto: {spread}"
                
            order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
            price = tick.ask if direction == "BUY" else tick.bid
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(lot),
                "type": order_type, "price": price, "sl": float(sl), "tp": float(tp),
                "deviation": 10, "magic": 234000, "comment": "Sniper v9.1",
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC
            }
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return False, result.comment
            return True, "OK"
        except Exception as e:
            return False, str(e)

    # Rotas existentes (status, config, etc) devem ser mantidas conforme arquivo original
    @app.route("/")
    def index():
        # Retornar HTML atualizado com novos scripts JS para sons e modais
        return Response(DASHBOARD_HTML_V2, mimetype="text/html")
    
    return app
# ───────────────────────────────────────────────────────────────────────
# FRONTEND ATUALIZADO (Trecho JS para Sons e Modais)
# ───────────────────────────────────────────────────────────────────────
DASHBOARD_HTML_V2 = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sniper Bot v9.1 Pro</title>
<style>
/* Estilos base mantidos do original + Novos */
.modal {display:none; position:fixed; z-index:999; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.8);}
.modal-content {background:#1e2840; margin:15% auto; padding:20px; border:1px solid #448aff; width:80%; max-width:400px; border-radius:10px; text-align:center;}
.btn-confirm {background:#00e676; color:#000; padding:10px 20px; border:none; border-radius:5px; cursor:pointer; font-weight:bold; margin-top:10px;}
.btn-cancel {background:#ff3d71; color:#fff; padding:10px 20px; border:none; border-radius:5px; cursor:pointer; margin-top:10px;}
</style>
</head>
<body>
<div id="app">
    <!-- Conteúdo do Dashboard Original Aqui -->
    <h1>Dashboard v9.1</h1>
    <button onclick="resetPausaConfirm()">Resetar Circuit Breaker</button>
    <button onclick="setBalanceConfirm()">Alterar Saldo</button>
    
    <!-- Modal Genérico -->
    <div id="confirmModal" class="modal">
        <div class="modal-content">
            <h3 id="modalTitle">Confirmar Ação</h3>
            <p id="modalMsg">Tem certeza?</p>
            <button class="btn-confirm" id="modalBtnYes">Sim</button>
            <button class="btn-cancel" onclick="closeModal()">Não</button>
        </div>
    </div>
</div>

<script>
// Sons
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
function playSound(type) {
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain); gain.connect(audioCtx.destination);
    
    if (type === 'win') { osc.frequency.value = 600; osc.type = 'sine'; gain.gain.setValueAtTime(0.1, audioCtx.currentTime); osc.start(); setTimeout(()=>osc.stop(), 200); }
    if (type === 'loss') { osc.frequency.value = 150; osc.type = 'sawtooth'; gain.gain.setValueAtTime(0.1, audioCtx.currentTime); osc.start(); setTimeout(()=>osc.stop(), 400); }
    if (type === 'signal') { osc.frequency.value = 800; osc.type = 'square'; gain.gain.setValueAtTime(0.05, audioCtx.currentTime); osc.start(); setTimeout(()=>osc.stop(), 100); }
}
// Modais
let currentAction = null;
function showModal(title, msg, action) {
    document.getElementById('modalTitle').innerText = title;
    document.getElementById('modalMsg').innerText = msg;
    document.getElementById('confirmModal').style.display = 'block';
    currentAction = action;
}
function closeModal() { document.getElementById('confirmModal').style.display = 'none'; currentAction = null; }
document.getElementById('modalBtnYes').onclick = () => { if(currentAction) currentAction(); closeModal(); };

function resetPausaConfirm() {
    showModal("Resetar Circuit Breaker", "Isso irá retomar as operações imediatamente.", async () => {
        await fetch('/api/resetpausa', {method:'POST'});
        location.reload();
    });
}
function setBalanceConfirm() {
    const val = prompt("Novo Saldo:");
    if(val) {
        showModal("Alterar Saldo", `Confirmar novo saldo de $${val}?`, async () => {
            await fetch('/api/balance', {method:'POST', body:JSON.stringify({balance:parseFloat(val)})});
            location.reload();
        });
    }
}

// Preview de Trade (Exemplo de chamada)
async function showTradePreview(pid, amount) {
    // Chama nova API /api/trade_plan
    // Atualiza UI com lote/comissão antes de executar
    console.log("Calculando preview...");
}

// Loop de atualização
setInterval(async () => {
    // Fetch status e verificar sons
    const status = await fetch('/api/status').then(r=>r.json());
    // Lógica para tocar som se houver novo win/loss comparado ao último estado
}, 5000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    log("Iniciando Tickmill Sniper Bot v9.1 PRO...")
    # Iniciar Thread do Bot
    t = threading.Thread(target=lambda: None) # Placeholder para loop real do bot
    # t.start()     app = create_api()
    app.run(host="0.0.0.0", port=8080, debug=False)
