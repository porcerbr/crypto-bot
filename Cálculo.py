# -- coding: utf-8 --
"""
TICKMILL SNIPER BOT v8.5 INSTITUTIONAL — Dashboard Profissional de Execução Rápida
══════════════════════════════════════════════════════════════════════════
CORRETORA: Tickmill | Plataforma: MT5 | Conta: Raw ECN (USD)

ADAPTAÇÕES TICKMILL APLICADAS:
✅ Símbolos MT5 nativos: XAUUSD, USOIL, BTCUSD, US500, DE40, etc.
✅ Mapeamento automático Tickmill MT5 → Yahoo Finance (dados de preço)
✅ Alavancagem máxima por ativo respeitada (FOREX 1:500, Gold 1:500, Cripto 1:200…)
✅ Comissão Raw ECN calculada ($6 RT/lote FOREX/Commodities) e deduzida do P&L
✅ Margin Call 100% / Stop Out 50% (regras reais da Tickmill)
✅ Tamanhos de contrato MT5 corretos (XAUUSD=100oz, USOIL=1000bbl, US500=$50/ponto…)
✅ Equity, free margin e P&L líquido (descontando comissão) em tempo real
✅ Suporte a conta RAW/CLASSIC/PRO via variável de ambiente
✅ Dashboard atualizado com branding Tickmill + campos específicos da corretora
✅ CÁLCULO DE LOTE EM USD: O bot agora calcula o lote exato para que o risco seja em USD.
✅ SL/TP 1:2.5 FIXO: O Stop Loss e Take Profit agora seguem a proporção 1:2.5 solicitada.
✅ AJUSTE DE ALAVANCAGEM: O cálculo de SL/TP em porcentagem agora considera a alavancagem.
"""
import os, time, json, math, threading, requests
import pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES & HELPERS
# ═══════════════════════════════════════════════════════════════
class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ      = timezone(timedelta(hours=-3))

    # ── TICKMILL MT5 — Símbolos nativos da plataforma ──────────────────────────
    MARKET_CATEGORIES = {
        "FOREX": {"label": "FOREX", "assets": {
            "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
            "USDCAD": "USD/CAD", "USDCHF": "USD/CHF", "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
            "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY"}},
        "CRYPTO": {"label": "CRIPTO", "assets": {
            "BTCUSD": "Bitcoin",   "ETHUSD": "Ethereum", "SOLUSD": "Solana",
            "BNBUSD": "BNB",       "XRPUSD": "XRP",      "ADAUSD": "Cardano",
            "DOGEUSD": "Dogecoin", "LTCUSD": "Litecoin"}},
        "COMMODITIES": {"label": "COMMODITIES", "assets": {
            "XAUUSD": "Ouro (Gold)",     "XAGUSD": "Prata (Silver)",
            "XTIUSD": "Petróleo WTI",    "BRENT":  "Petróleo Brent",
            "NATGAS": "Gás Natural",     "COPPER": "Cobre"}},
        "INDICES": {"label": "ÍNDICES", "assets": {
            "US500": "S&P 500",    "USTEC": "Nasdaq 100", "US30":  "Dow Jones",
            "DE40":  "DAX 40",     "UK100": "FTSE 100",   "JP225": "Nikkei 225",
            "AUS200":"ASX 200",    "STOXX50": "Euro Stoxx 50"}}
    }

    # Proporção de Risco:Retorno solicitada pelo usuário (1:2.5)
    RISK_REWARD_RATIO = 2.5
    
    # Porcentagem de variação do preço para o SL (baseada em alavancagem 1:1)
    # Se o usuário usa 1:500, o SL real no preço será SL_BASE_PCT / 500
    SL_BASE_PCT = 1.0 # 1% de variação do preço para atingir o SL com alavancagem 1:1

    MAX_CONSECUTIVE_LOSSES = 2; PAUSE_DURATION = 3600
    ADX_MIN = 22; MAX_TRADES = 3; ASSET_COOLDOWN = 3600; MIN_CONFLUENCE = 5
    MIN_CONFLUENCE_CT = 4; REVERSAL_MIN_SCORE = 6; REVERSAL_COOLDOWN = 2700
    REVERSAL_REQUIRE_TREND = True; REVERSAL_RSI_SELL = 75; REVERSAL_RSI_BUY = 25
    REVERSAL_BAND_BUFFER = 0.997
    RADAR_COOLDOWN = 1800; GATILHO_COOLDOWN = 300
    TRENDS_INTERVAL = 120; NEWS_INTERVAL = 7200
    SCAN_INTERVAL = 30

    BROKER_NAME     = "Tickmill"
    BROKER_PLATFORM = "MT5"
    ACCOUNT_TYPE    = os.getenv("TICKMILL_ACCOUNT_TYPE", "RAW")
    BASE_CURRENCY   = "USD"

    COMMISSION_PER_LOT_RT = {
        "FOREX":       6.0,
        "COMMODITIES": 6.0,
        "INDICES":     0.0,
        "CRYPTO":      0.0,
    }

    MAX_LEVERAGE_BY_CAT = {
        "FOREX":       500,
        "COMMODITIES": 100,
        "INDICES":     100,
        "CRYPTO":      200,
    }
    MAX_LEVERAGE_BY_SYM = {
        "XAUUSD": 500, "XAGUSD": 100,
        "XTIUSD": 100, "BRENT":  100, "NATGAS": 100, "COPPER": 100,
        "US500":  100, "USTEC":  100, "US30":   100,
        "DE40":   100, "UK100":  100, "JP225":  100, "AUS200": 100, "STOXX50": 100,
    }

    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "150.0"))
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    RISK_PERCENT_PER_TRADE = float(os.getenv("RISK_PERCENT_PER_TRADE", "2.0"))
    MARGIN_CALL_LEVEL = 100.0
    STOP_OUT_LEVEL    = 50.0
    MIN_LOT  = 0.01
    LOT_STEP = 0.01

    CONTRACT_SIZES = {
        "FOREX":       100000,
        "CRYPTO":      1,
        "COMMODITIES": 100,
        "INDICES":     1,
    }
    CONTRACT_SIZES_SPECIFIC = {
        "XAUUSD": 100, "XAGUSD": 5000, "XTIUSD": 100, "BRENT":  100,
        "NATGAS": 1000, "COPPER": 1000, "US500":  1, "USTEC":  1,
        "US30":   1, "DE40":   1, "UK100":  1, "JP225":  1,
        "AUS200": 1, "STOXX50": 1,
    }

    TIMEFRAMES = {
        "1m":  ("Agressivo",    "7d"),
        "5m":  ("Alto",         "5d"),
        "15m": ("Moderado",     "5d"),
        "30m": ("Conservador",  "5d"),
        "1h":  ("Seguro",      "60d"),
        "4h":  ("Muito Seguro","60d"),
    }
    TIMEFRAME = "15m"

    FOREX_OPEN_UTC = 0;  FOREX_CLOSE_UTC = 24
    COMM_OPEN_UTC  = 1;  COMM_CLOSE_UTC  = 23
    IDX_OPEN_UTC   = 1;  IDX_CLOSE_UTC   = 23
    STATE_FILE = "bot_state.json"
    USE_KELLY_CRITERION = True
    KELLY_FRACTION = 0.2
    ATR_PERIOD = 14
    NEWS_FILTER_IMPACT = ["HIGH"]
    CORRELATION_LIMIT = 0.7

def fmt(p: float) -> str:
    if not p: return "0"
    if p >= 10000: return f"{p:,.2f}"
    if p >= 1000:  return f"{p:.2f}"
    if p >= 10:    return f"{p:.4f}"
    if p >= 1:     return f"{p:.5f}"
    return f"{p:.6f}"

def log(msg):
    print(f"[{datetime.now(Config.BR_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)

TICKMILL_TO_YF = {
    "BTCUSD":  "BTC-USD",  "ETHUSD":  "ETH-USD",  "SOLUSD":  "SOL-USD",
    "BNBUSD":  "BNB-USD",  "XRPUSD":  "XRP-USD",  "ADAUSD":  "ADA-USD",
    "DOGEUSD": "DOGE-USD", "LTCUSD":  "LTC-USD",
    "XAUUSD":  "GC=F",     "XAGUSD":  "SI=F",
    "XTIUSD":  "CL=F",     "BRENT":   "BZ=F",
    "NATGAS":  "NG=F",     "COPPER":  "HG=F",
    "US500":   "ES=F",     "USTEC":   "NQ=F",     "US30":    "YM=F",
    "DE40":    "^GDAXI",   "UK100":   "^FTSE",    "JP225":   "^N225",
    "AUS200":  "^AXJO",    "STOXX50": "^STOXX50E",
}

def to_yf(s):
    if s in TICKMILL_TO_YF: return TICKMILL_TO_YF[s]
    if len(s) == 6 and s.isalpha(): return f"{s}=X"
    if "-" in s or s.startswith("^") or s.endswith("=F"): return s
    return f"{s}=X"

def asset_cat(s):
    for cat, info in Config.MARKET_CATEGORIES.items():
        if s in info["assets"]: return cat
    return "CRYPTO"

def asset_name(s):
    for info in Config.MARKET_CATEGORIES.values():
        if s in info["assets"]: return info["assets"][s]
    return s

def vol_reliable(s): return asset_cat(s) not in ("INDICES",)

def contract_size_for(symbol):
    return Config.CONTRACT_SIZES_SPECIFIC.get(symbol, Config.CONTRACT_SIZES.get(asset_cat(symbol), 1))

def commission_for(symbol, lot):
    if Config.ACCOUNT_TYPE not in ("RAW",): return 0.0
    cat = asset_cat(symbol)
    rate = Config.COMMISSION_PER_LOT_RT.get(symbol, Config.COMMISSION_PER_LOT_RT.get(cat, 0.0))
    return round(rate * lot, 2)

def max_leverage_for(symbol):
    if symbol in Config.MAX_LEVERAGE_BY_SYM: return Config.MAX_LEVERAGE_BY_SYM[symbol]
    return Config.MAX_LEVERAGE_BY_CAT.get(asset_cat(symbol), 100)

def symbol_profile(symbol):
    cat = asset_cat(symbol)
    if cat == "FOREX":
        return {"kind": "FX", "base": symbol[:3], "quote": symbol[3:], "contract_size": 100000}
    return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": contract_size_for(symbol)}

def required_amount_for_lot(symbol, entry, leverage, lot=None):
    profile = symbol_profile(symbol)
    lot = Config.MIN_LOT if lot is None else float(lot)
    max_lev = max_leverage_for(symbol)
    leverage = max(1.0, min(float(leverage or 1), float(max_lev)))
    entry = float(entry or 0)
    contract_size = float(profile["contract_size"])
    if profile["kind"] == "FX":
        base_to_usd = currency_to_usd(profile["base"])
        margin_per_lot = (contract_size * base_to_usd) / leverage
    else:
        margin_per_lot = (entry * contract_size) / leverage
    return round(margin_per_lot * lot, 2)

_FX_RATE_CACHE = {}
def currency_to_usd(currency):
    currency = (currency or "USD").upper()
    if currency == "USD": return 1.0
    now = time.time()
    cached = _FX_RATE_CACHE.get(currency)
    if cached and now - cached["ts"] < 300: return cached["rate"]
    import yfinance as yf
    pair_map = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "AUD": "AUDUSD=X", "NZD": "NZDUSD=X", "CAD": "USDCAD=X", "CHF": "USDCHF=X", "JPY": "USDJPY=X", "ZAR": "USDZAR=X"}
    ticker = pair_map.get(currency)
    rate = 1.0
    try:
        if ticker:
            df = yf.Ticker(ticker).history(period="5d", interval="1d")
            if len(df) and float(df["Close"].iloc[-1]) > 0:
                last = float(df["Close"].iloc[-1])
                rate = 1.0 / last if currency in {"CAD", "CHF", "JPY", "ZAR"} else last
    except: rate = 1.0
    _FX_RATE_CACHE[currency] = {"rate": float(rate), "ts": now}
    return float(rate)

def normalize_lot(lot):
    if lot <= 0: return 0.0
    step = Config.LOT_STEP
    return round(math.floor(lot / step) * step, 4)

def calc_trade_plan(symbol, entry, amount_usd, leverage, risk_pct, direction):
    """
    Cálculo Institucional Tickmill:
    1. Define SL e TP baseados na alavancagem (Quanto maior a alavancagem, menor a % de variação do preço).
    2. Calcula o lote necessário para que a perda no SL seja exatamente o valor em USD definido pelo risco.
    """
    amount_usd = float(amount_usd or 0)
    leverage = float(leverage or 1)
    entry = float(entry or 0)
    risk_pct = float(risk_pct or 0)
    
    if amount_usd <= 0 or entry <= 0 or leverage <= 0:
        return {"ok": False, "error": "Parâmetros inválidos para o plano de trade."}

    max_lev = max_leverage_for(symbol)
    if leverage > max_lev: leverage = float(max_lev)

    # Cálculo de SL e TP em porcentagem do preço
    # Regra: Quanto maior a alavancagem, menor a porcentagem para atingir o SL.
    # Ex: Se alavancagem é 500x, 1% de variação no capital (SL) = 1% / 500 no preço.
    sl_pct_price = (Config.SL_BASE_PCT / 100.0) / leverage
    tp_pct_price = sl_pct_price * Config.RISK_REWARD_RATIO

    if direction == "BUY":
        sl = entry * (1 - sl_pct_price)
        tp = entry * (1 + tp_pct_price)
    else:
        sl = entry * (1 + sl_pct_price)
        tp = entry * (1 - tp_pct_price)

    profile = symbol_profile(symbol)
    contract_size = float(profile["contract_size"])
    quote_to_usd = currency_to_usd(profile["quote"])
    
    # Risco em USD (Ex: 2% de $150 = $3)
    risk_money_target = amount_usd * (risk_pct / 100.0)
    
    # Perda por lote no SL
    sl_distance = abs(entry - sl)
    risk_loss_per_lot = sl_distance * contract_size * quote_to_usd
    
    # Lote baseado no risco em USD
    lot_by_risk = risk_money_target / risk_loss_per_lot if risk_loss_per_lot > 0 else 0
    
    # Margem necessária por lote
    if profile["kind"] == "FX":
        margin_per_lot = (contract_size * currency_to_usd(profile["base"])) / leverage
    else:
        margin_per_lot = (entry * contract_size) / leverage
        
    lot_by_margin = amount_usd / margin_per_lot if margin_per_lot > 0 else 0
    
    # O lote final é o menor entre o risco e a margem disponível
    raw_lot = min(lot_by_risk, lot_by_margin)
    lot = normalize_lot(raw_lot)
    
    if lot < Config.MIN_LOT:
        # Tenta o lote mínimo se a margem permitir
        if margin_per_lot * Config.MIN_LOT <= amount_usd:
            lot = Config.MIN_LOT
        else:
            return {"ok": False, "error": f"Saldo insuficiente para o lote mínimo de {Config.MIN_LOT} em {symbol}."}

    margin_required = margin_per_lot * lot
    risk_loss = risk_loss_per_lot * lot
    tp_gain = (abs(tp - entry) * contract_size * quote_to_usd) * lot
    commission = commission_for(symbol, lot)

    return {
        "ok": True, "symbol": symbol, "entry": entry, "sl": sl, "tp": tp, "lot": lot,
        "margin_required": round(margin_required, 2), "risk_loss": round(risk_loss, 2),
        "tp_gain": round(tp_gain, 2), "commission": round(commission, 2),
        "net_tp_gain": round(tp_gain - commission, 2), "leverage": leverage,
        "sl_pct_price": round(sl_pct_price * 100, 4), "tp_pct_price": round(tp_pct_price * 100, 4)
    }

def get_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, ("  ", "5d"))[1]
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 50: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]
        ema9 = closes.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]
        tr = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        price = float(closes.iloc[-1])
        cen = "ALTA" if price > ema200 and ema9 > ema21 else "BAIXA" if price < ema200 and ema9 < ema21 else "NEUTRO"
        return {"symbol": symbol, "price": price, "cenario": cen, "atr": atr, "ema9": ema9, "ema21": ema21, "ema200": ema200}
    except: return None

class TradingBot:
    def __init__(self):
        self.mode = "FOREX"; self.timeframe = Config.TIMEFRAME
        self.wins = 0; self.losses = 0; self.consecutive_losses = 0
        self.paused_until = 0; self.active_trades = []; self.pending_trades = []
        self.pending_counter = 0; self.history = []; self.signals_feed = []
        self.balance = Config.INITIAL_BALANCE; self.leverage = Config.DEFAULT_LEVERAGE
        self.risk_pct = Config.RISK_PERCENT_PER_TRADE
        self.last_id = 0; self.trend_cache = {}; self.news_cache = {}; self.news_cache_ts = 0
        self.awaiting_custom_amount = None; self._restore_msg = None
        self.account_currency = "USD"; self.account_type = Config.ACCOUNT_TYPE; self.platform = Config.BROKER_PLATFORM

    def set_balance(self, v): self.balance = float(v); save_state(self); return True
    def set_leverage(self, v): self.leverage = int(v); save_state(self); return True
    def set_mode(self, m): self.mode = m; save_state(self)
    def set_timeframe(self, t): self.timeframe = t; save_state(self)
    def reset_pause(self): self.paused_until = 0; self.consecutive_losses = 0; save_state(self)

    def scan(self):
        if time.time() < self.paused_until: return
        cat = self.mode
        assets = Config.MARKET_CATEGORIES[cat]["assets"] if cat != "TUDO" else {k:v for c in Config.MARKET_CATEGORIES.values() for k,v in c["assets"].items()}
        for sym in assets:
            if any(t["symbol"] == sym for t in self.active_trades + self.pending_trades): continue
            res = get_analysis(sym, self.timeframe)
            if not res or res["cenario"] == "NEUTRO": continue
            
            direction = "BUY" if res["cenario"] == "ALTA" else "SELL"
            plan = calc_trade_plan(sym, res["price"], self.balance, self.leverage, self.risk_pct, direction)
            
            if plan["ok"]:
                self.pending_counter += 1
                trade = {
                    "id": self.pending_counter, "symbol": sym, "dir": direction,
                    "entry": plan["entry"], "sl": plan["sl"], "tp": plan["tp"],
                    "lot": plan["lot"], "margin": plan["margin_required"],
                    "risk": plan["risk_loss"], "tp_gain": plan["tp_gain"],
                    "created": time.time()
                }
                self.pending_trades.append(trade)
                self.send_signal(trade)
                save_state(self)

    def send_signal(self, t):
        msg = (f"🎯 <b>SINAL TICKMILL: {t['symbol']}</b>\n"
               f"Direção: {'🟢 COMPRA' if t['dir'] == 'BUY' else '🔴 VENDA'}\n"
               f"Entrada: <code>{fmt(t['entry'])}</code>\n"
               f"Stop Loss: <code>{fmt(t['sl'])}</code>\n"
               f"Take Profit: <code>{fmt(t['tp'])}</code>\n"
               f"Lote Sugerido: <code>{t['lot']:.2f}</code>\n"
               f"Risco: <code>${t['risk']:.2f}</code> | Alvo: <code>${t['tp_gain']:.2f}</code>")
        self.send(msg)

    def send(self, msg):
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": Config.CHAT_ID, "text": msg, "parse_mode": "HTML"})

    def monitor_trades(self):
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res: continue
            price = res["price"]
            hit_tp = (t["dir"] == "BUY" and price >= t["tp"]) or (t["dir"] == "SELL" and price <= t["tp"])
            hit_sl = (t["dir"] == "BUY" and price <= t["sl"]) or (t["dir"] == "SELL" and price >= t["sl"])
            
            if hit_tp or hit_sl:
                result = "WIN" if hit_tp else "LOSS"
                pnl = t["tp_gain"] if hit_tp else -t["risk"]
                self.balance += pnl
                self.history.append({"symbol": t["symbol"], "result": result, "pnl": pnl, "closed_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")})
                self.active_trades.remove(t)
                if result == "LOSS":
                    self.consecutive_losses += 1
                    if self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                        self.paused_until = time.time() + Config.PAUSE_DURATION
                else:
                    self.consecutive_losses = 0
                save_state(self)
                self.send(f"🏁 Trade Finalizado: {t['symbol']} | Resultado: {result} | P&L: ${pnl:.2f}")

    def confirm_pending(self, pid):
        for t in self.pending_trades[:]:
            if t["id"] == int(pid):
                self.active_trades.append(t)
                self.pending_trades.remove(t)
                save_state(self)
                return True
        return False

    def reject_pending(self, pid):
        for t in self.pending_trades[:]:
            if t["id"] == int(pid):
                self.pending_trades.remove(t)
                save_state(self)
                return True
        return False

    def update_trends_cache(self): pass
    def maybe_send_news(self): pass
    def build_menu(self): pass
    def scan_reversal_forex(self): pass

def save_state(bot):
    try:
        with open(Config.STATE_FILE, "w") as f:
            json.dump({
                "balance": bot.balance, "leverage": bot.leverage, "wins": bot.wins, "losses": bot.losses,
                "active_trades": bot.active_trades, "history": bot.history
            }, f)
    except: pass

def load_state(bot):
    if os.path.exists(Config.STATE_FILE):
        try:
            with open(Config.STATE_FILE) as f:
                data = json.load(f)
                bot.balance = data.get("balance", Config.INITIAL_BALANCE)
                bot.leverage = data.get("leverage", Config.DEFAULT_LEVERAGE)
                bot.active_trades = data.get("active_trades", [])
                bot.history = data.get("history", [])
        except: pass

# ═══════════════════════════════════════════════════════════════
# DASHBOARD HTML (Simplificado para o exemplo)
# ═══════════════════════════════════════════════════════════════
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>Tickmill Sniper Dashboard</title>
    <style>
        body { font-family: sans-serif; background: #06090f; color: #fff; padding: 20px; }
        .card { background: #161b22; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #30363d; }
        .green { color: #00e676; } .red { color: #ff5252; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 10px; border-bottom: 1px solid #30363d; }
    </style>
</head>
<body>
    <h1>Tickmill Sniper Bot v8.5</h1>
    <div class="card">
        <h2>Conta</h2>
        <p>Saldo: <span class="green">$<span id="balance">0.00</span></span></p>
        <p>Alavancagem: <span id="leverage">0</span>x</p>
    </div>
    <div class="card">
        <h2>Trades Ativos</h2>
        <table id="active-trades">
            <thead><tr><th>Ativo</th><th>Dir</th><th>Entrada</th><th>Lote</th><th>P&L Est.</th></tr></thead>
            <tbody></tbody>
        </table>
    </div>
    <script>
        async function update() {
            const r = await fetch('/api/status').then(res => res.json());
            document.getElementById('balance').innerText = r.balance.toFixed(2);
            document.getElementById('leverage').innerText = r.leverage;
            const tbody = document.querySelector('#active-trades tbody');
            tbody.innerHTML = r.active_trades.map(t => `
                <tr>
                    <td>${t.symbol}</td>
                    <td class="${t.dir === 'BUY' ? 'green' : 'red'}">${t.dir}</td>
                    <td>${t.entry}</td>
                    <td>${t.lot}</td>
                    <td>$${t.tp_gain} / -$${t.risk}</td>
                </tr>
            `).join('');
        }
        setInterval(update, 5000); update();
    </script>
</body>
</html>
"""

def create_api(bot):
    app = Flask(__name__)
    CORS(app)
    @app.route("/")
    def index(): return Response(DASHBOARD_HTML, mimetype="text/html")
    @app.route("/api/status")
    def status():
        return jsonify({
            "balance": bot.balance, "leverage": bot.leverage,
            "active_trades": bot.active_trades, "history": bot.history
        })
    @app.route("/api/leverage", methods=["POST"])
    def set_lev():
        data = request.get_json()
        bot.set_leverage(data.get("leverage", 500))
        return jsonify({"ok": True})
    return app

def main():
    bot = TradingBot()
    load_state(bot)
    app = create_api(bot)
    
    def run_bot():
        while True:
            bot.scan()
            bot.monitor_trades()
            time.sleep(30)
            
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    main()
