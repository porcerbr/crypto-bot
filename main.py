# coding: utf-8
"""
TICKMILL SNIPER BOT v9.1 — PROFESSIONAL EDITION
══════════════════════════════════════════════════════════════════════════
Versão corrigida de sintaxe e indentação, preservando a estrutura original.
"""

import os
import time
import json
import math
import threading
import requests
import sqlite3
import logging
import pandas as pd
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────────
# CONFIGURAÇÕES GLOBAIS
# ───────────────────────────────────────────────────────────────────────
class Config:
    BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ = timezone(timedelta(hours=-3))

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

    SL_TP_BASE_MULTIPLIER = 250.0
    SL_MAX_PCT = 3.0
    SL_MIN_PCT = 0.2
    TP_SL_RATIO = 2.5
    DYNAMIC_RR_ENABLED = True
    DYNAMIC_RR_TIERS = [(3, 3.0, "⚡ Forte"), (5, 3.5, "🔥 Muito Forte"), (7, 4.5, "💎 Perfeito")]

    ATR_PERIOD = 14
    ATR_MULT_SL = 1.5
    ATR_MULT_TP = 3.75
    ATR_MULT_TRAIL = 1.2
    MAX_CONSECUTIVE_LOSSES = 2
    PAUSE_DURATION = 3600
    ADX_MIN = 22
    MAX_TRADES = 3
    ASSET_COOLDOWN = 3600
    MIN_CONFLUENCE = 5
    MIN_CONFLUENCE_CT = 4
    REVERSAL_MIN_SCORE = 6
    REVERSAL_COOLDOWN = 2700
    REVERSAL_REQUIRE_TREND = True
    REVERSAL_RSI_SELL = 75
    REVERSAL_RSI_BUY = 25
    REVERSAL_BAND_BUFFER = 0.997
    RADAR_COOLDOWN = 1800
    GATILHO_COOLDOWN = 300
    TRENDS_INTERVAL = 60
    NEWS_INTERVAL = 7200
    SCAN_INTERVAL = 15

    BROKER_NAME = "Tickmill"
    BROKER_PLATFORM = "MT5"
    ACCOUNT_TYPE = "RAW"
    BASE_CURRENCY = "USD"
    COMMISSION_PER_LOT_SIDE = {"FOREX": 3.0, "COMMODITIES": 3.0, "INDICES": 0.0, "CRYPTO": 0.0}
    MAX_LEVERAGE_BY_CAT = {"FOREX": 1000, "COMMODITIES": 500, "INDICES": 100, "CRYPTO": 200}
    MAX_LEVERAGE_BY_SYM = {
        "XAUUSD": 1000, "XAGUSD": 125, "XTIUSD": 100, "BRENT": 100, "NATGAS": 100, "COPPER": 100,
        "US500": 100, "USTEC": 100, "US30": 100, "DE40": 100, "UK100": 100, "JP225": 100,
        "AUS200": 100, "STOXX50": 100
    }

    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "500.0"))
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    RISK_PERCENT_PER_TRADE = float(os.getenv("RISK_PERCENT_PER_TRADE", "2.0"))
    MARGIN_CALL_LEVEL = 100.0
    STOP_OUT_LEVEL = 30.0
    MIN_LOT = 0.01
    LOT_STEP = 0.01
    MAX_SPREAD_POINTS = 30

    CONTRACT_SIZES = {"FOREX": 100000, "CRYPTO": 1, "COMMODITIES": 100, "INDICES": 1}
    CONTRACT_SIZES_SPECIFIC = {
        "XAUUSD": 100, "XAGUSD": 5000, "XTIUSD": 1000, "BRENT": 1000,
        "NATGAS": 1000, "COPPER": 1000
    }

    TIMEFRAMES = {
        "1m": ("Agressivo", "7d"), "5m": ("Alto", "5d"), "15m": ("Moderado", "5d"),
        "30m": ("Conservador", "5d"), "1h": ("Seguro", "60d"), "4h": ("Muito Seguro", "60d")
    }
    TIMEFRAME = "15m"

    STATE_DB = "bot_state.db"
    USE_KELLY_CRITERION = True
    KELLY_FRACTION = 0.2
    NEWS_FILTER_IMPACT = ["HIGH"]
    CORRELATION_LIMIT = 0.7


TICKMILL_TO_YF = {
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD", "SOLUSD": "SOL-USD", "BNBUSD": "BNB-USD",
    "XRPUSD": "XRP-USD", "ADAUSD": "ADA-USD", "DOGEUSD": "DOGE-USD", "LTCUSD": "LTC-USD",
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "XTIUSD": "CL=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "COPPER": "HG=F", "US500": "ES=F", "USTEC": "NQ=F", "US30": "YM=F",
    "DE40": "^GDAXI", "UK100": "^FTSE", "JP225": "^N225", "AUS200": "^AXJO", "STOXX50": "^STOXX50E",
}


def to_yf(s):
    return TICKMILL_TO_YF.get(s, f"{s}=X" if len(s) == 6 and s.isalpha() else s)


def asset_cat(s):
    for cat, info in Config.MARKET_CATEGORIES.items():
        if s in info["assets"]:
            return cat
    return "CRYPTO"


def asset_name(s):
    for info in Config.MARKET_CATEGORIES.values():
        if s in info["assets"]:
            return info["assets"][s]
    return s


def contract_size_for(symbol):
    return Config.CONTRACT_SIZES_SPECIFIC.get(symbol, Config.CONTRACT_SIZES.get(asset_cat(symbol), 1))


def max_leverage_for(symbol):
    return Config.MAX_LEVERAGE_BY_SYM.get(symbol, Config.MAX_LEVERAGE_BY_CAT.get(asset_cat(symbol), 100))


def mt5_timeframe_const(timeframe: str):
    tf = (timeframe or "15m").lower().strip()
    mapping = {
        "1m": "TIMEFRAME_M1",
        "5m": "TIMEFRAME_M5",
        "15m": "TIMEFRAME_M15",
        "30m": "TIMEFRAME_M30",
        "1h": "TIMEFRAME_H1",
        "4h": "TIMEFRAME_H4",
        "1d": "TIMEFRAME_D1",
    }
    return mapping.get(tf, "TIMEFRAME_M15")


# ───────────────────────────────────────────────────────────────────────
# BANCO DE DADOS
# ───────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(Config.STATE_DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS state (
        key TEXT PRIMARY KEY, value TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT
    )""")

    defaults = {
        "last_pending_id": "0",
        "wins": "0",
        "losses": "0",
        "consecutive_losses": "0",
        "balance": str(Config.INITIAL_BALANCE),
        "leverage": str(Config.DEFAULT_LEVERAGE),
        "risk_pct": str(Config.RISK_PERCENT_PER_TRADE),
        "mode": "CRYPTO",
        "timeframe": Config.TIMEFRAME,
        "paused_until": "0",
        "active_trades": "[]",
        "pending_trades": "[]",
        "asset_cooldown": "{}",
        "trend_cache": "{}",
        "history_list": "[]",
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
        raw = row[0]
        try:
            return json.loads(raw)
        except Exception:
            return raw
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
    c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 500)")
    conn.commit()
    conn.close()


# ───────────────────────────────────────────────────────────────────────
# CÁLCULOS FINANCEIROS & RISCO
# ───────────────────────────────────────────────────────────────────────
def fmt(p: float) -> str:
    if not p:
        return "0"
    if p >= 10000:
        return f"{p:,.2f}"
    if p >= 1000:
        return f"{p:.2f}"
    if p >= 10:
        return f"{p:.4f}"
    if p >= 1:
        return f"{p:.5f}"
    return f"{p:.6f}"


def symbol_profile(symbol):
    cat = asset_cat(symbol)
    cs = contract_size_for(symbol)
    if cat == "FOREX":
        return {"kind": "FX", "base": symbol[:3], "quote": symbol[3:], "contract_size": cs}
    if cat == "COMMODITIES":
        return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": cs}
    if cat == "INDICES":
        return {"kind": "INDEX", "base": "USD", "quote": "USD", "contract_size": cs}
    if cat == "CRYPTO":
        return {"kind": "CRYPTO", "base": "USD", "quote": "USD", "contract_size": cs}
    return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": cs}


def currency_to_usd(currency):
    currency = (currency or "USD").upper()
    if currency == "USD":
        return 1.0
    pairs = {
        "EUR": "EURUSD=X",
        "GBP": "GBPUSD=X",
        "JPY": "USDJPY=X",
        "CAD": "USDCAD=X",
        "CHF": "USDCHF=X",
        "AUD": "AUDUSD=X",
    }
    ticker = pairs.get(currency)
    if not ticker:
        return 1.0
    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period="1d", interval="1m")
        if len(df):
            px = float(df["Close"].iloc[-1])
            if currency in ["CAD", "CHF", "JPY"]:
                return 1.0 / px if px else 1.0
            return px
    except Exception:
        pass
    return 1.0


def calc_margin(symbol, price, leverage, lot):
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    kind = profile["kind"]
    base = profile["base"]
    quote = profile["quote"]
    lot = float(lot)
    leverage = max(1.0, float(leverage))

    if kind == "FX":
        if quote == "USD":
            notional = lot * cs * float(price)
        elif base == "USD":
            notional = lot * cs
        else:
            notional = lot * cs * currency_to_usd(base)
    else:
        notional = lot * cs * float(price)
    return round(notional / leverage, 2)


def commission_for(symbol, lot):
    if Config.ACCOUNT_TYPE not in ("RAW", "PRO"):
        return 0.0
    rate = Config.COMMISSION_PER_LOT_SIDE.get(asset_cat(symbol), 0.0)
    return round(rate * float(lot) * 2, 2)


def get_sl_tp_pct(leverage, rr_ratio=None):
    leverage = max(1, int(leverage))
    sl = Config.SL_TP_BASE_MULTIPLIER / leverage
    sl = min(Config.SL_MAX_PCT, max(Config.SL_MIN_PCT, sl))
    rr = rr_ratio if rr_ratio is not None else Config.TP_SL_RATIO
    return round(sl, 2), round(sl * rr, 2)


def normalize_lot(lot):
    if lot <= 0:
        return 0.0
    step = Config.LOT_STEP
    return round(math.floor(lot / step) * step, 4)


def calc_lot_from_margin(symbol, entry, leverage, margin_usd):
    entry = float(entry)
    leverage = max(1.0, float(leverage))
    margin_usd = float(margin_usd)
    if margin_usd <= 0 or entry <= 0:
        return Config.MIN_LOT
    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    if profile["kind"] == "FX" and profile["quote"] == "USD":
        lot = (margin_usd * leverage) / (cs * entry)
    elif profile["kind"] == "FX" and profile["base"] == "USD":
        lot = (margin_usd * leverage) / cs
    else:
        lot = (margin_usd * leverage) / (cs * entry)
    return max(Config.MIN_LOT, normalize_lot(lot))


def calc_lot_from_risk(symbol, entry, sl_price, balance, risk_pct):
    risk_money = float(balance) * (float(risk_pct) / 100.0)
    sl_distance = abs(float(entry) - float(sl_price))
    if sl_distance <= 0 or risk_money <= 0:
        return Config.MIN_LOT

    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    kind = profile["kind"]

    if kind == "FX" and profile["quote"] == "USD":
        loss_per_lot = sl_distance * cs
    elif kind == "FX" and profile["base"] == "USD":
        loss_per_lot = sl_distance * cs * currency_to_usd(profile["quote"])
    else:
        loss_per_lot = sl_distance * cs

    if loss_per_lot <= 0:
        return Config.MIN_LOT

    lot = risk_money / loss_per_lot
    step = Config.LOT_STEP
    return round(math.floor(lot / step) * step, 4)


def calc_trade_plan(symbol, entry, leverage, balance, risk_pct, margin_usd):
    entry = float(entry)
    leverage = max(1.0, min(float(leverage), float(max_leverage_for(symbol))))
    balance = float(balance)
    risk_pct = float(risk_pct)
    margin_usd = float(margin_usd)

    if margin_usd <= 0 or entry <= 0 or balance <= 0:
        return {"ok": False, "error": "Dados inválidos."}

    sl_pct, tp_pct = get_sl_tp_pct(leverage)
    sl_price_buy = round(entry * (1 - sl_pct / 100), 5)
    tp_price_buy = round(entry * (1 + tp_pct / 100), 5)
    sl_price_sell = round(entry * (1 + sl_pct / 100), 5)
    tp_price_sell = round(entry * (1 - tp_pct / 100), 5)

    lot_by_margin = calc_lot_from_margin(symbol, entry, leverage, margin_usd)
    lot_by_risk = calc_lot_from_risk(symbol, entry, sl_price_buy, balance, risk_pct)
    final_lot = normalize_lot(min(lot_by_margin, lot_by_risk))

    if final_lot < Config.MIN_LOT:
        return {"ok": False, "error": "Valor insuficiente para lote mínimo."}

    margin_required = calc_margin(symbol, entry, leverage, final_lot)
    commission = commission_for(symbol, final_lot)

    profile = symbol_profile(symbol)
    cs = float(profile["contract_size"])
    sl_dist = abs(entry - sl_price_buy)
    risk_money = sl_dist * cs * final_lot
    tp_dist = abs(tp_price_buy - entry)
    potential_profit = (tp_dist * cs * final_lot) - commission

    return {
        "ok": True,
        "symbol": symbol,
        "entry": entry,
        "leverage": leverage,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "sl_price_buy": sl_price_buy,
        "tp_price_buy": tp_price_buy,
        "sl_price_sell": sl_price_sell,
        "tp_price_sell": tp_price_sell,
        "lot": final_lot,
        "margin_required": margin_required,
        "risk_money": round(risk_money, 2),
        "commission": commission,
        "potential_profit": round(potential_profit, 2),
        "ratio": round(tp_pct / sl_pct, 2) if sl_pct > 0 else 0,
        "contract_size": cs,
    }


# ───────────────────────────────────────────────────────────────────────
# ANÁLISE TÉCNICA
# ───────────────────────────────────────────────────────────────────────
_data_cache = {}


def _process_df(df, symbol):
    closes = df["Close"]
    highs = df["High"]
    lows = df["Low"]
    volume = df["Volume"] if "Volume" in df.columns else pd.Series([0] * len(df), index=df.index)

    ema9 = closes.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = closes.ewm(span=21, adjust=False).mean().iloc[-1]
    ema200 = closes.ewm(span=min(200, max(2, len(closes) - 1)), adjust=False).mean().iloc[-1]

    w = min(20, max(2, len(closes) - 1))
    sma20 = closes.rolling(w).mean().iloc[-1]
    std20 = closes.rolling(w).std().iloc[-1]
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20

    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = (100 - 100 / (1 + rs)).iloc[-1]
    if pd.isna(rsi):
        rsi = 50.0

    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line
    last_hist = float(macd_hist.iloc[-1])
    prev_hist = float(macd_hist.iloc[-2]) if len(macd_hist) > 1 else last_hist
    macd_bull = bool(last_hist > 0 and last_hist > prev_hist)
    macd_bear = bool(last_hist < 0 and last_hist < prev_hist)

    tr = pd.concat([highs - lows, (highs - closes.shift()).abs(), (lows - closes.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])

    price = float(closes.iloc[-1])
    cen = "NEUTRO"
    if price > ema200 and ema9 > ema21:
        cen = "ALTA"
    elif price < ema200 and ema9 < ema21:
        cen = "BAIXA"

    change_pct = 0.0
    if len(closes) >= 10 and float(closes.iloc[-10]) != 0:
        change_pct = float((closes.iloc[-1] - closes.iloc[-10]) / closes.iloc[-10] * 100)

    return {
        "symbol": symbol,
        "name": asset_name(symbol),
        "price": price,
        "cenario": cen,
        "rsi": float(rsi),
        "atr": atr,
        "ema9": float(ema9),
        "ema21": float(ema21),
        "ema200": float(ema200),
        "upper": float(upper),
        "lower": float(lower),
        "macd_bull": macd_bull,
        "macd_bear": macd_bear,
        "macd_hist": last_hist,
        "change_pct": change_pct,
    }


def get_analysis(symbol, timeframe=None):
    timeframe = timeframe or Config.TIMEFRAME
    now = time.time()

    if symbol in _data_cache and (now - _data_cache[symbol]["ts"]) < 30:
        return _data_cache[symbol]["data"]

    data = None

    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            tf_name = mt5_timeframe_const(timeframe)
            tf = getattr(mt5, tf_name, mt5.TIMEFRAME_M15)
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, 200)
            if rates is not None and len(rates) > 50:
                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                if "tick_volume" in df.columns and "Volume" not in df.columns:
                    df["Volume"] = df["tick_volume"]
                data = _process_df(df, symbol)
                log.info("[MT5] Dados obtidos para %s", symbol)
    except Exception as e:
        log.warning("[MT5] Falha em %s: %s", symbol, e)

    if data is None:
        try:
            import yfinance as yf
            yf_symbol = to_yf(symbol)
            period = Config.TIMEFRAMES.get(timeframe, ("", "5d"))[1]
            df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
            if len(df) >= 50:
                data = _process_df(df, symbol)
                log.info("[YF] Dados obtidos para %s", symbol)
        except Exception as e:
            log.warning("[YF] Falha em %s: %s", symbol, e)
            return None

    if data is not None:
        _data_cache[symbol] = {"data": data, "ts": now}
    return data


# ───────────────────────────────────────────────────────────────────────
# CLASSE PRINCIPAL DO BOT
# ───────────────────────────────────────────────────────────────────────
class TradingBot:
    def __init__(self):
        init_db()
        self.mode = db_get("mode", "CRYPTO")
        self.timeframe = db_get("timeframe", Config.TIMEFRAME)
        self.wins = int(db_get("wins", 0))
        self.losses = int(db_get("losses", 0))
        self.consecutive_losses = int(db_get("consecutive_losses", 0))
        self.paused_until = float(db_get("paused_until", 0))
        self.active_trades = db_get("active_trades", [])
        self.pending_trades = db_get("pending_trades", [])
        self.pending_counter = int(db_get("last_pending_id", 0))
        self.asset_cooldown = db_get("asset_cooldown", {})
        self.balance = float(db_get("balance", Config.INITIAL_BALANCE))
        self.leverage = int(db_get("leverage", Config.DEFAULT_LEVERAGE))
        self.risk_pct = float(db_get("risk_pct", Config.RISK_PERCENT_PER_TRADE))
        self.history = []
        self._restore_msg = None

        self.correlations = {
            "EURUSD": ["GBPUSD", "USDCHF", "AUDUSD"],
            "GBPUSD": ["EURUSD", "NZDUSD"],
            "USDJPY": ["USDCAD"],
            "BTCUSD": ["ETHUSD", "SOLUSD"],
        }

    def save_state(self):
        db_set("mode", self.mode)
        db_set("timeframe", self.timeframe)
        db_set("wins", self.wins)
        db_set("losses", self.losses)
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
        active_symbols = [t["symbol"] for t in self.active_trades]
        if symbol in self.correlations:
            for related in self.correlations[symbol]:
                if related in active_symbols:
                    log.info("[RISCO] Bloqueado %s devido correlação com %s", symbol, related)
                    return True
        return False

    def send(self, text, markup=None):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML"}
        if markup:
            payload["reply_markup"] = json.dumps(markup)
        try:
            requests.post(url, json=payload, timeout=8)
        except Exception as e:
            log.warning("[TG] Erro: %s", e)

    def is_paused(self):
        return time.time() < self.paused_until

    def account_snapshot(self):
        open_pnl = 0.0
        used_margin = 0.0
        for t in self.active_trades:
            open_pnl += 0.0
            used_margin += float(t.get("margin_required", 0))
        equity = self.balance + open_pnl
        free_margin = equity - used_margin
        level = (equity / used_margin * 100) if used_margin > 0 else 0
        return {
            "balance": self.balance,
            "equity": equity,
            "used_margin": used_margin,
            "free_margin": free_margin,
            "margin_level": level,
        }

    def close_trade(self, t, reason):
        lot = float(t["lot"])
        cs = float(t["contract_size"])
        cur = float(t.get("current_price", t["entry"]))

        if t["dir"] == "BUY":
            raw_pnl = (cur - t["entry"]) * cs * lot
        else:
            raw_pnl = (t["entry"] - cur) * cs * lot

        comm = float(t.get("commission", 0))
        net_pnl = raw_pnl - comm

        self.balance += float(t.get("margin_required", 0)) + net_pnl
        self.balance = round(self.balance, 2)

        result = "WIN" if reason == "WIN" else "LOSS"
        if result == "WIN":
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1

        record = {
            "symbol": t["symbol"],
            "dir": t["dir"],
            "result": result,
            "pnl_money": net_pnl,
            "closed_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
        }
        db_append_history(record)

        if t in self.active_trades:
            self.active_trades.remove(t)

        self.send(f"🏁 <b>{result}</b> em {t['symbol']}\nP&L: ${net_pnl:.2f}")

        if result == "LOSS" and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
            self.paused_until = time.time() + Config.PAUSE_DURATION
            self.send(f"⛔ Circuit Breaker ativado por {Config.PAUSE_DURATION // 60} min.")

    def monitor_trades(self):
        changed = False
        snap = self.account_snapshot()

        if snap["used_margin"] > 0:
            margin_level = (snap["equity"] / snap["used_margin"]) * 100
            if margin_level < Config.STOP_OUT_LEVEL:
                log.warning("STOP OUT PREVENTIVO! Nível: %.1f%%", margin_level)
                self.send(f"⛔ <b>STOP OUT PREVENTIVO</b>\nNível de Margem: {margin_level:.1f}%\nFechando todas as posições.")
                for t in self.active_trades[:]:
                    self.close_trade(t, "STOP_OUT_PREVENTIVE")
                self.save_state()
                return

        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res:
                continue

            cur = res["price"]
            t["current_price"] = cur

            if t["dir"] == "BUY":
                if cur > t.get("peak", t["entry"]):
                    t["peak"] = cur
                    swing_low = cur - (Config.ATR_MULT_TRAIL * res["atr"])
                    if swing_low > t["sl"]:
                        t["sl"] = swing_low
                        changed = True
                        log.info("[TRAILING] %s SL ajustado para %s", t["symbol"], t["sl"])
            else:
                if cur < t.get("peak", t["entry"]):
                    t["peak"] = cur
                    swing_high = cur + (Config.ATR_MULT_TRAIL * res["atr"])
                    if swing_high < t["sl"]:
                        t["sl"] = swing_high
                        changed = True

            is_win = (t["dir"] == "BUY" and cur >= t["tp"]) or (t["dir"] == "SELL" and cur <= t["tp"])
            is_loss = (t["dir"] == "BUY" and cur <= t["sl"]) or (t["dir"] == "SELL" and cur >= t["sl"])

            if is_win or is_loss:
                if is_win and not t.get("partial_closed", False):
                    half_lot = float(t["lot"]) / 2.0
                    profit_half = (cur - t["entry"]) * float(t["contract_size"]) * half_lot
                    self.balance += profit_half
                    t["lot"] = half_lot
                    t["partial_closed"] = True
                    t["sl"] = t["entry"]
                    self.send(f"✅ <b>PARCIAL FECHADO</b> em {t['symbol']}\n50% realizado. SL movido para Entry.")
                    changed = True
                    continue

                if is_loss or (is_win and t.get("partial_closed", False)):
                    self.close_trade(t, "WIN" if is_win else "LOSS")
                    changed = True

        if changed:
            self.save_state()

    def scan(self):
        if self.is_paused() or len(self.active_trades) >= Config.MAX_TRADES:
            return

        universe = []
        for c in Config.MARKET_CATEGORIES.values():
            if self.mode == "TUDO" or c["label"].upper().replace(" ", "_") == str(self.mode).upper():
                universe.extend(c["assets"].keys())

        for s in universe:
            if any(t["symbol"] == s for t in self.active_trades + self.pending_trades):
                continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN:
                continue
            if self.check_correlation(s):
                continue

            res = get_analysis(s, self.timeframe)
            if not res or res["cenario"] == "NEUTRO":
                continue

            try:
                import MetaTrader5 as mt5
                if mt5.initialize():
                    tick = mt5.symbol_info_tick(s)
                    if tick and (tick.ask - tick.bid) > (Config.MAX_SPREAD_POINTS * 0.00001):
                        log.info("[SPREAD] %s ignorado (Spread alto)", s)
                        continue
            except Exception:
                pass

            eff_lev = min(self.leverage, max_leverage_for(s))
            sl_pct, tp_pct = get_sl_tp_pct(eff_lev)

            dir_s = "BUY" if res["cenario"] == "ALTA" else "SELL"
            entry = res["price"]
            sl = entry * (1 - sl_pct / 100) if dir_s == "BUY" else entry * (1 + sl_pct / 100)
            tp = entry * (1 + tp_pct / 100) if dir_s == "BUY" else entry * (1 - tp_pct / 100)

            self.pending_counter += 1
            pending = {
                "pending_id": self.pending_counter,
                "symbol": s,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "dir": dir_s,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
            }
            self.pending_trades.append(pending)
            self.save_state()
            self.send(f"📌 Sinal Pendente: {s} ({dir_s})\nEntrada: {entry}")


# ───────────────────────────────────────────────────────────────────────
# FLASK API & DASHBOARD
# ───────────────────────────────────────────────────────────────────────
bot = TradingBot()

DASHBOARD_HTML_V2 = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sniper Bot v9.1 Pro</title>
<style>
.modal {display:none; position:fixed; z-index:999; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.8);}
.modal-content {background:#1e2840; margin:15% auto; padding:20px; border:1px solid #448aff; width:80%; max-width:400px; border-radius:10px; text-align:center;}
.btn-confirm {background:#00e676; color:#000; padding:10px 20px; border:none; border-radius:5px; cursor:pointer; font-weight:bold; margin-top:10px;}
.btn-cancel {background:#ff3d71; color:#fff; padding:10px 20px; border:none; border-radius:5px; cursor:pointer; margin-top:10px;}
</style>
</head>
<body>
<div id="app">
    <h1>Dashboard v9.1</h1>
    <button onclick="resetPausaConfirm()">Resetar Circuit Breaker</button>
    <button onclick="setBalanceConfirm()">Alterar Saldo</button>

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
            await fetch('/api/balance', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({balance:parseFloat(val)})});
            location.reload();
        });
    }
}

async function showTradePreview(pid, amount) {
    console.log("Calculando preview...");
}

setInterval(async () => {
    const status = await fetch('/api/status').then(r=>r.json());
}, 5000);
</script>
</body>
</html>
"""


def create_api():
    app = Flask(__name__)
    CORS(app)

    def mt5_send_order_real(symbol, direction, lot, sl, tp):
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                return False, "MT5 Init Fail"

            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return False, "Símbolo inválido"

            spread = tick.ask - tick.bid
            if spread > (Config.MAX_SPREAD_POINTS * 0.00001):
                return False, f"Spread alto: {spread}"

            order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
            price = tick.ask if direction == "BUY" else tick.bid

            request_mt5 = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot),
                "type": order_type,
                "price": price,
                "sl": float(sl),
                "tp": float(tp),
                "deviation": 10,
                "magic": 234000,
                "comment": "Sniper v9.1",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request_mt5)
            if result is None:
                return False, "order_send retornou None"
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return False, result.comment
            return True, "OK"
        except Exception as e:
            return False, str(e)

    @app.route("/api/trade_plan", methods=["POST"])
    def api_trade_plan():
        data = request.json or {}
        symbol = data.get("symbol")
        amount = float(data.get("amount", 100))

        res = get_analysis(symbol, bot.timeframe)
        if not res:
            return jsonify({"error": "Dados indisponíveis"}), 400

        plan = calc_trade_plan(symbol, res["price"], bot.leverage, bot.balance, bot.risk_pct, amount)
        return jsonify(plan)

    @app.route("/api/execute_pending", methods=["POST"])
    def api_execute_pending():
        data = request.json or {}
        pid = data.get("pending_id")
        amount = float(data.get("amount", 0))

        pending = next((p for p in bot.pending_trades if p["pending_id"] == pid), None)
        if not pending:
            return jsonify({"error": "Não encontrado"}), 404

        plan = calc_trade_plan(pending["symbol"], pending["entry"], bot.leverage, bot.balance, bot.risk_pct, amount)
        if not plan["ok"]:
            return jsonify({"error": plan["error"]}), 400

        sl_key = "sl_price_buy" if pending["dir"] == "BUY" else "sl_price_sell"
        tp_key = "tp_price_buy" if pending["dir"] == "BUY" else "tp_price_sell"

        success, msg = mt5_send_order_real(
            pending["symbol"],
            pending["dir"],
            plan["lot"],
            plan[sl_key],
            plan[tp_key],
        )

        if success:
            try:
                import MetaTrader5 as mt5
                positions = mt5.positions_get(symbol=pending["symbol"])
                if positions:
                    trade_obj = {**pending, **plan, "opened_at": datetime.now().strftime("%H:%M")}
                    bot.active_trades.append(trade_obj)
                    bot.pending_trades.remove(pending)
                    bot.balance -= plan["margin_required"]
                    bot.save_state()
                    return jsonify({"ok": True})
                return jsonify({"error": "Falha na reconciliação MT5"}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        return jsonify({"error": msg}), 500

    @app.route("/api/status", methods=["GET"])
    def api_status():
        snap = bot.account_snapshot()
        return jsonify({
            "mode": bot.mode,
            "timeframe": bot.timeframe,
            "wins": bot.wins,
            "losses": bot.losses,
            "consecutive_losses": bot.consecutive_losses,
            "paused": bot.is_paused(),
            "paused_until": bot.paused_until,
            "balance": bot.balance,
            "active_trades": bot.active_trades,
            "pending_trades": bot.pending_trades,
            "snapshot": snap,
        })

    @app.route("/api/resetpausa", methods=["POST"])
    def api_resetpausa():
        bot.paused_until = 0
        bot.consecutive_losses = 0
        bot.save_state()
        return jsonify({"ok": True})

    @app.route("/api/balance", methods=["POST"])
    def api_balance():
        data = request.json or {}
        balance = data.get("balance")
        if balance is None:
            return jsonify({"error": "Saldo ausente"}), 400
        try:
            bot.balance = float(balance)
            bot.save_state()
            return jsonify({"ok": True, "balance": bot.balance})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/")
    def index():
        return Response(DASHBOARD_HTML_V2, mimetype="text/html")

    return app


if __name__ == "__main__":
    log.info("Iniciando Tickmill Sniper Bot v9.1 PRO...")
    app = create_api()
    app.run(host="0.0.0.0", port=8080, debug=False)
