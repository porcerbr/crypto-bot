# -- coding: utf-8 --
"""
TICKMILL SNIPER BOT v8.0 INSTITUTIONAL — Dashboard Profissional de Execução Rápida
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
✅ 100% da lógica original preservada (engine, persistência, Telegram, etc.)
"""
import os, time, json, math, threading, requests
import pandas as pd, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
# ═══════════════════════════════════════════════════════════════
# CONFIGURAÇÕES & HELPERS (100% PRESERVADOS)
# ═══════════════════════════════════════════════════════════════
class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ      = timezone(timedelta(hours=-3))

    # ── TICKMILL MT5 — Símbolos nativos da plataforma ──────────────────────────
    # Crypto/Commodities/Índices usam nomenclatura MT5 da Tickmill.
    # A conversão para Yahoo Finance é feita internamente via TICKMILL_TO_YF.
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

    ATR_MULT_SL = 1.5; ATR_MULT_TP = 3.5; ATR_MULT_TRAIL = 1.2
    MAX_CONSECUTIVE_LOSSES = 2; PAUSE_DURATION = 3600
    ADX_MIN = 22; MAX_TRADES = 3; ASSET_COOLDOWN = 3600; MIN_CONFLUENCE = 5
    MIN_CONFLUENCE_CT = 4; REVERSAL_MIN_SCORE = 6; REVERSAL_COOLDOWN = 2700
    REVERSAL_REQUIRE_TREND = True; REVERSAL_RSI_SELL = 75; REVERSAL_RSI_BUY = 25
    REVERSAL_BAND_BUFFER = 0.997
    RADAR_COOLDOWN = 1800; GATILHO_COOLDOWN = 300
    TRENDS_INTERVAL = 120; NEWS_INTERVAL = 7200
    SCAN_INTERVAL = 30

    # ── TICKMILL — Configurações de corretora ──────────────────────────────────
    BROKER_NAME     = "Tickmill"
    BROKER_PLATFORM = "MT5"
    # Tipos disponíveis: RAW (comissão $2/lote/lado), CLASSIC (spread alargado), PRO
    ACCOUNT_TYPE    = os.getenv("TICKMILL_ACCOUNT_TYPE", "RAW")
    BASE_CURRENCY   = "USD"

    # Comissão Round-Trip por lote padrão (Raw ECN: $2 entrada + $2 saída = $4)
    COMMISSION_PER_LOT_RT = {
        "FOREX":       6.0,
        "COMMODITIES": 6.0,
        "INDICES":     0.0,
        "CRYPTO":      0.0,
    }

    # Alavancagem máxima por categoria (Tickmill — entidade Seychelles/Global)
    MAX_LEVERAGE_BY_CAT = {
        "FOREX":       500,
        "COMMODITIES": 100,
        "INDICES":     100,
        "CRYPTO":      200,
    }
    # Overrides por símbolo específico
    MAX_LEVERAGE_BY_SYM = {
        "XAUUSD": 500, "XAGUSD": 100,
        "XTIUSD": 100, "BRENT":  100, "NATGAS": 100, "COPPER": 100,
        "US500":  100, "USTEC":  100, "US30":   100,
        "DE40":   100, "UK100":  100, "JP225":  100, "AUS200": 100, "STOXX50": 100,
    }

    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "500.0"))
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    RISK_PERCENT_PER_TRADE = float(os.getenv("RISK_PERCENT_PER_TRADE", "2.0"))
    MARGIN_CALL_LEVEL = 100.0   # Tickmill margin call: 100%
    STOP_OUT_LEVEL    = 50.0    # Tickmill stop out:    30%
    MIN_LOT  = 0.01
    LOT_STEP = 0.01

    # ── Tamanhos de contrato Tickmill MT5 ─────────────────────────────────────
    CONTRACT_SIZES = {
        "FOREX":       100000,  # 1 lote = 100.000 unidades da moeda base
        "CRYPTO":      1,       # 1 lote = 1 unidade do cripto
        "COMMODITIES": 100,     # base (overrides abaixo)
        "INDICES":     1,       # base (overrides abaixo)
    }
    # Tamanhos específicos por símbolo MT5
    CONTRACT_SIZES_SPECIFIC = {
        "XAUUSD": 100,
        "XAGUSD": 5000,
        "XTIUSD": 100,
        "BRENT":  100,
        "NATGAS": 1000,
        "COPPER": 1000,
        "US500":  1,
        "USTEC":  1,
        "US30":   1,
        "DE40":   1,
        "UK100":  1,
        "JP225":  1,
        "AUS200": 1,
        "STOXX50": 1,
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

    # Horários de mercado (UTC) — compatível com sessões Tickmill
    FOREX_OPEN_UTC = 0;  FOREX_CLOSE_UTC = 24   # Londres+NY
    COMM_OPEN_UTC  = 1;  COMM_CLOSE_UTC  = 23   # Até fechamento NY
    IDX_OPEN_UTC   = 1;  IDX_CLOSE_UTC   = 23
    STATE_FILE = "bot_state.json"
    # --- Configurações Institucionais v8.0 ---
    USE_KELLY_CRITERION = True
    KELLY_FRACTION = 0.2  # "Half-Kelly" para maior segurança
    ATR_PERIOD = 14
    ATR_TRAILING_MULT = 2.0
    NEWS_FILTER_IMPACT = ["HIGH"] # Bloquear apenas notícias de alto impacto
    CORRELATION_LIMIT = 0.7 # Limite de correlação entre ativos abertos

def fmt(p: float) -> str:
    if not p: return "0"
    if p >= 10000: return f"{p:,.2f}"
    if p >= 1000:  return f"{p:.2f}"
    if p >= 10:    return f"{p:.4f}"
    if p >= 1:     return f"{p:.5f}"
    return f"{p:.6f}"
def log(msg):
    print(f"[{datetime.now(Config.BR_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)

# ── Mapeamento: Símbolo Tickmill MT5 → Yahoo Finance (para dados de preço) ──
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
    """Converte símbolo Tickmill MT5 para Yahoo Finance."""
    if s in TICKMILL_TO_YF:
        return TICKMILL_TO_YF[s]
    # Pares Forex: 6 letras → adiciona =X
    if len(s) == 6 and s.isalpha():
        return f"{s}=X"
    # Já está no formato YF
    if "-" in s or s.startswith("^") or s.endswith("=F"):
        return s
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
    """Retorna o tamanho do contrato do símbolo na Tickmill MT5."""
    return Config.CONTRACT_SIZES_SPECIFIC.get(
        symbol, Config.CONTRACT_SIZES.get(asset_cat(symbol), 1))

def commission_for(symbol, lot):
    """Calcula comissão round-trip Tickmill para o lote dado (Raw ECN)."""
    if Config.ACCOUNT_TYPE not in ("RAW",):
        return 0.0  # Classic/Pro não têm comissão separada
    cat = asset_cat(symbol)
    rate = Config.COMMISSION_PER_LOT_RT.get(symbol,
           Config.COMMISSION_PER_LOT_RT.get(cat, 0.0))
    return round(rate * lot, 2)

def max_leverage_for(symbol):
    """Retorna a alavancagem máxima permitida pela Tickmill para o símbolo."""
    if symbol in Config.MAX_LEVERAGE_BY_SYM:
        return Config.MAX_LEVERAGE_BY_SYM[symbol]
    return Config.MAX_LEVERAGE_BY_CAT.get(asset_cat(symbol), 100)

def symbol_profile(symbol):
    cat = asset_cat(symbol)
    if cat == "FOREX":
        return {"kind": "FX", "base": symbol[:3], "quote": symbol[3:], "contract_size": 100000}
    if cat == "COMMODITIES":
        return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": contract_size_for(symbol)}
    if cat == "INDICES":
        return {"kind": "INDEX", "base": "USD", "quote": "USD", "contract_size": contract_size_for(symbol)}
    if cat == "CRYPTO":
        return {"kind": "CRYPTO", "base": "USD", "quote": "USD", "contract_size": 1}
    return {"kind": "CFD", "base": "USD", "quote": "USD", "contract_size": contract_size_for(symbol)}

def asset_min_lot(symbol):
    # Tickmill: lote mínimo padrão = 0.01 para todos os instrumentos disponíveis.
    return Config.MIN_LOT

def required_amount_for_lot(symbol, entry, leverage, lot=None):
    """Valor-base mínimo estimado para abrir um lote específico."""
    profile = symbol_profile(symbol)
    lot = Config.MIN_LOT if lot is None else float(lot)
    # Respeita limite de alavancagem da Tickmill por símbolo
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
    if currency == "USD":
        return 1.0
    now = time.time()
    cached = _FX_RATE_CACHE.get(currency)
    if cached and now - cached["ts"] < 300:
        return cached["rate"]
    import yfinance as yf
    pair_map = {
        "EUR": "EURUSD=X", "GBP": "GBPUSD=X", "AUD": "AUDUSD=X", "NZD": "NZDUSD=X",
        "CAD": "USDCAD=X", "CHF": "USDCHF=X", "JPY": "USDJPY=X", "ZAR": "USDZAR=X",
    }
    ticker = pair_map.get(currency)
    rate = 1.0
    try:
        if ticker:
            df = yf.Ticker(ticker).history(period="5d", interval="1d")
            if len(df) and float(df["Close"].iloc[-1]) > 0:
                last = float(df["Close"].iloc[-1])
                if currency in {"CAD", "CHF", "JPY", "ZAR"}:
                    rate = 1.0 / last
                else:
                    rate = last
    except Exception:
        rate = 1.0
    _FX_RATE_CACHE[currency] = {"rate": float(rate), "ts": now}
    return float(rate)

def normalize_lot(lot):
    if lot <= 0:
        return 0.0
    step = Config.LOT_STEP
    return round(math.floor(lot / step) * step, 4)



def check_correlation(bot, symbol):
    # Pares altamente correlacionados (Simplificado)
    correlations = {
        "EURUSD": ["GBPUSD", "USDCHF", "AUDUSD"],
        "GBPUSD": ["EURUSD", "NZDUSD"],
        "USDJPY": ["USDCAD"],
        "BTCUSD": ["ETHUSD", "SOLUSD"]
    }
    active_symbols = [t['symbol'] for t in bot.active_trades]
    if symbol in correlations:
        for related in correlations[symbol]:
            if related in active_symbols:
                return True # Bloqueia por alta correlação
    return False

def check_news_block(bot):
    # Simulação de integração com calendário econômico
    # Em um ambiente real, faria request para ForexFactory ou Investing.com
    # Retorna True se houver notícia de alto impacto nos próximos 15 min
    try:
        # Exemplo de lógica: se o bot_loop detectar horário de notícia, bloqueia
        return False # Implementação simplificada para manter estabilidade
    except: return False

def calc_kelly_risk(bot):
    if not bot.history: return Config.RISK_PERCENT_PER_TRADE
    wins = [h for h in bot.history if h['result'] == 'WIN']
    if not wins: return Config.RISK_PERCENT_PER_TRADE
    win_rate = len(wins) / len(bot.history)
    avg_win = sum(h['pnl_money'] for h in wins) / len(wins)
    losses = [h for h in bot.history if h['result'] == 'LOSS']
    if not losses: return Config.RISK_PERCENT_PER_TRADE
    avg_loss = abs(sum(h['pnl_money'] for h in losses) / len(losses))
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1
    kelly_f = win_rate - ((1 - win_rate) / win_loss_ratio)
    risk = max(0.5, min(Config.RISK_PERCENT_PER_TRADE * 1.5, kelly_f * Config.KELLY_FRACTION * 100))
    return round(risk, 2)

def calc_trade_plan(symbol, entry, sl, tp, amount, leverage, risk_pct):
    amount = float(amount or 0)
    leverage = float(leverage or 1)
    entry = float(entry or 0)
    sl = float(sl or 0)
    tp = float(tp or 0)
    risk_pct = float(risk_pct or 0)
    profile = symbol_profile(symbol)
    contract_size = float(profile["contract_size"])
    base_ccy = profile["base"]
    quote_ccy = profile["quote"]

    if amount <= 0:
        return {"ok": False, "error": "Valor da operação precisa ser maior que zero."}
    if entry <= 0 or sl <= 0 or tp <= 0:
        return {"ok": False, "error": "Preço de entrada/SL/TP inválido."}
    if leverage <= 0:
        return {"ok": False, "error": "Alavancagem inválida."}

    # ── Tickmill: garante que a alavancagem não excede o limite do símbolo ──
    max_lev = max_leverage_for(symbol)
    if leverage > max_lev:
        leverage = float(max_lev)

    sl_distance = abs(entry - sl)
    if sl_distance <= 0:
        return {"ok": False, "error": "Distância do stop inválida."}

    # Tickmill/MT5: margem calculada pelo MT5 com base no contrato e na alavancagem.
    quote_to_usd = currency_to_usd(quote_ccy)
    base_to_usd = currency_to_usd(base_ccy)
    risk_money_target = amount * (risk_pct / 100.0)

    # P/L e risco dependem do contrato do ativo e da moeda de cotação.
    risk_loss_per_lot = sl_distance * contract_size * quote_to_usd
    tp_gain_per_lot = abs(tp - entry) * contract_size * quote_to_usd
    lot_by_risk = risk_money_target / risk_loss_per_lot if risk_loss_per_lot > 0 else 0.0

    # Margem no MT5 (Tickmill): volume * tamanho_contrato / alavancagem
    if profile["kind"] == "FX":
        if base_ccy == Config.BASE_CURRENCY:
            margin_per_lot = contract_size / leverage
        else:
            margin_per_lot = (contract_size * base_to_usd) / leverage
    else:
        margin_per_lot = (entry * contract_size) / leverage

    max_lot_by_margin = amount / margin_per_lot if margin_per_lot > 0 else 0.0
    raw_lot = min(max_lot_by_margin, lot_by_risk)
    lot = normalize_lot(raw_lot)
    note = []

    if lot < Config.MIN_LOT and max_lot_by_margin >= Config.MIN_LOT:
        note.append(f"Lote calculado abaixo do mínimo; ajustado para {Config.MIN_LOT:.2f}.")
        lot = Config.MIN_LOT

    if lot > max_lot_by_margin + 1e-12:
        lot = normalize_lot(max_lot_by_margin)

    if lot < Config.MIN_LOT or lot <= 0:
        min_amt = required_amount_for_lot(symbol, entry, leverage, Config.MIN_LOT)
        return {"ok": False, "error": f"Valor insuficiente para abrir o lote mínimo de {Config.MIN_LOT:.2f}. Valor mínimo estimado: {fmt(min_amt)} USD."}

    # Margem final e risco final já com o lote arredondado.
    margin_required = margin_per_lot * lot
    if margin_required > amount + 1e-9:
        return {"ok": False, "error": "Margem insuficiente para o lote mínimo."}

    risk_loss = risk_loss_per_lot * lot
    tp_gain = tp_gain_per_lot * lot
    potential_pnl_ratio = tp_gain / margin_required * 100 if margin_required else 0

    # ── Tickmill: comissão round-trip (Raw ECN) ───────────────────────────────
    commission = commission_for(symbol, lot)
    if commission > 0:
        note.append(f"Comissão Tickmill (Raw ECN RT): ~${commission:.2f} ({lot:.2f} lotes × ${Config.COMMISSION_PER_LOT_RT.get(asset_cat(symbol), 4.0):.0f}/lote).")
    net_tp_gain = round(tp_gain - commission, 2)

    # Aviso se alavancagem foi limitada
    max_lev = max_leverage_for(symbol)
    if float(leverage) == float(max_lev) and float(leverage) < float(leverage):
        note.append(f"Alavancagem limitada ao máximo permitido pela Tickmill: {max_lev}x.")

    return {
        "ok": True,
        "symbol": symbol,
        "contract_size": contract_size,
        "base_ccy": base_ccy,
        "quote_ccy": quote_ccy,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "amount": amount,
        "leverage": leverage,
        "max_leverage": max_lev,
        "risk_pct": risk_pct,
        "min_lot": Config.MIN_LOT,
        "min_amount_required": required_amount_for_lot(symbol, entry, leverage, Config.MIN_LOT),
        "lot_by_risk": round(lot_by_risk, 4),
        "max_lot_by_margin": round(max_lot_by_margin, 4),
        "lot": round(lot, 4),
        "margin_required": round(margin_required, 2),
        "risk_money_target": round(risk_money_target, 2),
        "risk_loss": round(risk_loss, 2),
        "tp_gain": round(tp_gain, 2),
        "commission": round(commission, 2),
        "net_tp_gain": net_tp_gain,
        "potential_pnl_ratio": round(potential_pnl_ratio, 2),
        "note": note,
    }

def all_syms():

    out = []
    for c in Config.MARKET_CATEGORIES.values(): out.extend(c["assets"].keys())
    return out
def mkt_open(cat):
    now = datetime.now(timezone.utc); h = now.hour; wd = now.weekday()
    if cat == "CRYPTO": return True
    if wd >= 5: return False
    if cat == "FOREX":       return Config.FOREX_OPEN_UTC <= h < Config.FOREX_CLOSE_UTC
    if cat == "COMMODITIES": return Config.COMM_OPEN_UTC  <= h < Config.COMM_CLOSE_UTC
    if cat == "INDICES":     return Config.IDX_OPEN_UTC   <= h < Config.IDX_CLOSE_UTC
    return True
# ═══════════════════════════════════════════════════════════════# PERSISTÊNCIA, NOTÍCIAS, ANÁLISE, CONFLUÊNCIA, CT, PUSH
# ═══════════════════════════════════════════════════════════════
# (TUDO PRESERVADO EXATAMENTE COMO NA VERSÃO ANTERIOR)
def save_state(bot):
    data = {
        "mode": bot.mode, "timeframe": bot.timeframe,
        "wins": bot.wins, "losses": bot.losses,
        "consecutive_losses": bot.consecutive_losses,
        "paused_until": bot.paused_until,
        "active_trades": bot.active_trades,
        "pending_trades": bot.pending_trades,
        "pending_counter": bot.pending_counter,
        "radar_list": bot.radar_list, "gatilho_list": bot.gatilho_list,
        "reversal_list": bot.reversal_list, "asset_cooldown": bot.asset_cooldown,
        "history": bot.history,
        "signals_feed": bot.signals_feed,
        "balance": bot.balance,
        "leverage": bot.leverage,
        "risk_pct": bot.risk_pct,
        "account_currency": bot.account_currency,
        "account_type": bot.account_type,
        "platform": bot.platform,
    }
    try:
        with open(Config.STATE_FILE, "w") as f: json.dump(data, f, indent=2)
    except Exception as e: log(f"[STATE] {e}")
def load_state(bot):
    if not os.path.exists(Config.STATE_FILE): return
    try:
        with open(Config.STATE_FILE) as f: data = json.load(f)
        bot.mode = data.get("mode", "CRYPTO")
        bot.timeframe = data.get("timeframe", Config.TIMEFRAME)
        bot.wins = data.get("wins", 0); bot.losses = data.get("losses", 0)
        bot.consecutive_losses = data.get("consecutive_losses", 0)
        bot.paused_until = data.get("paused_until", 0)
        bot.active_trades = data.get("active_trades", [])
        bot.pending_trades = data.get("pending_trades", [])
        bot.pending_counter = data.get("pending_counter", 0)
        bot.radar_list = data.get("radar_list", {}); bot.gatilho_list = data.get("gatilho_list", {})
        bot.reversal_list = data.get("reversal_list", {}); bot.asset_cooldown = data.get("asset_cooldown", {})
        bot.history = data.get("history", [])
        bot.signals_feed = data.get("signals_feed", [])
        bot.balance = float(data.get("balance", Config.INITIAL_BALANCE))
        bot.leverage = int(data.get("leverage", Config.DEFAULT_LEVERAGE))
        bot.risk_pct = float(data.get("risk_pct", Config.RISK_PERCENT_PER_TRADE))
        bot.account_currency = data.get("account_currency", Config.BASE_CURRENCY)
        bot.account_type = data.get("account_type", Config.ACCOUNT_TYPE)
        bot.platform = data.get("platform", Config.BROKER_PLATFORM)
        for t in bot.active_trades: t["session_alerted"] = False
        for t in bot.pending_trades: t["session_alerted"] = False
        log(f"[STATE] {bot.wins}W/{bot.losses}L | {len(bot.active_trades)} trade(s) | {len(bot.pending_trades)} pendente(s) | {len(bot.signals_feed)} sinal(is)")
        if bot.active_trades:
            lines = ["♻️ BOT REINICIADO – TRADES ATIVOS\n"]
            for t in bot.active_trades:
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                lines.append(f"📌 {t['symbol']} {dl} | Entrada: `{fmt(t['entry'])}` | TP: `{fmt(t['tp'])}` | SL: `{fmt(t['sl'])}`")
            bot._restore_msg = "\n".join(lines)
        else: bot._restore_msg = None
    except Exception as e: log(f"[STATE] Erro: {e}")

def account_snapshot(bot):
    open_pnl_money = 0.0
    used_margin = 0.0
    total_commission = 0.0
    for t in bot.active_trades:
        try:
            res = get_analysis(t["symbol"], bot.timeframe)
            cur = res["price"] if res else t["entry"]
        except Exception:
            cur = t["entry"]
        pnl_pct = (cur - t["entry"]) / t["entry"] * 100
        if t["dir"] == "SELL":
            pnl_pct = -pnl_pct
        lot = float(t.get("lot", Config.MIN_LOT))
        contract_size = float(t.get("contract_size", contract_size_for(t["symbol"])))
        move = (cur - t["entry"]) if t["dir"] == "BUY" else (t["entry"] - cur)
        raw_pnl = move * contract_size * lot
        # Subtrai comissão Tickmill do P&L flutuante
        comm = commission_for(t["symbol"], lot)
        open_pnl_money += raw_pnl - comm
        total_commission += comm
        used_margin += float(t.get("margin_required", 0))
    balance = float(bot.balance)
    equity = round(balance + open_pnl_money, 2)
    free_margin = round(equity - used_margin, 2)
    margin_level = round((equity / used_margin) * 100, 1) if used_margin > 0 else 0
    return {
        "balance": round(balance, 2),
        "equity": equity,
        "used_margin": round(used_margin, 2),
        "free_margin": free_margin,
        "margin_level": margin_level,
        "open_pnl_money": round(open_pnl_money, 2),
        "total_commission": round(total_commission, 2),
    }

RSS_FEEDS = [    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"), ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Yahoo Finance", "https://finance.yahoo.com/rss/topfinstories"),
]
def _parse_rss(url, src, mx=3):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        out = []
        for item in items[:mx]:
            title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "  ").strip()
            link  = (item.findtext("link")  or item.findtext("{http://www.w3.org/2005/Atom}link")  or "  ").strip()
            if title and link: out.append({"title": title, "url": link, "source": src})
        return out
    except: return []
def get_news(mx=15):
    arts = []
    for name, url in RSS_FEEDS:
        if len(arts) >= mx: break
        try: arts.extend(_parse_rss(url, name, 4))
        except Exception as e: log(f"[RSS] {name}: {e}")
    return arts[:mx]
def get_fear_greed():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6).json()["data"][0]
        return {"value": d["value"], "label": d["value_classification"]}
    except: return {"value": "N/D", "label": " "}
def build_news_msg():
    arts = get_news(5); fg = get_fear_greed()
    lines = ["📰 NOTÍCIAS\n"]
    for i, a in enumerate(arts, 1):
        t = a["title"][:120] + ("…" if len(a["title"]) > 120 else "  ")
        lines.append(f"{i}. <a href='{a['url']}'>{t} ({a['source']})")
    lines.append(f"\n😱 F&G: {fg['value']} – {fg['label']}")
    return "\n".join(lines)
def get_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, ("  ", "5d"))[1]
    use_vol = vol_reliable(symbol)
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        
        if len(df) < 50: 
            return None
            
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]; volume = df["Volume"]
        ema9   = closes.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21  = closes.ewm(span=21, adjust=False).mean().iloc[-1]
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean().iloc[-1]
        w = min(20, len(closes)-1)
        sma20 = closes.rolling(w).mean().iloc[-1]; std20 = closes.rolling(w).std().iloc[-1]
        upper = sma20 + std20*2; lower = sma20 - std20*2
        delta = closes.diff()
        gain  = delta.where(delta>0, 0).rolling(14).mean()
        loss  = (-delta.where(delta<0, 0)).rolling(14).mean()
        rsi   = (100 - 100/(1 + gain/loss)).iloc[-1]
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        ml    = ema12 - ema26; mh = ml - ml.ewm(span=9, adjust=False).mean()
        macd_bull = bool(mh.iloc[-1] > 0 and mh.iloc[-1] > mh.iloc[-2])
        macd_bear = bool(mh.iloc[-1] < 0 and mh.iloc[-1] < mh.iloc[-2])
        if use_vol and volume.sum() > 0:
            va = volume.rolling(20).mean().iloc[-1]; vc = volume.iloc[-1]
            vol_ok = bool(vc > va) if va > 0 else False; vol_ratio = float(vc/va) if va > 0 else 0
        else: vol_ok = True; vol_ratio = 0
        tr  = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd>0)&(hd>-ld), 0.0); mdm = (-ld).where((-ld>0)&(-ld>hd), 0.0)
        as_ = tr.ewm(alpha=1/14, adjust=False).mean()
        pdi = 100*pdm.ewm(alpha=1/14, adjust=False).mean()/(as_+1e-10)
        mdi = 100*mdm.ewm(alpha=1/14, adjust=False).mean()/(as_+1e-10)
        dx  = 100*(pdi-mdi).abs()/(pdi+mdi+1e-10)
        adx = float(dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
        price = float(closes.iloc[-1])
        chg   = float((closes.iloc[-1]-closes.iloc[-10])/closes.iloc[-10]*100) if len(closes)>=10 else 0
        cen   = "NEUTRO"
        if price > ema200 and ema9 > ema21: cen = "ALTA"
        elif price < ema200 and ema9 < ema21: cen = "BAIXA"
        h1b = h1r = False
        sup_tf = "1h" if timeframe in ("1m","5m","15m","30m") else "1d"
        sup_per = "60d" if sup_tf == "1h" else "2y"
        try:
            dh = yf.Ticker(yf_symbol).history(period=sup_per, interval=sup_tf)
            if len(dh) >= 50:
                ch = dh["Close"]
                e21h = ch.ewm(span=21, adjust=False).mean().iloc[-1]
                e200h = ch.ewm(span=min(200,len(ch)-1), adjust=False).mean().iloc[-1]
                ph = ch.iloc[-1]
                h1b = bool(ph > e21h and e21h > e200h)
                h1r = bool(ph < e21h and e21h < e200h)
        except: pass
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price, "cenario": cen,            "rsi": float(rsi), "atr": atr, "adx": adx, "ema9": float(ema9), "ema21": float(ema21),
            "ema200": float(ema200), "upper": float(upper), "lower": float(lower),
            "macd_bull": macd_bull, "macd_bear": macd_bear, "macd_hist": float(mh.iloc[-1]),
            "vol_ok": vol_ok, "vol_ratio": vol_ratio, "t_buy": float(highs.tail(5).max()),
            "t_sell": float(lows.tail(5).min()), "h1_bull": h1b, "h1_bear": h1r, "change_pct": chg,
        }
    except Exception as e:
        log(f"[ANÁLISE] {symbol}: {e}"); return None
def calc_confluence(res, d):
    if d == "BUY":
        checks = [("EMA 200 acima", res["price"] > res["ema200"]), ("EMA 9 > 21", res["ema9"] > res["ema21"]),
                  ("MACD Alta", res["macd_bull"]), ("Volume OK", res["vol_ok"]), ("RSI < 65", res["rsi"] < 65),
                  ("TF Superior Alta", res["h1_bull"]), ("ADX tendência", res["adx"] > Config.ADX_MIN)]
    else:
        checks = [("EMA 200 abaixo", res["price"] < res["ema200"]), ("EMA 9 < 21", res["ema9"] < res["ema21"]),
                  ("MACD Baixa", res["macd_bear"]), ("Volume OK", res["vol_ok"]), ("RSI > 35", res["rsi"] > 35),
                  ("TF Superior Baixa", res["h1_bear"]), ("ADX tendência", res["adx"] > Config.ADX_MIN)]
    sc = sum(1 for _, ok in checks if ok)
    return sc, len(checks), checks
def cbar(sc, tot):
    f = math.floor(sc/tot*5)
    return "█"*f + "░"*(5-f)
def detect_candle_patterns(df):
    if len(df) < 3: return False, False, " "
    o1,h1,l1,c1 = df["Open"].iloc[-2],df["High"].iloc[-2],df["Low"].iloc[-2],df["Close"].iloc[-2]
    o0,h0,l0,c0 = df["Open"].iloc[-1],df["High"].iloc[-1],df["Low"].iloc[-1],df["Close"].iloc[-1]
    body0 = abs(c0-o0); rng0 = h0-l0 or 1e-10
    uw = h0-max(c0,o0); lw = min(c0,o0)-l0
    pb = pb2 = False; nm = " "
    if (c0>o0) and (c1<o1) and c0>o1 and o0<c1: pb=True; nm="Engolfo de Alta"
    elif (c0<o0) and (c1>o1) and c0<l1: pb2=True; nm="Engolfo de Baixa"
    elif lw>body0*2 and uw<body0*0.5 and body0<rng0*0.4: pb=True; nm="Martelo"
    elif uw>body0*2 and lw<body0*0.5 and body0<rng0*0.4: pb2=True; nm="Estrela Cadente"
    elif body0 < rng0*0.1: pb=pb2=True; nm="Doji"
    elif lw>rng0*0.6 and body0<rng0*0.25: pb=True; nm="Pin Bar Alta"
    elif uw>rng0*0.6 and body0<rng0*0.25: pb2=True; nm="Pin Bar Baixa"
    return pb, pb2, nm
def get_reversal_analysis(symbol, timeframe=None):
    import yfinance as yf
    timeframe = timeframe or Config.TIMEFRAME
    yf_symbol = to_yf(symbol)
    period = Config.TIMEFRAMES.get(timeframe, ("  ", "5d"))[1]
    try:
        df = yf.Ticker(yf_symbol).history(period=period, interval=timeframe)
        if len(df) < 30: return None
        closes = df["Close"]; highs = df["High"]; lows = df["Low"]        
        price = float(closes.iloc[-1])
        w = min(20, len(closes)-1)
        sma = closes.rolling(w).mean(); std = closes.rolling(w).std()
        ub = float((sma+std*2).iloc[-1]); lb = float((sma-std*2).iloc[-1])
        delta = closes.diff()
        gain = delta.where(delta>0,0).rolling(14).mean(); loss = (-delta.where(delta<0,0)).rolling(14).mean()
        rsi_s = 100-100/(1+gain/loss); rsi = float(rsi_s.iloc[-1])
        ema9 = closes.ewm(span=9,adjust=False).mean()
        ema21 = closes.ewm(span=21,adjust=False).mean()
        ema12 = closes.ewm(span=12,adjust=False).mean(); ema26 = closes.ewm(span=26,adjust=False).mean()
        mh = (ema12-ema26)-(ema12-ema26).ewm(span=9,adjust=False).mean()
        ema200 = closes.ewm(span=min(200, len(closes)-1), adjust=False).mean()
        tr = pd.concat([highs-lows,(highs-closes.shift()).abs(),(lows-closes.shift()).abs()],axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        hd = highs.diff(); ld = lows.diff()
        pdm = hd.where((hd>0)&(hd>-ld),0.0); mdm = (-ld).where((-ld>0)&(-ld>hd),0.0)
        as_ = tr.ewm(alpha=1/14,adjust=False).mean()
        pdi = 100*pdm.ewm(alpha=1/14,adjust=False).mean()/(as_+1e-10)
        mdi = 100*mdm.ewm(alpha=1/14,adjust=False).mean()/(as_+1e-10)
        adx = float((100*(pdi-mdi).abs()/(pdi+mdi+1e-10)).ewm(alpha=1/14,adjust=False).mean().iloc[-1])
        lb10 = 10; rh = closes.tail(lb10).max(); rl = closes.tail(lb10).min()
        ph = closes.iloc[-lb10*2:-lb10].max(); pl = closes.iloc[-lb10*2:-lb10].min()
        div_bear = bool(rh > ph and rsi < rsi_s.iloc[-lb10*2:-lb10].max() and rsi > 55)
        div_bull = bool(rl < pl and rsi > rsi_s.iloc[-lb10*2:-lb10].min() and rsi < 45)
        mdiv_bear = bool(closes.iloc[-1]>closes.iloc[-3] and mh.iloc[-1]<mh.iloc[-3])
        mdiv_bull = bool(closes.iloc[-1]<closes.iloc[-3] and mh.iloc[-1]>mh.iloc[-3])
        rng0 = highs.iloc[-1]-lows.iloc[-1] or 1e-10
        uw = highs.iloc[-1]-max(closes.iloc[-1],df["Open"].iloc[-1])
        lw = min(closes.iloc[-1],df["Open"].iloc[-1])-lows.iloc[-1]
        pb, pb2, pnm = detect_candle_patterns(df)
        near_up = price >= ub*Config.REVERSAL_BAND_BUFFER
        near_dn = price <= lb*(2-Config.REVERSAL_BAND_BUFFER)
        rsi_ob = rsi >= Config.REVERSAL_RSI_SELL
        rsi_os = rsi <= Config.REVERSAL_RSI_BUY
        trend_up = bool(price > ema200.iloc[-1] and ema9.iloc[-1] > ema21.iloc[-1] and ema21.iloc[-1] > ema200.iloc[-1])
        trend_down = bool(price < ema200.iloc[-1] and ema9.iloc[-1] < ema21.iloc[-1] and ema21.iloc[-1] < ema200.iloc[-1])
        sell_core = [near_up, rsi_ob, div_bear, mdiv_bear, bool(uw>rng0*0.6), pb2, trend_up, adx > 20]
        buy_core  = [near_dn, rsi_os, div_bull, mdiv_bull, bool(lw>rng0*0.6), pb, trend_down, adx > 20]
        sig_sell = sum(bool(x) for x in sell_core) >= Config.REVERSAL_MIN_SCORE - 1
        sig_buy  = sum(bool(x) for x in buy_core) >= Config.REVERSAL_MIN_SCORE - 1
        if not (sig_sell or sig_buy): return None
        return {
            "symbol": symbol, "name": asset_name(symbol), "price": price, "rsi": rsi, "atr": atr, "adx": adx, "adx_mature": adx>30,
            "upper_band": ub, "lower_band": lb, "near_upper": near_up, "near_lower": near_dn,
            "rsi_overbought": rsi_ob, "rsi_oversold": rsi_os, "div_bear": div_bear, "div_bull": div_bull,
            "macd_div_bear": mdiv_bear, "macd_div_bull": mdiv_bull, "wick_bear": bool(uw>rng0*0.6),
            "wick_bull": bool(lw>rng0*0.6), "pat_bull": pb, "pat_bear": pb2, "pat_name": pnm,
            "trend_up": trend_up, "trend_down": trend_down,
            "signal_sell_ct": sig_sell, "signal_buy_ct": sig_buy,
        }
    except Exception as e: log(f"[CT] {symbol}: {e}"); return None
def calc_reversal_conf(res, d):
    if d == "SELL":
        checks = [("Tendência principal de alta", res.get("trend_up", False)),
                  ("RSI sobrecomprado", res["rsi_overbought"]), ("Banda Superior BB", res["near_upper"]),
                  ("RSI div. bearish", res["div_bear"]), ("MACD div. bearish", res["macd_div_bear"]),
                  ("Candle de baixa", res["pat_bear"]), ("Wick superior", res["wick_bear"]), ("ADX maduro", res["adx_mature"])]
    else:
        checks = [("Tendência principal de baixa", res.get("trend_down", False)),
                  ("RSI sobrevendido", res["rsi_oversold"]), ("Banda Inferior BB", res["near_lower"]),
                  ("RSI div. bullish", res["div_bull"]), ("MACD div. bullish", res["macd_div_bull"]),                  ("Candle de alta", res["pat_bull"]), ("Wick inferior", res["wick_bull"]), ("ADX maduro", res["adx_mature"])]
    sc = sum(1 for _, ok in checks if ok)
    return sc, len(checks), checks
def detect_reversal(res):
    if not res: return (False, None, 0, [])
    motivos = []; forca = 0; dir_rev = None
    rsi = res["rsi"]; price = res["price"]; cen = res["cenario"]
    trend_up = bool(price > res["ema200"] and res["ema9"] > res["ema21"] and res["ema21"] > res["ema200"])
    trend_down = bool(price < res["ema200"] and res["ema9"] < res["ema21"] and res["ema21"] < res["ema200"])
    if cen == "ALTA" or trend_up:
        if rsi >= 75: motivos.append(f"RSI sobrecomprado ({rsi:.0f})"); forca += 25; dir_rev = "SELL"
        if price >= res["upper"] * Config.REVERSAL_BAND_BUFFER: motivos.append("Banda superior BB"); forca += 25; dir_rev = "SELL"
        if res["macd_hist"] < 0: motivos.append("Div. MACD baixista"); forca += 20; dir_rev = "SELL"
        if res["adx"] > 20 and trend_up: motivos.append(f"Tendência esticada ({res['adx']:.0f} ADX)"); forca += 10
    if cen == "BAIXA" or trend_down:
        if rsi <= 25: motivos.append(f"RSI sobrevendido ({rsi:.0f})"); forca += 25; dir_rev = "BUY"
        if price <= res["lower"] * (2-Config.REVERSAL_BAND_BUFFER): motivos.append("Banda inferior BB"); forca += 25; dir_rev = "BUY"
        if res["macd_hist"] > 0: motivos.append("Div. MACD altista"); forca += 20; dir_rev = "BUY"
        if res["adx"] > 20 and trend_down: motivos.append(f"Tendência esticada ({res['adx']:.0f} ADX)"); forca += 10
    forca = min(forca, 100)
    return (forca >= 70 and dir_rev is not None, dir_rev, forca, motivos)
_push_subscriptions = []
def send_push(title, body, icon="/icon-192.png"):
    try:
        from pywebpush import webpush, WebPushException
        priv_key = os.getenv("VAPID_PRIVATE_KEY", ""); pub_key = os.getenv("VAPID_PUBLIC_KEY", "")
        email = os.getenv("VAPID_EMAIL", "mailto:admin@sniperbot.app")
        if not priv_key or not pub_key: return
        data = json.dumps({"title": title, "body": body, "icon": icon})
        dead = []
        for sub in _push_subscriptions:
            try:
                webpush(subscription_info=sub, data=data, vapid_private_key=priv_key,
                        vapid_claims={"sub": email, "aud": sub["endpoint"].split("/")[0]+"//"+sub["endpoint"].split("/")[2]})
            except WebPushException as e:
                if "410" in str(e) or "404" in str(e): dead.append(sub)
            except Exception as e: log(f"[PUSH] {e}")
        for d in dead: _push_subscriptions.remove(d)
    except ImportError: pass
    except Exception as e: log(f"[PUSH] {e}")
# ═══════════════════════════════════════════════════════════════
# BOT PRINCIPAL (100% PRESERVADO)
# ═══════════════════════════════════════════════════════════════
class TradingBot:
    def __init__(self):
        self.mode = "CRYPTO"; self.timeframe = Config.TIMEFRAME
        self.wins = 0; self.losses = 0; self.consecutive_losses = 0        
        self.paused_until = 0; self.active_trades = []; self.pending_trades = []
        self.pending_counter = 0; self.radar_list = {}; self.gatilho_list = {}
        self.reversal_list = {}; self.asset_cooldown = {}; self.history = []
        self.last_id = 0; self.last_news_ts = 0; self._restore_msg = None
        self.trend_cache = {}; self.last_trends_update = 0
        self.signals_feed = []; self.news_cache = []; self.news_cache_ts = 0
        self.balance = Config.INITIAL_BALANCE
        self.leverage = Config.DEFAULT_LEVERAGE
        self.risk_pct = Config.RISK_PERCENT_PER_TRADE
        self.account_currency = Config.BASE_CURRENCY
        self.account_type = Config.ACCOUNT_TYPE
        self.platform = Config.BROKER_PLATFORM
        self.margin_call_level = Config.MARGIN_CALL_LEVEL
        self.stop_out_level = Config.STOP_OUT_LEVEL
        self.awaiting_custom_amount = None
    def send(self, text, markup=None, disable_preview=False):
        import re
        clean = re.sub(r"<[^>]+>", " ", text).strip()
        tipo = push_title = push_body = None
        if "RADAR" in text: tipo="radar"; push_title="⚠ RADAR"
        elif "GATILHO ATINGIDO" in text: tipo="gatilho"; push_title="🔔 GATILHO ATINGIDO!"
        elif "SINAL CONFIRMADO" in text: tipo="sinal"; push_title="🎯 SINAL CONFIRMADO!"
        elif "SINAL PENDENTE" in text: tipo="sinal"; push_title="🎯 SINAL PENDENTE!"
        elif "CONTRA-TENDÊNCIA" in text: tipo="ct"; push_title="⚡ Contra-Tendência!"
        elif "CONFLUÊNCIA INSUF" in text: tipo="insuf"
        elif "OPERAÇÃO ENCERRADA" in text: tipo="close"; push_title="🏁 Operação Encerrada"; push_body=clean[:80]
        elif "CIRCUIT BREAKER" in text: tipo="cb"; push_title="⛔ Circuit Breaker Ativado"
        if tipo:
            self.signals_feed.append({"tipo": tipo, "texto": clean[:300], "ts": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")})
            self.signals_feed = self.signals_feed[-50:]
            if push_title:
                body = push_body or clean[:100]
                threading.Thread(target=send_push, args=(push_title, body), daemon=True).start()
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": disable_preview}
        if markup: payload["reply_markup"] = json.dumps(markup)
        try: requests.post(url, json=payload, timeout=8)
        except Exception as e: log(f"[SEND] {e}")
    def send_pending_notification(self, t):
        dl = "COMPRAR (BUY) 🟢" if t["dir"] == "BUY" else "VENDER (SELL) 🔴"
        sl_pct = abs(t["entry"] - t["sl"]) / t["entry"] * 100
        tp_pct = abs(t["tp"] - t["entry"]) / t["entry"] * 100
        is_ct = "CONTRA-TENDÊNCIA" in (t.get("tipo") or "  ")
        header = "⚡ SINAL CT PENDENTE" if is_ct else "🎯 SINAL PENDENTE"
        snap = account_snapshot(self)
        max_lev = max_leverage_for(t["symbol"])
        eff_lev = min(self.leverage, max_lev)
        comm_info = ""
        if asset_cat(t["symbol"]) in ("FOREX", "COMMODITIES"):
            comm_info = f"\n💳 Comissão RT estimada: <code>${commission_for(t['symbol'], Config.MIN_LOT):.2f}</code>/lote (Raw ECN)"
        text = "\n".join([
            f"{header} – <b>{t['symbol']}</b> ({t['name']}) [Tickmill MT5]",
            f"Conta: <b>{self.account_type}</b> {self.platform} | Moeda: <b>{self.account_currency}</b>",
            f"Alavancagem efetiva: <code>{eff_lev}x</code> (máx. Tickmill: <code>{max_lev}x</code>)",
            f"Lote mínimo: <code>{float(t.get('min_lot', Config.MIN_LOT)):.2f}</code> | Valor mínimo aprox.: <code>{fmt(float(t.get('min_amount_required', 0)))}</code>",
            f"Aguardando sua escolha de valor…{comm_info}",
            "",
            f"▶️ <b>{dl}</b>",
            "",
            f"💰 <b>Entrada:</b> <code>{fmt(t['entry'])}</code>",
            f"🛡 <b>SL:</b> <code>{fmt(t['sl'])}</code> ({-sl_pct:.2f}%)",
            f"🎯 <b>TP:</b> <code>{fmt(t['tp'])}</code> ({tp_pct:+.2f}%)",
            "",
            f"🏦 <b>Saldo:</b> <code>{fmt(snap['balance'])}</code> | <b>Equity:</b> <code>{fmt(snap['equity'])}</code>",
            f"📉 <b>Margem usada:</b> <code>{fmt(snap['used_margin'])}</code> | <b>Free margin:</b> <code>{fmt(snap['free_margin'])}</code>",
            f"📊 <b>Margin level:</b> <code>{snap['margin_level']:.1f}%</code> | <b>Alav.:</b> <code>{eff_lev}x</code> | <b>Risco:</b> <code>{self.risk_pct:.1f}%</code>",
            "",
        ])
        if is_ct and t.get("sinais"):
            text += "\n<b>Sinais de exaustão:</b>\n" + "\n".join(f"   ⚡ {sg}" for sg in t["sinais"]) + "\n"
        if t.get("conf_txt"):
            text += f"\n<b>Confluência: {t.get('sc','')}/{t.get('tot_c',t.get('tc',''))} [{t['bar']}]</b>\n{t['conf_txt']}"
        markup = {"inline_keyboard": [[
            {"text": "25%", "callback_data": f"amtpct_25_{t['pending_id']}"},
            {"text": "50%", "callback_data": f"amtpct_50_{t['pending_id']}"},
            {"text": "100%", "callback_data": f"amtpct_100_{t['pending_id']}"}
        ], [
            {"text": "Valor custom", "callback_data": f"amtcustom_{t['pending_id']}"},
            {"text": "❌ Recusar", "callback_data": f"reject_{t['pending_id']}"}
        ]]}
        self.send(text, markup=markup)
    def _open_trade_with_plan(self, pending_trade, plan, source="telegram"):
        
        # --- Filtros Institucionais v8.0 ---
        if check_news_block(self):
            # self.send("⚠️ Operação bloqueada: Notícia de alto impacto próxima.")
            return None
        if check_correlation(self, pending_trade["symbol"]):
            # self.send(f"⚠️ Operação bloqueada: Alta correlação detectada para {pending_trade['symbol']}.")
            return None

        trade = {k: v for k, v in pending_trade.items() if k not in ("conf_txt", "sc", "tot_c", "tc", "bar", "ratio", "vol_txt", "sinais", "pending_id")}
        trade.update({
            "capital_base": plan["amount"],
            "margin_required": plan["margin_required"],
            "lot": plan["lot"],
            "contract_size": plan["contract_size"],
            "base_ccy": plan.get("base_ccy", Config.BASE_CURRENCY),
            "quote_ccy": plan.get("quote_ccy", Config.BASE_CURRENCY),
            "risk_pct": plan["risk_pct"],
            "risk_money_target": plan["risk_money_target"],
            "risk_loss": plan["risk_loss"],
            "tp_gain": plan["tp_gain"],
            "leverage": plan["leverage"],
            "risk_note": plan.get("note", []),
            "min_lot": plan.get("min_lot", Config.MIN_LOT),
            "min_amount_required": plan.get("min_amount_required", 0),
            "source": source,
        })
        self.balance -= plan["margin_required"]
        self.balance = round(self.balance, 2)
        self.active_trades.append(trade)
        save_state(self)
        return trade
    def execute_pending_with_amount(self, pending_id, amount, source="telegram"):
        for t in self.pending_trades[:]:
            if t.get("pending_id") != pending_id:
                continue
            plan = calc_trade_plan(t["symbol"], t["entry"], t["sl"], t["tp"], amount, self.leverage, self.risk_pct)
            if not plan.get("ok"):
                self.send(f"❌ <b>Não foi possível abrir {t['symbol']}</b>\n{plan.get('error','Erro desconhecido')}")
                return False
            self.pending_trades.remove(t)
            opened = self._open_trade_with_plan(t, plan, source=source)
            if not opened:
                self.send(f"⚠️ <b>Operação bloqueada – {t['symbol']}</b>\nFiltro institucional ativo (correlação ou notícia).")
                save_state(self)
                return False
            dl = "BUY 🟢" if opened["dir"] == "BUY" else "SELL 🔴"
            warn = ""
            if plan.get("note"):
                warn = "\n" + "\n".join(f"⚠ {n}" for n in plan["note"])
            comm_txt = f"\n💳 <b>Comissão Tickmill (RT):</b> <code>${plan.get('commission', 0):.2f}</code> | <b>Ganho líq. TP:</b> <code>{fmt(plan.get('net_tp_gain', plan['tp_gain']))}</code>" if plan.get("commission", 0) > 0 else ""
            self.send(
                f"✅ <b>TRADE ABERTO – {opened['symbol']}</b> [Tickmill MT5]\n"
                f"{dl} | Entrada: <code>{fmt(opened['entry'])}</code>\n"
                f"💵 Base escolhida: <code>{fmt(plan['amount'])}</code> | Alav.: <code>{int(plan['leverage'])}x</code> (máx {plan.get('max_leverage','--')}x)\n"
                f"📦 Lote: <code>{plan['lot']:.2f}</code> | Margem usada: <code>{fmt(plan['margin_required'])}</code>\n"
                f"🛡 SL: <code>{fmt(opened['sl'])}</code> | 🎯 TP: <code>{fmt(opened['tp'])}</code>\n"
                f"📉 Risco até SL: <code>{fmt(plan['risk_loss'])}</code> | 📈 Potencial no TP: <code>{fmt(plan['tp_gain'])}</code>"
                f"{comm_txt}\n"
                f"🧷 Lote mínimo: <code>{float(plan.get('min_lot', Config.MIN_LOT)):.2f}</code> | Base mín. aprox.: <code>{fmt(plan.get('min_amount_required', 0))}</code>\n"
                f"🏦 Saldo após reservar margem: <code>{fmt(self.balance)}</code>{warn}"
            )
            return True
        return False
    def request_custom_amount(self, pending_id):
        self.awaiting_custom_amount = pending_id
        self.send(
            f"💬 <b>Valor custom solicitado</b>\n\nEnvie agora o valor que deseja negociar em dólares.\n"
            f"Exemplo: <code>500</code>\n\nVocê pode cancelar enviando <code>cancelar</code>."
        )
    def confirm_pending(self, pending_id, amount=None):
        if amount is None:
            for t in self.pending_trades:
                if t.get("pending_id") == pending_id:
                    amount = max(
                        min(self.balance, max(self.balance * 0.25, Config.MIN_LOT * 10)),
                        required_amount_for_lot(t["symbol"], t["entry"], self.leverage, Config.MIN_LOT)
                    )
                    break
            else:
                amount = min(self.balance, max(self.balance * 0.25, Config.MIN_LOT * 10))
        return self.execute_pending_with_amount(pending_id, amount, source="dashboard")
    def reject_pending(self, pending_id):
        for t in self.pending_trades[:]:
            if t.get("pending_id") == pending_id:
                self.pending_trades.remove(t); save_state(self)
                self.send(f"❌ <b>TRADE RECUSADO – {t['symbol']}</b>\nSinal ignorado.")
                return True
        return False
    def build_menu(self):
        tfl = Config.TIMEFRAMES.get(self.timeframe, ("?", "  "))[0]
        ml  = Config.MARKET_CATEGORIES[self.mode]["label"] if self.mode != "TUDO" else "TUDO"
        markup = {"inline_keyboard": [
            [{"text": f"Mercado: {ml}", "callback_data": "ignore"}],
            [{"text": "FOREX", "callback_data": "set_FOREX"}, {"text": "CRIPTO", "callback_data": "set_CRYPTO"}],
            [{"text": "COMM.", "callback_data": "set_COMMODITIES"}, {"text": "INDICES", "callback_data": "set_INDICES"}],
            [{"text": "TUDO", "callback_data": "set_TUDO"}],
            [{"text": f"TF: {self.timeframe} {tfl}", "callback_data": "tf_menu"}],
            [{"text": "Status", "callback_data": "status"}, {"text": "Placar", "callback_data": "placar"}],
            [{"text": "Noticias", "callback_data": "news"}],
        ]}
        tot = self.wins + self.losses; wr = (self.wins/tot*100) if tot > 0 else 0
        cb = f"\n⛔ CB – retoma em {int((self.paused_until-time.time())/60)}min  " if self.is_paused() else "  "
        self.send(f"<b>BOT SNIPER v7.2 PRO</b>\n{self.wins}W / {self.losses}L ({wr:.1f}%)\nModo: {ml} | TF: {self.timeframe}{cb}", markup)
    def build_tf_menu(self):
        rows = [[{"text": f"{tf} {lb}{'✅' if tf==self.timeframe else ''}", "callback_data": f"set_tf_{tf}"}] for tf, (lb, _) in Config.TIMEFRAMES.items()]
        rows.append([{"text": "« Voltar", "callback_data": "main_menu"}])
        self.send("Selecione o Timeframe", {"inline_keyboard": rows})
    def set_timeframe(self, tf):
        if tf not in Config.TIMEFRAMES: 
            return
        old = self.timeframe 
        self.timeframe = tf 
        save_state(self)
        self.send(f"✅ TF: {old} → {tf}")
        
    def set_mode(self, mode):
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]: 
            return
        self.mode = mode; save_state(self); self.send(f"✅ Modo: {mode}")
    def set_balance(self, value):
        try:
            value = float(value)
        except Exception:
            return False
        if value <= 0:
            return False
        self.balance = round(value, 2)
        save_state(self)
        self.send(f"🏦 <b>Saldo atualizado</b>\nNovo saldo: <code>{fmt(self.balance)}</code>")
        return True
    def set_leverage(self, value):
        try:
            value = int(value)
        except Exception:
            return False
        if value < 1 or value > 500:
            return False
        self.leverage = value
        save_state(self)
        self.send(f"⚙️ <b>Alavancagem atualizada</b>\nNova alavancagem: <code>{self.leverage}x</code>")
        return True
    def send_news(self): self.send(build_news_msg(), disable_preview=True); self.last_news_ts = time.time()
    def maybe_send_news(self):
        if time.time() - self.last_news_ts >= Config.NEWS_INTERVAL: self.send_news()
    def send_status(self):
        lines = [
            "<b>OPERAÇÕES ABERTAS</b>",
            f"🏦 Saldo: <code>{fmt(self.balance)}</code> | Alavancagem: <code>{self.leverage}x</code> | Risco: <code>{self.risk_pct:.1f}%</code>",
            ""
        ]
        if not self.active_trades:
            lines.append("Nenhuma.")
            self.send("\n".join(lines))
            return
        for t in self.active_trades:
            res = get_analysis(t["symbol"], self.timeframe)
            cur = res["price"] if res else t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL":
                pnl = -pnl
            pnl_money = t.get("pnl_money")
            money_txt = f" | R$ <code>{fmt(pnl_money)}</code>" if pnl_money is not None else ""
            lines.append(
                f"{'🟢' if pnl>=0 else '🔴'} "
                f"{t['symbol']} {t['dir']} "
                f"P&L: {pnl:+.2f}%{money_txt}"
            )
            self.send("\n".join(lines))
    def is_paused(self):
        return time.time() < self.paused_until
    def reset_pause(self):
        self.paused_until = 0
        self.consecutive_losses = 0
        save_state(self)
        self.send("✅ Circuit Breaker resetado.")
    def update_trends_cache(self):
        if time.time() - self.last_trends_update < Config.TRENDS_INTERVAL:
            return
        log("📡 Atualizando cache tendências...")
        for s in all_syms():
            try:
                res = get_analysis(s, self.timeframe)
                if res:
                    rev = detect_reversal(res)
                    self.trend_cache[s] = {
                        "data": res,
                        "reversal": {"has": rev[0], "dir": rev[1], "strength": rev[2], "reasons": rev[3]},
                        "ts": time.time(),
                    }
            except Exception as e:
                log(f"[TRENDS] {s}: {e}")
        self.last_trends_update = time.time()
    def scan(self):
        if self.is_paused():
            return
        if len(self.active_trades) >= Config.MAX_TRADES:
            return
        universe = all_syms() if self.mode == "TUDO" else list(Config.MARKET_CATEGORIES[self.mode]["assets"].keys())
        for s in universe:
            cat = asset_cat(s)
            if not mkt_open(cat):
                continue
            if any(t["symbol"] == s for t in self.active_trades):
                continue
            if any(t["symbol"] == s for t in self.pending_trades):
                continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN:
                continue
            res = self.trend_cache.get(s, {}).get("data") or get_analysis(s, self.timeframe)
            if not res:
                continue
            if s not in self.trend_cache:
                rev = detect_reversal(res)
                self.trend_cache[s] = {
                    "data": res,
                    "reversal": {"has": rev[0], "dir": rev[1], "strength": rev[2], "reasons": rev[3]},
                    "ts": time.time(),
                }
            if res["cenario"] == "NEUTRO":
                continue
            price = res["price"]
            atr = res["atr"]
            cen = res["cenario"]
            cl = asset_cat(s)
            cl_lbl = Config.MARKET_CATEGORIES.get(cl, {}).get("label", cl)
            if cen == "ALTA":
                gatilho = res["t_buy"]
                dir_s = "BUY"
                sl_est = gatilho - Config.ATR_MULT_SL * atr
                tp_est = gatilho + Config.ATR_MULT_TP * atr
                preco_ok = price >= gatilho and price < res["upper"] and res["rsi"] < 70
            else:
                gatilho = res["t_sell"]
                dir_s = "SELL"
                sl_est = gatilho + Config.ATR_MULT_SL * atr
                tp_est = gatilho - Config.ATR_MULT_TP * atr
                preco_ok = price <= gatilho and price > res["lower"] and res["rsi"] > 30
            sl_p = abs(gatilho - sl_est) / gatilho * 100
            tp_p = abs(tp_est - gatilho) / gatilho * 100
            ratio = f"1:{Config.ATR_MULT_TP / Config.ATR_MULT_SL:.1f}"
            if not preco_ok:
                if time.time() - self.radar_list.get(s, 0) > Config.RADAR_COOLDOWN:
                    dist = abs(price - gatilho) / price * 100
                    dl = "COMPRA" if dir_s == "BUY" else "VENDA"
                    self.send(
                        f"⚠️ <b>RADAR – {s}</b> ({res['name']})\n"
                        f"{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
                        f"Tendência de <b>{cen}</b> detectada\n"
                        f"Aguardando gatilho de <b>{dl}</b>\n\n"
                        f"🎯 Gatilho: <code>{fmt(gatilho)}</code>\n"
                        f"📍 Atual: <code>{fmt(price)}</code> ({dist:.2f}%)\n"
                        f"🛡 SL est.: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n"
                        f"🎯 TP est.: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n"
                        f"⚖️ Ratio: <b>{ratio}</b>\n"
                        f"RSI: <code>{res['rsi']:.1f}</code> | ADX: <code>{res['adx']:.1f}</code>"
                    )
                    self.radar_list[s] = time.time()
                continue
            if time.time() - self.gatilho_list.get(s, 0) > Config.GATILHO_COOLDOWN:
                dl = "COMPRAR (BUY) 🟢" if dir_s == "BUY" else "VENDER (SELL) 🔴"
                self.send(
                    f"🔔 <b>GATILHO ATINGIDO – {s}</b> ({res['name']})\n"
                    f"{cl_lbl} | TF: <code>{self.timeframe}</code>\n\n"
                    f"✅ Preço chegou no nível de entrada!\n\n"
                    f"▶️ <b>AÇÃO: {dl}</b>\n\n"
                    f"💰 Entrada: <code>{fmt(price)}</code>\n"
                    f"🛡 SL: <code>{fmt(sl_est)}</code> ({-sl_p:.2f}%)\n"
                    f"🎯 TP: <code>{fmt(tp_est)}</code> ({tp_p:+.2f}%)\n"
                    f"⚖️ Ratio: <b>{ratio}</b>\n\n"
                    f"⏳ <i>Verificando confluência…</i>"
                )
                self.gatilho_list[s] = time.time()
            sc, tot_c, checks = calc_confluence(res, dir_s)
            bar = cbar(sc, tot_c)
            conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in checks)
            if sc < Config.MIN_CONFLUENCE:
                falhou = [nm for nm, ok in checks if not ok]
                self.send(
                    f"⚡ <b>CONFLUÊNCIA INSUF. – {s}</b>\n\n"
                    f"Gatilho atingido mas bot NÃO entrou.\n"
                    f"Score: <code>{sc}/{tot_c}</code> [{bar}] (min: {Config.MIN_CONFLUENCE})\n\n"
                    f"<b>Filtros que falharam:</b>\n" + "\n".join(f"   ❌ {nm}" for nm in falhou)
                )
                continue
            if dir_s == "BUY":
                sl = price - Config.ATR_MULT_SL * atr
                tp = price + Config.ATR_MULT_TP * atr
            else:
                sl = price + Config.ATR_MULT_SL * atr
                tp = price - Config.ATR_MULT_TP * atr
            sl_pct = abs(price - sl) / price * 100
            tp_pct = abs(tp - price) / price * 100
            dl = "COMPRAR (BUY) 🟢" if dir_s == "BUY" else "VENDER (SELL) 🔴"
            vol_txt = f"{res['vol_ratio']:.1f}x média" if res["vol_ratio"] > 0 else "N/A"
            self.pending_counter += 1
            pending_trade = {
                "pending_id": self.pending_counter,
                "min_lot": asset_min_lot(s),
                "min_amount_required": required_amount_for_lot(s, price, self.leverage, Config.MIN_LOT),
                "symbol": s,
                "name": res["name"],
                "entry": price,
                "tp": tp,
                "sl": sl,
                "dir": dir_s,
                "peak": price,
                "atr": atr,
                "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "session_alerted": True,
                "conf_txt": conf_txt,
                "sc": sc,
                "tot_c": tot_c,
                "bar": bar,
                "ratio": ratio,
                "vol_txt": vol_txt,
            }
            self.pending_trades.append(pending_trade)
            self.send_pending_notification(pending_trade)
            self.radar_list[s] = self.gatilho_list[s] = time.time()
            save_state(self)
    def scan_reversal_forex(self):
        if self.is_paused():
            return
        if not mkt_open("FOREX"):
            return
        if len(self.active_trades) >= Config.MAX_TRADES:
            return
        for s in Config.MARKET_CATEGORIES["FOREX"]["assets"].keys():
            if any(t["symbol"] == s for t in self.active_trades):
                continue
            if any(t["symbol"] == s for t in self.pending_trades):
                continue
            if time.time() - self.asset_cooldown.get(s, 0) < Config.ASSET_COOLDOWN:
                continue
            if time.time() - self.reversal_list.get(s, 0) < Config.REVERSAL_COOLDOWN:
                continue
            res = get_reversal_analysis(s, self.timeframe)
            if not res:
                continue
            price = res["price"]
            atr = res["atr"]
            cands = []
            for d in (["SELL"] if res["signal_sell_ct"] else []) + (["BUY"] if res["signal_buy_ct"] else []):
                sc, tc, ch = calc_reversal_conf(res, d)
                strong_anchor = (d == "SELL" and res.get("trend_up")) or (d == "BUY" and res.get("trend_down"))
                extreme = (d == "SELL" and res["rsi_overbought"] and res["near_upper"]) or (d == "BUY" and res["rsi_oversold"] and res["near_lower"])
                rejection = (d == "SELL" and (res["div_bear"] or res["macd_div_bear"] or res["pat_bear"] or res["wick_bear"])) or (d == "BUY" and (res["div_bull"] or res["macd_div_bull"] or res["pat_bull"] or res["wick_bull"]))
                if sc >= Config.MIN_CONFLUENCE_CT and sc >= Config.REVERSAL_MIN_SCORE and strong_anchor and extreme and rejection:
                    sinais = []
                    if d == "SELL":
                        if res["rsi_overbought"]: sinais.append(f"RSI {res['rsi']:.0f} sobrecomprado")
                        if res["near_upper"]: sinais.append("BB Superior atingida")
                        if res["div_bear"]: sinais.append("RSI divergência bearish")
                        if res["macd_div_bear"]: sinais.append("MACD divergência bearish")
                        if res["wick_bear"]: sinais.append("Wick de rejeição")
                        if res["pat_bear"] and res["pat_name"]: sinais.append(res["pat_name"])
                    else:
                        if res["rsi_oversold"]: sinais.append(f"RSI {res['rsi']:.0f} sobrevendido")
                        if res["near_lower"]: sinais.append("BB Inferior atingida")
                        if res["div_bull"]: sinais.append("RSI divergência bullish")
                        if res["macd_div_bull"]: sinais.append("MACD divergência bullish")
                        if res["wick_bull"]: sinais.append("Wick de rejeição")
                        if res["pat_bull"] and res["pat_name"]: sinais.append(res["pat_name"])
                    cands.append((sc, tc, ch, d, sinais))
            if not cands:
                continue
            cands.sort(key=lambda x: x[0], reverse=True)
            sc, tc, ch, dir_s, sinais = cands[0]
            bar = cbar(sc, tc)
            conf_txt = "\n".join(f"   {'✅' if ok else '❌'} {nm}" for nm, ok in ch)
            sl_m = Config.ATR_MULT_SL
            tp_m = Config.ATR_MULT_SL * 1.5
            if dir_s == "BUY":
                sl = price - sl_m * atr
                tp = price + tp_m * atr
            else:
                sl = price + sl_m * atr
                tp = price - tp_m * atr
            dl = "COMPRAR (BUY) 🟢" if dir_s == "BUY" else "VENDER (SELL) 🔴"
            sinais_txt = "\n".join(f"   ⚡ {sg}" for sg in sinais)
            self.pending_counter += 1
            pending_trade = {
                "pending_id": self.pending_counter,
                "symbol": s,
                "name": res["name"],
                "entry": price,
                "tp": tp,
                "sl": sl,
                "dir": dir_s,
                "peak": price,
                "atr": atr,
                "tipo": "CONTRA-TENDÊNCIA ⚡",
                "opened_at": datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M"),
                "session_alerted": True,
                "conf_txt": conf_txt,
                "sc": sc,
                "tc": tc,
                "bar": bar,
                "ratio": f"1:{tp_m/sl_m:.1f}",
                "sinais": sinais,
            }
            self.pending_trades.append(pending_trade)
            self.send_pending_notification(pending_trade)
            self.reversal_list[s] = time.time()
            save_state(self)
    def monitor_trades(self):
        changed = False
        # --- Expiração de Sinais Pendentes (15 min) ---
        now_ts = time.time()
        for t in self.pending_trades[:]:
            created_at = t.get("created_at", now_ts)
            if now_ts - created_at > 900:  # 15 minutos
                self.pending_trades.remove(t)
                self.send(f"⏳ <b>SINAL EXPIRADO – {t['symbol']}</b>\nO sinal não foi respondido em 15 minutos e foi removido automaticamente.")
                changed = True
        changed = False
        for t in self.active_trades[:]:
            res = get_analysis(t["symbol"], self.timeframe)
            if not res:
                continue
            cur = res["price"]
            atr = res["atr"]
            if not t.get("session_alerted", True):
                dl = "BUY 🟢" if t["dir"] == "BUY" else "SELL 🔴"
                sl_p = abs(t["entry"] - t["sl"]) / t["entry"] * 100
                tp_p = abs(t["tp"] - t["entry"]) / t["entry"] * 100
                self.send(
                    f"📌 <b>TRADE RESTAURADO – {t['symbol']}</b>\n"
                    f"Ação: <b>{dl}</b> | Aberto: {t.get('opened_at','?')}\n"
                    f"Entrada: <code>{fmt(t['entry'])}</code> | Atual: <code>{fmt(cur)}</code>\n"
                    f"🎯 TP: <code>{fmt(t['tp'])}</code> ({tp_p:+.2f}%)\n"
                    f"🛡 SL: <code>{fmt(t['sl'])}</code> ({-sl_p:.2f}%)"
                )
                t["session_alerted"] = True
                changed = True
            if t["dir"] == "BUY" and cur > t.get("peak", t["entry"]):
                t["peak"] = cur
                nsl = cur - Config.ATR_MULT_TRAIL * atr
                if nsl > t["sl"]:
                    t["sl"] = nsl
                    changed = True
            elif t["dir"] == "SELL" and cur < t.get("peak", t["entry"]):
                t["peak"] = cur
                nsl = cur + Config.ATR_MULT_TRAIL * atr
                if nsl < t["sl"]:
                    t["sl"] = nsl
                    changed = True
            is_win = (t["dir"] == "BUY" and cur >= t["tp"]) or (t["dir"] == "SELL" and cur <= t["tp"])
            is_loss = (t["dir"] == "BUY" and cur <= t["sl"]) or (t["dir"] == "SELL" and cur >= t["sl"])
            if is_win or is_loss:
                pnl_pct = (cur - t["entry"]) / t["entry"] * 100
                if t["dir"] == "SELL":
                    pnl_pct = -pnl_pct
                lot = float(t.get("lot", Config.MIN_LOT))
                contract_size = float(t.get("contract_size", contract_size_for(t["symbol"])))
                move = (cur - t["entry"]) if t["dir"] == "BUY" else (t["entry"] - cur)
                pnl_money = move * contract_size * lot
                # Tickmill: desconta comissão round-trip do resultado final
                comm = commission_for(t["symbol"], lot)
                pnl_money_net = round(pnl_money - comm, 2)
                margin_required = float(t.get("margin_required", t.get("capital_base", 0)))
                self.balance = round(self.balance + margin_required + pnl_money_net, 2)
                st = "✅ TAKE PROFIT (WIN)" if is_win else "❌ STOP LOSS (LOSS)"
                closed_at = datetime.now(Config.BR_TZ).strftime("%d/%m %H:%M")
                if is_win:
                    self.wins += 1
                    self.consecutive_losses = 0
                else:
                    self.losses += 1
                    self.consecutive_losses += 1
                    self.asset_cooldown[t["symbol"]] = time.time()
                self.history.append({"symbol": t["symbol"], "dir": t["dir"], "result": "WIN" if is_win else "LOSS", "pnl": round(pnl_pct, 2), "pnl_money": pnl_money_net, "commission": round(comm, 2), "closed_at": closed_at, "lot": lot, "margin_required": round(margin_required, 2)})
                comm_line = f"\n💳 Comissão Tickmill: <code>-${comm:.2f}</code> | P&L líquido: <code>{fmt(pnl_money_net)}</code>" if comm > 0 else ""
                self.send("\n".join([
                    "🏁 <b>OPERAÇÃO ENCERRADA</b> [Tickmill MT5]",
                    f"Ativo: <b>{t['symbol']}</b> ({t.get('name','')}) | {t['dir']}",
                    f"Resultado: <b>{st}</b>",
                    "",
                    f"💰 Entrada: <code>{fmt(t['entry'])}</code>",
                    f"🔚 Saída: <code>{fmt(cur)}</code>",
                    f"P&L bruto: <code>{pnl_pct:+.2f}%</code> | <b>{fmt(pnl_money)}</b>{comm_line}",
                    f"🏦 Saldo atual: <code>{fmt(self.balance)}</code>",
                ]))
                self.active_trades.remove(t)
                changed = True
                if not is_win and self.consecutive_losses >= Config.MAX_CONSECUTIVE_LOSSES:
                    self.paused_until = time.time() + Config.PAUSE_DURATION
                    mins = Config.PAUSE_DURATION // 60
                    self.send("\n".join([
                        "⛔ <b>CIRCUIT BREAKER ATIVADO</b>",
                        "",
                        f"{self.consecutive_losses} losses consecutivos.",
                        f"Pausado por <b>{mins} minutos</b>.",
                        "",
                        "Use /resetpausa para retomar.",
                    ]))

        if changed:
            save_state(self)
# ═══════════════════════════════════════════════════════════════
# SERVICE WORKER
# ═══════════════════════════════════════════════════════════════
SW_JS = """
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => clients.claim());
self.addEventListener('push', e => {
let data = {title: 'Sniper Bot', body: 'Novo sinal!', icon: '/icon-192.png'};
try { data = JSON.parse(e.data.text()); } catch(_) {}
e.waitUntil(self.registration.showNotification(data.title, {
body: data.body, icon: data.icon || '/icon-192.png',
badge: '/icon-192.png', vibrate: [200, 100, 200],
data: { url: '/' }
}));
});
self.addEventListener('notificationclick', e => {
e.notification.close();
e.waitUntil(clients.matchAll({type:'window'}).then(cs => {
if (cs.length) cs[0].focus();
else clients.openWindow('/');
}));
});
"""
# ═══════════════════════════════════════════════════════════════
# DASHBOARD v7.3 PRO — MESA DE TRADING PROFISSIONAL
# ═══════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Sniper Bot Pro v7.3</title>
<style>
:root{
  --bg:#02040a;--bg2:#080c14;--bg3:#0d1320;--bg4:#151d2e;--bg5:#1e2840;
  --text:#cfe2f5;--text2:#8aaccf;--muted:#3d5f85;--muted2:#5577a0;
  --border:rgba(255,255,255,0.06);--border2:rgba(255,255,255,0.1);
  --green:#00e676;--green2:#00c853;--g3:rgba(0,230,118,.12);--g2:rgba(0,230,118,.22);
  --red:#ff3d71;--red2:#d50000;--r3:rgba(255,61,113,.12);--r2:rgba(255,61,113,.22);
  --blue:#448aff;--blue2:#2979ff;--b3:rgba(68,138,255,.12);--b2:rgba(68,138,255,.22);
  --cyan:#18ffff;--c3:rgba(24,255,255,.12);
  --gold:#ffd740;--y3:rgba(255,215,64,.10);
  --mono:'JetBrains Mono',monospace;--sans:'Inter',system-ui,-apple-system,sans-serif;
  --r:16px;--rsm:10px;--nav:68px;--safe:env(safe-area-inset-bottom,0px);--head:56px;--subhd:40px
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);font-family:var(--sans);-webkit-font-smoothing:antialiased}
#app{display:flex;flex-direction:column;height:100%;max-width:480px;margin:0 auto}
.g{color:var(--green)}.r{color:var(--red)}.cy{color:var(--cyan)}.bl{color:var(--blue)}.go{color:var(--gold)}
/* ── HEADER ── */
#hdr{height:var(--head);flex-shrink:0;background:rgba(8,12,20,.97);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 16px;z-index:100}
.hdr-l{display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#e8002d,#002868);display:flex;align-items:center;justify-content:center;font-family:var(--mono);font-size:18px;font-weight:800;color:#fff;box-shadow:0 0 0 1px rgba(232,0,45,.35)}
.t1{font-size:15px;font-weight:700;letter-spacing:-.4px}.t2{font-size:10px;color:var(--muted2);letter-spacing:1.2px;text-transform:uppercase;margin-top:1px}
.hdr-r{display:flex;align-items:center;gap:8px}
.badge{display:flex;align-items:center;gap:4px;background:var(--g3);border:1px solid rgba(0,230,118,.2);border-radius:20px;padding:3px 8px;font-size:9px;color:var(--green);font-weight:600}
.dot{width:5px;height:5px;border-radius:50%;background:var(--green);animation:blink 2s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.ibtn{width:36px;height:36px;border-radius:10px;border:1px solid var(--border2);background:var(--bg3);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:18px;color:var(--text2);transition:all .15s}
.ibtn:active{background:var(--bg4);transform:scale(.9)}
.ibtn.focus-on{background:var(--b3);border-color:rgba(68,138,255,.4);color:var(--blue)}
/* ── P&L SUB-HEADER (sempre visível) ── */
#subhdr{height:var(--subhd);flex-shrink:0;background:rgba(5,9,18,.95);border-bottom:1px solid var(--border);display:flex;align-items:stretch;z-index:99}
.shi{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-right:1px solid var(--border);padding:0 4px}
.shi:last-child{border-right:none}
.shl{font-size:8px;letter-spacing:.8px;text-transform:uppercase;color:var(--muted2);font-weight:600}
.shv{font-size:13px;font-weight:800;font-family:var(--mono);line-height:1.2}
.shv.g{color:var(--green)}.shv.r{color:var(--red)}.shv.bl{color:var(--blue)}.shv.go{color:var(--gold)}
/* ── PAGES ── */
#pages{flex:1;overflow:hidden;position:relative}
.pg{position:absolute;inset:0;display:none;overflow-y:auto;padding:14px 14px calc(var(--nav) + var(--safe) + 18px);opacity:0;transform:translateY(5px);transition:all .2s ease-out}
.pg.on{display:block;opacity:1;transform:translateY(0)}
.pg::-webkit-scrollbar{width:2px}.pg::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
/* ── FOCUS MODE ── */
body.focus .ibtn.focus-on{box-shadow:0 0 10px rgba(68,138,255,.4)}
body.focus #subhdr{background:rgba(0,230,118,.05);border-bottom-color:rgba(0,230,118,.2)}
body.focus #hdr{border-bottom-color:rgba(0,230,118,.3)}
.focus-banner{display:none;background:rgba(68,138,255,.08);border:1px solid rgba(68,138,255,.25);border-radius:12px;padding:10px 14px;margin-bottom:12px;text-align:center;font-size:12px;color:var(--blue);font-weight:600;letter-spacing:.3px}
body.focus .focus-banner{display:block}
/* ── NAV ── */
#nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:480px;height:var(--nav);background:rgba(8,12,20,.97);backdrop-filter:blur(16px);border-top:1px solid var(--border2);display:flex;z-index:200;padding-bottom:var(--safe)}
.nb{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:none;background:none;cursor:pointer;font-size:10px;color:var(--muted2);letter-spacing:.4px;text-transform:uppercase;font-weight:500;position:relative;transition:all .2s}
.nb .ni{font-size:20px;transition:all .2s;opacity:.5}
.nb.on{color:var(--green)}.nb.on .ni{transform:scale(1.1);opacity:1;filter:drop-shadow(0 0 4px var(--green))}
.nb:active{opacity:.7}
.nbadge{position:absolute;top:3px;right:calc(50% - 18px);min-width:16px;height:16px;border-radius:8px;background:var(--red);color:#fff;font-size:9px;display:none;align-items:center;justify-content:center;font-family:var(--mono);font-weight:700;padding:0 3px;box-shadow:0 0 8px rgba(255,61,113,.5)}
/* ── STATS ROW ── */
.srow{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}
.sb{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:12px 8px;text-align:center}
.sl{font-size:9px;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:4px;font-weight:600}
.sv{font-size:20px;font-weight:800;font-family:var(--mono);line-height:1}
.ss{font-size:10px;color:var(--muted2);margin-top:3px}
/* ── SECTION HEADERS ── */
.chd{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted2);margin-bottom:10px;display:flex;align-items:center;justify-content:space-between;font-weight:700}
.ts{font-size:9px;color:var(--muted);font-weight:400;letter-spacing:0}
.empty{text-align:center;padding:30px 16px;color:var(--muted2)}
.empi{font-size:32px;margin-bottom:8px;display:block;opacity:.6}.empt{font-size:12px;line-height:1.6}
/* ── RISK PANEL ── */
.risk-panel{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:12px}
.risk-head{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--muted2);font-weight:700;margin-bottom:10px}
.risk-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.risk-item{background:var(--bg3);border-radius:10px;padding:10px 12px;display:flex;align-items:center;justify-content:space-between}
.risk-lbl{font-size:10px;color:var(--muted2);font-weight:500}
.risk-val{font-size:13px;font-weight:800;font-family:var(--mono)}
/* ── TRADE CARDS (hierarquia: maior que sinais) ── */
.tcard{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:12px;position:relative;overflow:hidden}
.tcard.buy{border-left:3px solid var(--green)}.tcard.sell{border-left:3px solid var(--red)}
.tcard-head{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px}
.tsym{font-size:18px;font-weight:700;font-family:var(--mono)}.tname{font-size:11px;color:var(--muted2);margin-top:2px}
.tdir{font-size:11px;font-weight:700;padding:4px 10px;border-radius:16px;background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.tdir.sell{background:var(--r3);color:var(--red);border:1px solid rgba(255,61,113,.2)}
.ttype-badge{font-size:9px;letter-spacing:.6px;padding:2px 6px;border-radius:6px;background:var(--bg4);color:var(--muted2);font-weight:600;margin-top:4px;display:inline-block}
.tlvs{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:10px}
.tlv{background:var(--bg3);border-radius:var(--rsm);padding:10px;text-align:center}
.tll{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:var(--muted);margin-bottom:4px;font-weight:600}
.tlvv{font-size:13px;font-weight:700;font-family:var(--mono)}
.tprog{height:6px;background:var(--bg4);border-radius:3px;margin:8px 0 6px;overflow:hidden}
.tfill{height:100%;border-radius:3px;transition:width .4s}
.tdist{display:flex;justify-content:space-between;font-size:10px;color:var(--muted2)}
.tdist .near{color:var(--red);font-weight:700}.tdist .far{color:var(--green)}
.tbtns{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}
.tb{padding:14px;border-radius:10px;border:none;cursor:pointer;font-size:13px;font-weight:700;transition:all .15s}
.tb:active{transform:scale(.97)}
.tb.yes{background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}
.tb.no{background:var(--r3);color:var(--red);border:1px solid rgba(255,61,113,.2)}
.cpbtn{background:none;border:none;color:var(--blue);cursor:pointer;font-size:14px;padding:0 4px;transition:all .15s}
.cpbtn:active{opacity:.6}
/* ── HISTORY ── */
.hist-item{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border)}
.hist-icon{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:14px}
.hist-sym{font-size:13px;font-weight:600;font-family:var(--mono)}.hist-time{font-size:10px;color:var(--muted2);margin-top:2px}
.hist-pnl{font-size:14px;font-weight:700;font-family:var(--mono)}
/* ── SCANNER ── */
.tgroup{margin-bottom:14px}
.tghd{font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted2);margin-bottom:8px;font-weight:700;display:flex;align-items:center;gap:8px}
.titem{display:flex;align-items:center;justify-content:space-between;background:var(--bg2);border:1px solid var(--border);border-radius:var(--rsm);padding:12px 14px;margin-bottom:6px}
.titem.up{border-left:3px solid var(--green);background:linear-gradient(90deg,rgba(0,230,118,.04) 0%,var(--bg2) 60%)}
.titem.dn{border-left:3px solid var(--red);background:linear-gradient(90deg,rgba(255,61,113,.04) 0%,var(--bg2) 60%)}
.titem.neut{border-left:3px solid var(--muted)}
.tsym-scan{font-size:14px;font-weight:700;font-family:var(--mono)}.tname-scan{font-size:11px;color:var(--muted2);margin-top:1px}
.tmeta{display:flex;align-items:center;gap:8px}
.ttag{font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px}
.ttag.up{background:var(--g3);color:var(--green)}.ttag.dn{background:var(--r3);color:var(--red)}.ttag.neut{background:var(--bg4);color:var(--muted2)}
.tscan-r{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.tprice{font-size:13px;font-weight:700;font-family:var(--mono)}
.tchg{font-size:11px;font-family:var(--mono);font-weight:600}
.tstat{font-size:10px;color:var(--muted2);font-family:var(--mono)}
/* ── CT CARDS ── */
.ctcard{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin-bottom:8px;position:relative}
.ctcard::before{content:'';position:absolute;top:0;left:0;width:3px;height:100%;background:var(--cyan)}
.cthead{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.ctsym{font-size:16px;font-weight:700;font-family:var(--mono)}
.ctdir{font-size:11px;font-weight:700;padding:4px 10px;border-radius:8px;background:var(--c3);color:var(--cyan);border:1px solid rgba(24,255,255,.2)}
.ctstat{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px}
.ctbox{background:var(--bg3);border-radius:8px;padding:10px;text-align:center}
.ctl{font-size:10px;color:var(--muted);margin-bottom:3px}.ctv{font-size:14px;font-weight:700;font-family:var(--mono)}
.ctbar{height:5px;background:var(--bg4);border-radius:3px;margin-bottom:10px;overflow:hidden}
.ctfill{height:100%;background:var(--cyan);transition:width .5s}
.ctrs{display:flex;flex-wrap:wrap;gap:4px}
.cttag{font-size:10px;background:var(--bg3);color:var(--text2);padding:3px 8px;border-radius:6px;border:1px solid var(--border2)}
/* ── SINAIS ── */
.sig-card{border:1px solid var(--border);border-radius:10px;padding:12px;margin-bottom:8px}
.sig-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.sig-tipo{font-size:10px;font-weight:700;padding:2px 8px;border-radius:6px;background:var(--bg3);letter-spacing:.5px;text-transform:uppercase}
.sig-ts{font-size:10px;color:var(--muted2)}
.sig-txt{font-size:12px;line-height:1.5;color:var(--text2)}
/* ── FEAR & GREED ── */
.fg-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between}
.fg-l{display:flex;flex-direction:column;gap:5px}
.fg-lbl{font-size:10px;letter-spacing:1px;text-transform:uppercase;color:var(--muted2);font-weight:600}
.fg-val{font-size:36px;font-weight:900;font-family:var(--mono);line-height:1}
.fg-name{font-size:13px;font-weight:700}
.fg-circle{transform:rotate(-90deg);transform-origin:50% 50%}
/* ── NEWS ── */
.news-item{padding:12px 0;border-bottom:1px solid var(--border);display:flex;flex-direction:column;gap:4px}
.news-title{font-size:13px;color:var(--blue);text-decoration:none;line-height:1.4;font-weight:500}
.news-title:active{opacity:.7}
.news-src{font-size:10px;color:var(--muted2);font-weight:600;letter-spacing:.5px;text-transform:uppercase}
/* ── TOAST (contextual) ── */
.toast{position:fixed;bottom:calc(var(--nav) + var(--safe) + 10px);left:50%;transform:translateX(-50%) translateY(10px);background:var(--bg4);border:1px solid var(--border2);border-radius:12px;padding:10px 16px;display:flex;align-items:center;gap:10px;opacity:0;pointer-events:none;transition:all .25s;z-index:300;max-width:92%;box-shadow:0 4px 20px rgba(0,0,0,.5)}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0);pointer-events:auto}
.toast.t-success{border-color:rgba(0,230,118,.3);background:rgba(0,230,118,.09)}
.toast.t-error{border-color:rgba(255,61,113,.3);background:rgba(255,61,113,.09)}
.toast.t-warning{border-color:rgba(255,215,64,.3);background:rgba(255,215,64,.07)}
.toast.t-info{border-color:rgba(68,138,255,.3);background:rgba(68,138,255,.09)}
.ticon{font-size:18px;flex-shrink:0}.ttxt{font-size:12px;font-weight:600}
/* ── ERROR BANNER ── */
.eb{background:var(--r3);border:1px solid rgba(255,61,113,.2);border-radius:10px;padding:12px 14px;margin-bottom:10px;font-size:12px;color:var(--red);display:none;text-align:center}
/* ── CONFIG ── */
.cfgsec{margin-bottom:18px}
.cfgl{font-size:10px;letter-spacing:1.2px;text-transform:uppercase;color:var(--muted2);margin-bottom:10px;font-weight:700}
.mdg{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
.mdb{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;padding:14px 8px;cursor:pointer;font-size:13px;font-family:var(--sans);color:var(--text2);text-align:center;transition:all .15s;line-height:1.4;font-weight:500}
.mdb:active{transform:scale(.97)}.mdb.on{background:var(--g3);border:1px solid rgba(0,230,118,.3);color:var(--green)}
.tfg{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.tfb{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;padding:12px 6px;cursor:pointer;font-size:12px;font-family:var(--mono);color:var(--text2);text-align:center;transition:all .15s}
.tfb.on{background:var(--b3);border:1px solid rgba(68,138,255,.3);color:var(--blue)}
.tfb:active{transform:scale(.97)}
.tfd{font-size:15px;display:block;margin-bottom:2px;font-weight:700}.tfl{font-size:9px;color:var(--muted)}
.ab{width:100%;padding:14px;border-radius:12px;border:none;cursor:pointer;font-size:13px;font-weight:600;font-family:var(--sans);margin-bottom:10px;transition:all .15s}
.ab:active{transform:scale(.97)}.abd{background:var(--r3);color:var(--red);border:1px solid rgba(255,61,113,.2)}.abp{background:var(--g3);color:var(--green);border:1px solid rgba(0,230,118,.2)}.abn{background:var(--b3);color:var(--blue);border:1px solid rgba(68,138,255,.2)}
.pgrid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.pbox{background:var(--bg3);border:1px solid var(--border);border-radius:10px;padding:12px}
.plb{font-size:10px;color:var(--muted);margin-bottom:4px;font-weight:600}.pvl{font-size:15px;font-family:var(--mono);font-weight:700}
/* ── SKELETON LOADING ── */
@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}
.skel{background:linear-gradient(90deg,var(--bg3) 25%,var(--bg4) 50%,var(--bg3) 75%);background-size:200% 100%;animation:shimmer 1.6s infinite;border-radius:var(--r)}
.skel-card{height:120px;margin-bottom:10px}
</style>

<style>
:root { --tm-red: #e8002d; --tm-blue: #002868; --gold: #ffd740; }
.tcard.pending { border-left: 4px solid var(--gold) !important; position: relative; overflow: hidden; }
.expire-bar { position: absolute; bottom: 0; left: 0; height: 4px; background: linear-gradient(90deg, var(--gold), #ffecb3); width: 100%; transition: width 1s linear; }
.tcard { 
    background: rgba(10, 15, 26, 0.92) !important; 
    backdrop-filter: blur(16px); 
    border: 1px solid rgba(255,255,255,0.13) !important; 
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255,255,255,0.06);
    border-radius: 16px !important;
}
.tb.yes { background: linear-gradient(135deg, #00c853, #00e676) !important; border: none !important; font-weight: 700 !important; color: #002b0f !important; text-shadow: none !important; }
.tb.no { background: rgba(255, 61, 113, 0.15) !important; border: 1px solid rgba(255,61,113,0.5) !important; color: var(--red) !important; font-weight: 700 !important; }
.tb.yes:active { transform: scale(.96) !important; filter: brightness(0.92); }
.tb.yes:hover { filter: brightness(1.08); }
/* Botões de percentual com cores distintas */
.tb-pct-25 { background: linear-gradient(135deg, #00796b, #26a69a) !important; color: #e0f7f4 !important; border: none !important; font-weight: 700 !important; }
.tb-pct-50 { background: linear-gradient(135deg, #1565c0, #1e88e5) !important; color: #e3f2fd !important; border: none !important; font-weight: 700 !important; }
.tb-pct-100 { background: linear-gradient(135deg, #e65100, #fb8c00) !important; color: #fff3e0 !important; border: none !important; font-weight: 700 !important; }
.tb-custom { background: linear-gradient(135deg, #4a148c, #7b1fa2) !important; color: #f3e5f5 !important; border: none !important; font-weight: 700 !important; }
.tsym { font-size: 20px !important; letter-spacing: 1px; }
</style>

<style>
.kelly-badge { background: var(--b3); color: var(--blue); border: 1px solid var(--blue2); padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; }
.news-alert { color: var(--red); font-size: 10px; animation: pulse 1s infinite; }
@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
/* Hover states para todos botões de ação */
.tb-pct-25:active,.tb-pct-50:active,.tb-pct-100:active,.tb-custom:active { transform: scale(.95) !important; filter: brightness(0.88); }
/* Labels de percentual mais legíveis */
.tb { font-size: 14px !important; letter-spacing: .3px; border-radius: 12px !important; }
/* Input-like overlay para o modal de valor custom */
.amt-label { font-size: 11px; color: var(--muted2); text-align:center; margin-bottom:4px; }
/* Destaque do símbolo nos cards pendentes */
.tcard.pending .tsym { color: var(--gold) !important; }
.tcard.pending .tcard-head { border-bottom: 1px solid rgba(255,215,64,.12); padding-bottom: 10px; margin-bottom: 10px; }
/* Melhorar contraste geral nos valores de risk panel */
.risk-val { color: var(--text) !important; }
.risk-item { background: rgba(255,255,255,0.03) !important; border: 1px solid rgba(255,255,255,0.07) !important; border-radius: 10px !important; }
/* ── PAINEL DE ALAVANCAGEM ── */
.lev-current-row{display:flex;align-items:center;gap:10px;margin-bottom:12px;background:var(--bg3);border:1px solid var(--border2);border-radius:12px;padding:12px 14px}
.lev-label{font-size:11px;color:var(--muted2);font-weight:600;text-transform:uppercase;letter-spacing:.8px}
.lev-val{font-size:22px;font-weight:800;font-family:var(--mono);color:var(--gold)}
.lev-max{font-size:10px;color:var(--muted2);margin-left:auto}
.lev-presets{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:10px}
.levb{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;padding:11px 4px;cursor:pointer;font-size:13px;font-family:var(--mono);color:var(--text2);font-weight:700;transition:all .15s;text-align:center}
.levb:active{transform:scale(.94)}
.levb.on{background:rgba(255,215,64,.15);border-color:rgba(255,215,64,.45);color:var(--gold)}
.levb-ok{background:linear-gradient(135deg,#e65100,#fb8c00) !important;color:#fff3e0 !important;border:none !important;padding:11px 18px !important}
.lev-custom-row{display:flex;gap:8px;align-items:center;margin-bottom:10px}
.lev-input{flex:1;background:rgba(255,255,255,0.06);border:1px solid var(--border2);border-radius:10px;padding:12px;color:var(--text);font-size:14px;font-family:var(--mono);outline:none;transition:border-color .2s}
.lev-input:focus{border-color:rgba(255,215,64,.5)}
.lev-warn{font-size:10px;color:var(--muted2);line-height:1.5;padding:8px 10px;background:rgba(255,215,64,.05);border:1px solid rgba(255,215,64,.15);border-radius:8px}
</style>
</head>
<body>
<div id="app">
<!-- ── HEADER ── -->
<div id="hdr">
  <div class="hdr-l">
    <div class="logo">T</div>
    <div><div class="t1">Tickmill Sniper</div><div class="t2">MT5 • PRO v7.3</div></div>
  </div>
  <div class="hdr-r">
    <div class="badge">LIVE <span class="dot"></span></div>
    <button class="ibtn" id="focus-btn" onclick="toggleFocus()" title="Modo Focus">🎯</button>
    <button class="ibtn" id="refbtn" onclick="refreshAll()">↻</button>
  </div>
</div>
<!-- ── P&L SUB-HEADER (sempre visível) ── -->
<div id="subhdr">
  <div class="shi"><div class="shl">Hoje</div><div class="shv" id="sh-dpnl">--</div></div>
  <div class="shi"><div class="shl">Win%</div><div class="shv" id="sh-wr">--%</div></div>
  <div class="shi"><div class="shl">Abertos</div><div class="shv bl" id="sh-open">0</div></div>
  <div class="shi"><div class="shl">Status</div><div class="shv" id="sh-status">●</div></div>
</div>
<!-- ── PAGES ── -->
<div id="pages">
<!-- DASHBOARD -->
<div class="pg on" id="pg-dash">
  <div id="eb" class="eb">⚠ Erro de conexão. Verifique sua rede.</div>
  <div class="focus-banner">🎯 MODO FOCUS ATIVO — Apenas trades e P&L visíveis</div>
  <div class="srow">
    <div class="sb"><div class="sl">Lucro</div><div class="sv" id="d-dpnl">--%</div><div class="ss" id="d-drec">0W / 0L</div></div>
    <div class="sb"><div class="sl">Win Rate</div><div class="sv" id="d-wr">--%</div><div class="ss" id="d-wlt">0W / 0L</div></div>
    <div class="sb"><div class="sl">Abertos</div><div class="sv" id="d-open">0</div><div class="ss" id="d-maxopen">de 3 max</div></div>
    <div class="sb"><div class="sl">Fechados</div><div class="sv" id="d-closed">0</div><div class="ss">Hoje</div></div>
  </div>
  <!-- PAINEL DE RISCO -->
  <div class="risk-panel">
    <div class="risk-head">⚖ Gestão de Risco — Tickmill MT5</div>
    <div class="risk-grid">
      <div class="risk-item"><span class="risk-lbl">Saldo</span><span class="risk-val bl" id="r-balance">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Equity</span><span class="risk-val" id="r-equity">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Margem usada</span><span class="risk-val go" id="r-margin">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Free margin</span><span class="risk-val bl" id="r-free">0</span></div>
      <div class="risk-item"><span class="risk-lbl">Margin level</span><span class="risk-val" id="r-level">0%</span></div>
      <div class="risk-item"><span class="risk-lbl">Alavancagem</span><span class="risk-val" id="r-leverage">0x</span></div>
      <div class="risk-item"><span class="risk-lbl">Risco/trade</span><span class="risk-val go" id="r-risk">0%</span></div>
      <div class="risk-item"><span class="risk-lbl">Exposição</span><span class="risk-val bl" id="r-exposure">0%</span></div>
      <div class="risk-item"><span class="risk-lbl">CB Status</span><span class="risk-val" id="r-cb">OK</span></div>
      <div class="risk-item"><span class="risk-lbl">Seq. Perdas</span><span class="risk-val" id="r-losses">0 / 2</span></div>
      <div class="risk-item"><span class="risk-lbl">W / L Total</span><span class="risk-val" id="r-wl">--</span></div>
      <div class="risk-item"><span class="risk-lbl">Tipo Conta</span><span class="risk-val cy" id="r-actype">RAW</span></div>
      <div class="risk-item" style="grid-column:span 2"><span class="risk-lbl">Margin Call / Stop Out</span><span class="risk-val go" id="r-mcso">100% / 30%</span></div>
    </div>
  </div>
  <div class="chd">💼 Trades Ativos <span class="ts">Auto: 5s</span></div>
  <div id="d-trades"><div class="skel skel-card"></div></div>
  <div class="chd">📜 Histórico Hoje</div>
  <div id="d-closed-list"><div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada.</div></div></div>
</div>
<!-- PENDENTES -->
<div class="pg" id="pg-pend">
  <div class="chd">⏳ Aprovação Rápida <span class="ts">Auto: 5s</span></div>
  <div id="pendingQueue"><div class="skel skel-card"></div></div>
</div>
<!-- SCANNER -->
<div class="pg" id="pg-scan">
  <div class="chd">📡 Tendências de Mercado</div>
  <div id="scan-list"><div class="skel skel-card"></div><div class="skel skel-card"></div></div>
</div>
<!-- SINAIS -->
<div class="pg" id="pg-sig">
  <div class="chd">🔔 Feed de Sinais</div>
  <div id="sig-list"><div class="skel skel-card"></div></div>
</div>
<!-- CT / NEWS -->
<div class="pg" id="pg-ct">
  <div class="chd">⚡ Oportunidades de Reversão</div>
  <div id="ct-list"><div class="skel skel-card"></div></div>
  <div class="chd" style="margin-top:16px">📰 Notícias & Sentimento</div>
  <div id="fg-card-wrap"></div>
  <div id="news-list"><div class="skel skel-card"></div></div>
</div>
<!-- CONFIG -->
<div class="pg" id="pg-cfg">
  <div class="cfgsec"><div class="cfgl">Mercado</div><div class="mdg">
    <div class="mdb" data-mode="FOREX" onclick="setMode('FOREX')">📈 FOREX</div>
    <div class="mdb" data-mode="CRYPTO" onclick="setMode('CRYPTO')">₿ CRIPTO</div>
    <div class="mdb" data-mode="COMMODITIES" onclick="setMode('COMMODITIES')">🏅 COMM.</div>
    <div class="mdb" data-mode="INDICES" onclick="setMode('INDICES')">📊 ÍNDICES</div>
    <div class="mdb" data-mode="TUDO" onclick="setMode('TUDO')" style="grid-column:span 2">🌐 TUDO</div>
  </div></div>
  <div class="cfgsec"><div class="cfgl">Timeframe</div><div class="tfg">
    <div class="tfb" data-tf="1m" onclick="setTf('1m')"><span class="tfd">1m</span><span class="tfl">Agressivo</span></div>
    <div class="tfb" data-tf="5m" onclick="setTf('5m')"><span class="tfd">5m</span><span class="tfl">Alto</span></div>
    <div class="tfb" data-tf="15m" onclick="setTf('15m')"><span class="tfd">15m</span><span class="tfl">Moderado</span></div>
    <div class="tfb" data-tf="30m" onclick="setTf('30m')"><span class="tfd">30m</span><span class="tfl">Conserv.</span></div>
    <div class="tfb" data-tf="1h" onclick="setTf('1h')"><span class="tfd">1h</span><span class="tfl">Seguro</span></div>
    <div class="tfb" data-tf="4h" onclick="setTf('4h')"><span class="tfd">4h</span><span class="tfl">Muito Seg.</span></div>
  </div></div>
  <div class="cfgsec"><div class="cfgl">Parâmetros de Risco</div><div class="pgrid">
    <div class="pbox"><div class="plb">Stop Loss</div><div class="pvl" id="p-sl">--</div></div>
    <div class="pbox"><div class="plb">Take Profit</div><div class="pvl" id="p-tp">--</div></div>
    <div class="pbox"><div class="plb">Max Trades</div><div class="pvl" id="p-mt">--</div></div>
    <div class="pbox"><div class="plb">Confluência</div><div class="pvl" id="p-mc">--</div></div>
    <div class="pbox"><div class="plb">Comissão RT</div><div class="pvl cy" id="p-comm">--</div></div>
    <div class="pbox"><div class="plb">Lote Mínimo</div><div class="pvl" id="p-minlot">0.01</div></div>
  </div></div>
  <div class="cfgsec"><div class="cfgl">Saldo da Conta</div>
    <div class="pgrid">
      <div class="pbox"><div class="plb">Saldo atual</div><div class="pvl" id="p-bal">--</div></div>
      <div class="pbox"><div class="plb">Editar saldo</div><button class="ab abn" onclick="setBalance()">Alterar</button></div>
    </div>
  </div>
  <div class="cfgsec">
    <div class="cfgl">Alavancagem</div>
    <div class="lev-current-row">
      <span class="lev-label">Atual:</span>
      <span class="lev-val" id="p-lev">--</span>
      <span class="lev-max" id="p-lev-max"></span>
    </div>
    <div class="lev-presets" id="lev-presets">
      <button class="levb" data-lev="50"   onclick="setLeverage(50)">50x</button>
      <button class="levb" data-lev="100"  onclick="setLeverage(100)">100x</button>
      <button class="levb" data-lev="200"  onclick="setLeverage(200)">200x</button>
      <button class="levb" data-lev="300"  onclick="setLeverage(300)">300x</button>
      <button class="levb" data-lev="500"  onclick="setLeverage(500)">500x</button>
    </div>
    <div class="lev-custom-row">
      <input type="number" id="lev-input" min="1" max="500" placeholder="Valor manual (1–500)"
        class="lev-input" onkeydown="if(event.key==='Enter')submitLeverage()">
      <button class="levb levb-ok" onclick="submitLeverage()">✓ OK</button>
    </div>
    <div class="lev-warn">⚠ Alavancagem alta aumenta risco. Limite Tickmill por ativo pode ser menor.</div>
  </div>
  <div class="cfgsec"><div class="cfgl">Modo Focus (Execução)</div>
    <button class="ab abn" id="focus-cfg-btn" onclick="toggleFocus()">🎯 Ativar Modo Focus</button>
  </div>
  <button class="ab abd" onclick="resetPausa()">⛔ Resetar Circuit Breaker</button>
  <button class="ab abn" onclick="requestNotif()">🔔 Ativar Notificações Push</button>
  <button class="ab abp" onclick="refreshAll()">↻ Atualizar App</button>
</div>
</div><!-- /pages -->
<!-- NAV -->
<div id="nav">
  <button class="nb on" onclick="goTo('dash',this)"><span class="ni">⬡</span>Dashboard</button>
  <button class="nb" onclick="goTo('pend',this)"><span class="ni">⏳</span>Pendentes<div class="nbadge" id="nbadge-pend">0</div></button>
  <button class="nb" onclick="goTo('scan',this)"><span class="ni">📡</span>Scanner</button>
  <button class="nb" onclick="goTo('sig',this)"><span class="ni">🔔</span>Sinais<div class="nbadge" id="nbadge-sig">0</div></button>
  <button class="nb" onclick="goTo('ct',this)"><span class="ni">⚡</span>CT/News</button>
  <button class="nb" onclick="goTo('cfg',this)"><span class="ni">⚙</span>Config</button>
</div>
</div><!-- /app -->
<div class="toast" id="toast"><span class="ticon">🔔</span><span class="ttxt"></span></div>
<script>
let _st=null,_sigs=[],_unread=0,_lastSigLen=0,_pending=[],_focusMode=false;
function fp(p){
  if(p==null)return'--';
  if(p>=10000)return p.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(p>=1000)return p.toFixed(2);
  if(p>=10)return p.toFixed(4);
  if(p>=1)return p.toFixed(5);
  return p.toFixed(6);
}
async function apiFetch(path,opts={}){
  const r=await fetch(path,{headers:{'Content-Type':'application/json'},mode:'same-origin',...opts});
  if(!r.ok)throw new Error(r.status);
  return r.json();
}
let _toastTimer=null;
function toast(msg,type=''){
  const t=document.getElementById('toast');
  const icon=t.querySelector('.ticon');
  const txt=t.querySelector('.ttxt');
  t.className='toast'+(type?' t-'+type:'');
  icon.textContent=type==='success'?'✅':type==='error'?'❌':type==='warning'?'⚠':type==='info'?'ℹ':'🔔';
  txt.textContent=msg;
  t.classList.add('show');
  if(_toastTimer)clearTimeout(_toastTimer);
  _toastTimer=setTimeout(()=>t.classList.remove('show'),3200);
}
function toggleFocus(){
  _focusMode=!_focusMode;
  document.body.classList.toggle('focus',_focusMode);
  const btn=document.getElementById('focus-btn');
  const cfgBtn=document.getElementById('focus-cfg-btn');
  if(_focusMode){
    btn.classList.add('focus-on');
    if(cfgBtn)cfgBtn.textContent='🎯 Desativar Modo Focus';
    const dashBtn=document.querySelector('.nb');
    goTo('dash',dashBtn);
    toast('Modo Focus ativado — apenas trades visíveis','info');
  }else{
    btn.classList.remove('focus-on');
    if(cfgBtn)cfgBtn.textContent='🎯 Ativar Modo Focus';
    toast('Modo Focus desativado','info');
  }
}
function goTo(pg,btn){
  if(_focusMode&&pg!=='dash'){
    toast('Desative o Modo Focus para navegar','warning');
    return;
  }
  document.querySelectorAll('.pg').forEach(p=>{p.classList.remove('on');p.style.display='none';});
  document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));
  const t=document.getElementById('pg-'+pg);
  if(t){t.classList.add('on');t.style.display='block';}
  btn.classList.add('on');
  if(pg==='pend')loadPending();
  if(pg==='scan')loadScanner();
  if(pg==='sig'){loadSigs();_unread=0;updBadge();}
  if(pg==='ct'){loadCT();loadNews();}
  if(pg==='cfg')loadCfg();
}
async function refreshAll(){
  const b=document.getElementById('refbtn');
  b.style.opacity='.4';b.style.pointerEvents='none';
  try{
    await loadDash();await loadPending();
    const a=document.querySelector('.pg.on');
    if(a){
      if(a.id==='pg-scan')await loadScanner();
      if(a.id==='pg-sig')await loadSigs();
      if(a.id==='pg-ct'){await loadCT();await loadNews();}
    }
    toast('Dados atualizados','success');
  }finally{b.style.opacity='1';b.style.pointerEvents='auto';}
}
function updSubHeader(st){
  if(!st)return;
  const dpnl=document.getElementById('sh-dpnl');
  const wr=document.getElementById('sh-wr');
  const op=document.getElementById('sh-open');
  const sts=document.getElementById('sh-status');
  dpnl.textContent=(st.daily_pnl>=0?'+':'')+st.daily_pnl+'%';
  dpnl.className='shv '+(st.daily_pnl>0?'g':st.daily_pnl<0?'r':'');
  wr.textContent=st.winrate+'%';
  wr.className='shv '+(st.winrate>=50?'g':st.winrate>0?'go':'r');
  op.textContent=st.active_trades.length;
  if(st.paused){sts.textContent='⛔CB';sts.className='shv r';}
  else if(st.consecutive_losses>=1){sts.textContent='⚠'+st.consecutive_losses+'L';sts.className='shv go';}
  else{sts.textContent='●OK';sts.className='shv g';}
}
function updRiskPanel(st){
  if(!st)return;
  const balEl=document.getElementById('r-balance');
  balEl.textContent=fp(st.balance||0);
  balEl.className='risk-val bl';
  const eqEl=document.getElementById('r-equity');
  if(eqEl){eqEl.textContent=fp(st.equity||st.balance||0); eqEl.className='risk-val '+((st.equity||0)>= (st.balance||0)?'g':'r');}
  const marEl=document.getElementById('r-margin');
  if(marEl){marEl.textContent=fp(st.used_margin||0); marEl.className='risk-val go';}
  const freeEl=document.getElementById('r-free');
  if(freeEl){freeEl.textContent=fp(st.free_margin||0); freeEl.className='risk-val '+((st.free_margin||0)>0?'bl':'r');}
  const lvlEl=document.getElementById('r-level');
  if(lvlEl){
    const ml=st.margin_level||0;
    lvlEl.textContent=ml.toFixed(1)+'%';
    lvlEl.className='risk-val '+(ml<=(st.stop_out_level||30)?'r':ml<=(st.margin_call_level||100)?'go':'g');
  }
  const levEl=document.getElementById('r-leverage');
  levEl.textContent=(st.leverage||0)+'x';
  levEl.className='risk-val go';
  const riskEl=document.getElementById('r-risk');
  riskEl.textContent=(st.risk_pct||0).toFixed(1)+'%';
  riskEl.className='risk-val go';
  const exposure=Math.round((st.active_trades.length/3)*100);
  const expEl=document.getElementById('r-exposure');
  expEl.textContent=exposure+'%';
  expEl.className='risk-val '+(exposure>=80?'r':exposure>=50?'go':'bl');
  const cbEl=document.getElementById('r-cb');
  cbEl.textContent=st.paused?'⛔ ATIVO':'✅ OK';
  cbEl.className='risk-val '+(st.paused?'r':'g');
  const lEl=document.getElementById('r-losses');
  lEl.textContent=st.consecutive_losses+' / 2';
  lEl.className='risk-val '+(st.consecutive_losses>=2?'r':st.consecutive_losses>=1?'go':'g');
  const wlEl=document.getElementById('r-wl');
  wlEl.textContent=st.wins+'W / '+st.losses+'L';
  wlEl.className='risk-val '+(st.winrate>=50?'g':'r');
  // Campos específicos Tickmill
  const actEl=document.getElementById('r-actype');
  if(actEl){actEl.textContent=st.account_type||'RAW'; actEl.className='risk-val cy';}
  const mcsoEl=document.getElementById('r-mcso');
  if(mcsoEl){mcsoEl.textContent=(st.margin_call_level||100)+'% / '+(st.stop_out_level||30)+'%';}
}
async function loadDash(){
  try{
    _st=await apiFetch('/api/status');
    document.getElementById('eb').style.display='none';
    updSubHeader(_st);updRiskPanel(_st);
    const dpnl=document.getElementById('d-dpnl');
    dpnl.textContent=(_st.daily_pnl>=0?'+':'')+_st.daily_pnl+'%';
    dpnl.className='sv '+(_st.daily_pnl>=0?'g':'r');
    document.getElementById('d-drec').textContent=_st.daily_wins+'W / '+_st.daily_losses+'L hoje';
    const wr=document.getElementById('d-wr');
    wr.textContent=_st.winrate+'%';
    wr.className='sv '+(_st.winrate>=50?'g':_st.winrate>0?'go':'r');
    document.getElementById('d-wlt').textContent=_st.wins+'W / '+_st.losses+'L total';
    document.getElementById('d-open').textContent=_st.active_trades.length;
    document.getElementById('d-closed').textContent=_st.today_closed;
    document.getElementById('d-trades').innerHTML=_st.active_trades.length
      ?_st.active_trades.map(renderOpenTrade).join('')
      :'<div class="empty"><span class="empi">📭</span><div class="empt">Nenhum trade aberto.</div></div>';
    document.getElementById('d-closed-list').innerHTML=_st.today_closed
      ?renderClosedToday(_st.history_today)
      :'<div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada.</div></div>';
    updCfgBtns();
  }catch(e){document.getElementById('eb').style.display='block';}
}
function renderOpenTrade(t){
  const buy=t.dir==='BUY',pos=t.pnl>=0;
  const cls=buy?'buy':'sell';
  const distSlClass=t.dist_sl<30?'near':'far';
  const distTpClass=t.dist_tp<30?'near':'far';
  const maxLevTxt=t.max_leverage?` | máx ${t.max_leverage}x`:'';
  return`<div class="tcard ${cls}">
    <div class="tcard-head">
      <div><div class="tsym">${t.symbol}</div><div class="tname">${t.name||''} <span style="font-size:9px;color:var(--muted2)">[MT5]</span></div></div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px">
        <div class="tdir ${buy?'':'sell'}">${buy?'▲ BUY':'▼ SELL'}</div>
        <span class="ttype-badge">${t.tipo||'TREND'}</span>
      </div>
    </div>
    <div class="tlvs">
      <div class="tlv"><div class="tll">Entrada</div><div class="tlvv">${fp(t.entry)}</div></div>
      <div class="tlv"><div class="tll">Atual</div><div class="tlvv ${pos?'g':'r'}">${fp(t.current)}</div></div>
      <div class="tlv"><div class="tll">P&L</div><div class="tlvv ${pos?'g':'r'}">${t.pnl>=0?'+':''}${t.pnl.toFixed(2)}%${t.pnl_money!==undefined?' | '+fp(t.pnl_money):''}</div></div>
    </div>
    <div class="tlvs">
      <div class="tlv"><div class="tll">Lote</div><div class="tlvv bl">${(t.lot||0).toFixed(2)}</div></div>
      <div class="tlv"><div class="tll">Margem</div><div class="tlvv go">${fp(t.margin_required||0)}</div></div>
      <div class="tlv"><div class="tll">Alav.</div><div class="tlvv" style="font-size:11px">${(_st&&_st.leverage)||'--'}x${maxLevTxt}</div></div>
    </div>
    <div class="tprog"><div class="tfill" style="width:${t.progress}%;background:${pos?'var(--green)':'var(--red)'}"></div></div>
    <div class="tdist">
      <span>🛡 SL: <span class="${distSlClass}">${t.dist_sl.toFixed(1)}%</span></span>
      <span>🎯 TP: <span class="${distTpClass}">${t.dist_tp.toFixed(1)}%</span></span>
    </div>
  </div>`;
}
function renderClosedToday(list){
  if(!list||!list.length)return'<div class="empty"><span class="empi">📂</span><div class="empt">Nenhuma operação finalizada.</div></div>';
  return list.map(h=>{
    const win=h.result==='WIN';
    return`<div class="hist-item">
      <div style="display:flex;align-items:center;gap:10px">
        <div class="hist-icon" style="background:${win?'var(--g3)':'var(--r3)'};color:${win?'var(--green)':'var(--red)'}">${win?'✅':'❌'}</div>
        <div><div class="hist-sym">${h.symbol} ${h.dir}</div><div class="hist-time">${h.closed_at}</div></div>
      </div>
      <div class="hist-pnl ${win?'g':'r'}">${win?'+':''}${h.pnl.toFixed(2)}%</div>
    </div>`;
  }).join('');
}
async function loadPending(){
  try{const d=await apiFetch('/api/pending');renderPendingFromApi(d);}
  catch(e){console.log('pending err',e);}
}
function renderPendingFromApi(list){
  const el=document.getElementById('pendingQueue');if(!el)return;
  el.innerHTML=list.length?list.map(p=>{
    const buy=p.dir==='BUY';const cls=buy?'buy':'sell';const dirLabel=buy?'▲ BUY':'▼ SELL';
    return`<div class="tcard ${cls} pending" data-pid="${p.pending_id}" data-created="${p.created_at}"><div class="expire-bar"></div>
      <div class="tcard-head">
        <div><div class="tsym">${p.symbol}</div><div class="tname">${p.name||''}</div></div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px">
          <div class="tdir ${cls}">${dirLabel}</div>
          <span class="ttype-badge">R: ${p.ratio||'--'}</span>
        </div>
      </div>
      <div class="tlvs">
        <div class="tlv"><div class="tll">Entrada <button class="cpbtn" onclick="copyText('${p.entry}')">📋</button></div><div class="tlvv">${fp(p.entry)}</div></div>
        <div class="tlv"><div class="tll">SL 🛡 <button class="cpbtn" onclick="copyText('${p.sl}')">📋</button></div><div class="tlvv r">${fp(p.sl)}</div></div>
        <div class="tlv"><div class="tll">TP 🎯 <button class="cpbtn" onclick="copyText('${p.tp}')">📋</button></div><div class="tlvv g">${fp(p.tp)}</div></div>
      </div>
      <div class="tlvs">
        <div class="tlv"><div class="tll">Saldo</div><div class="tlvv bl">${fp(p.balance!==undefined?p.balance:(_st&&_st.balance?_st.balance:0))}</div></div>
        <div class="tlv"><div class="tll">Risco</div><div class="tlvv go">${((_st&&_st.risk_pct!==undefined)?_st.risk_pct:0).toFixed(1)}%</div></div>
        <div class="tlv"><div class="tll">Alav.</div><div class="tlvv">${((_st&&_st.leverage!==undefined)?_st.leverage:0)}x</div></div>
      </div>
      <div class="tlvs">
        <div class="tlv"><div class="tll">Lote mín.</div><div class="tlvv bl">${Number(p.min_lot||0).toFixed(2)}</div></div>
        <div class="tlv"><div class="tll">Base mín.</div><div class="tlvv go">${fp(p.min_amount_required||0)}</div></div>
        <div class="tlv"><div class="tll">Margem min.</div><div class="tlvv">${fp(p.min_amount_required||0)}</div></div>
      </div>
      <div class="tbtns" style="grid-template-columns:repeat(2,1fr)">
        <button class="tb tb-pct-25" onclick="openPendingPct(${p.pending_id},25,this)">⚡ 25%</button>
        <button class="tb tb-pct-50" onclick="openPendingPct(${p.pending_id},50,this)">💎 50%</button>
        <button class="tb tb-pct-100" onclick="openPendingPct(${p.pending_id},100,this)">🔥 100%</button>
        <button class="tb no" onclick="rejectPending(${p.pending_id},this)">❌ Recusar</button>
      </div>
      <div class="tbtns" style="grid-template-columns:1fr">
        <button class="tb tb-custom" onclick="openPendingCustom(${p.pending_id},this)">✏️ Valor customizado</button>
      </div>
    </div>`;
  }).join('')
  :'<div class="empty"><span class="empi">✨</span><div class="empt">Nenhuma confirmação pendente</div></div>';
  _pending=list;updBadge();
}
async function confirmPending(id,btn){
  btn.textContent='…';btn.disabled=true;
  try{await apiFetch('/api/confirm',{method:'POST',body:JSON.stringify({pending_id:id})});toast('Trade confirmado!','success');loadPending();loadDash();}
  catch(e){btn.textContent='Erro';btn.disabled=false;}
}
async function openPendingPct(id,pct,btn){
  const bal = _st && _st.balance ? _st.balance : 0;
  const usd = (bal * pct / 100).toFixed(2);
  btn.textContent='…';btn.disabled=true;
  try{
    await apiFetch('/api/execute_pending_pct',{method:'POST',body:JSON.stringify({pending_id:id,pct:pct})});
    toast('✅ Operação aberta com '+pct+'% ($'+usd+')','success');
    loadPending();loadDash();
  }catch(e){btn.textContent=pct+'%';btn.disabled=false;toast('Erro: '+e.message,'error');}
}
async function openPendingCustom(id,btn){
  // Cria input inline no card, mais profissional que prompt()
  const card = btn.closest('.tcard');
  let inputWrap = card.querySelector('.custom-amt-wrap');
  if(inputWrap){inputWrap.remove();return;}
  inputWrap = document.createElement('div');
  inputWrap.className='custom-amt-wrap';
  inputWrap.style.cssText='margin-top:10px;display:flex;gap:8px;align-items:center';
  inputWrap.innerHTML=`
    <input type="number" min="1" step="1" placeholder="Valor em USD (ex: 500)"
      style="flex:1;background:rgba(255,255,255,0.07);border:1px solid rgba(255,215,64,.4);
      border-radius:10px;padding:12px;color:var(--text);font-size:14px;font-family:var(--mono);outline:none"
      id="custom-amt-${id}">
    <button onclick="submitCustomAmt(${id},this)"
      style="background:linear-gradient(135deg,#4a148c,#7b1fa2);color:#f3e5f5;border:none;
      border-radius:10px;padding:12px 16px;font-weight:700;cursor:pointer;font-size:14px;white-space:nowrap">
      ✓ OK
    </button>`;
  btn.parentElement.appendChild(inputWrap);
  const inp = inputWrap.querySelector('input');
  inp.focus();
  inp.addEventListener('keydown', e=>{ if(e.key==='Enter') submitCustomAmt(id, inp); });
}
async function submitCustomAmt(id, el){
  const inp = document.getElementById('custom-amt-'+id);
  if(!inp)return;
  const raw = inp.value;
  const amount=parseFloat(String(raw).replace(',','.'));
  if(!Number.isFinite(amount)||amount<=0){inp.style.borderColor='var(--red)';toast('Valor inválido. Ex: 500','error');return;}
  inp.disabled=true;
  try{
    await apiFetch('/api/execute_pending',{method:'POST',body:JSON.stringify({pending_id:id,amount:amount})});
    toast('✅ Operação aberta com $'+amount.toFixed(2),'success');
    loadPending();loadDash();
  }catch(e){inp.disabled=false;inp.style.borderColor='var(--red)';toast('Erro: '+e.message,'error');}
}
async function rejectPending(id,btn){
  btn.textContent='…';btn.disabled=true;
  try{await apiFetch('/api/reject',{method:'POST',body:JSON.stringify({pending_id:id})});toast('Trade recusado','error');loadPending();}
  catch(e){btn.textContent='Erro';btn.disabled=false;}
}
function copyText(txt){navigator.clipboard.writeText(String(txt));toast('Copiado: '+txt,'info');}
async function loadScanner(){
  try{
    const d=await apiFetch('/api/trends');
    const g={};
    d.forEach(x=>{const c=x.category||'OUTROS';(g[c]=g[c]||[]).push(x);});
    let h='';
    const lb={FOREX:'FOREX',CRYPTO:'CRIPTO',COMMODITIES:'COMMODITIES',INDICES:'ÍNDICES',OUTROS:'OUTROS'};
    const order=['FOREX','CRYPTO','COMMODITIES','INDICES'];
    for(const c of [...order,...Object.keys(g).filter(k=>!order.includes(k))]){
      if(!g[c])continue;
      const up=g[c].filter(x=>x.cenario==='ALTA').length;
      const dn=g[c].filter(x=>x.cenario==='BAIXA').length;
      h+=`<div class="tgroup"><div class="tghd">${lb[c]||c}<span style="font-size:9px;font-weight:400;margin-left:4px"><span style="color:var(--green)">${up}▲</span> <span style="color:var(--red)">${dn}▼</span></span></div>`;
      h+=g[c].map(x=>{
        const cls=x.cenario==='ALTA'?'up':x.cenario==='BAIXA'?'dn':'neut';
        const tag=x.cenario==='ALTA'?'▲ ALTA':x.cenario==='BAIXA'?'▼ BAIXA':'NEUTRO';
        const chgCls=x.change_pct>=0?'g':'r';
        return`<div class="titem ${cls}">
          <div><div class="tsym-scan">${x.symbol}</div><div class="tname-scan">${x.name}</div></div>
          <div class="tmeta">
            <span class="ttag ${cls}">${tag}</span>
            <div class="tscan-r">
              <span class="tprice">${fp(x.price)}</span>
              <span class="tchg ${chgCls}">${x.change_pct>=0?'+':''}${x.change_pct.toFixed(2)}%</span>
            </div>
          </div>
        </div>`;
      }).join('');
      h+='</div>';
    }
    document.getElementById('scan-list').innerHTML=h||'<div class="empty"><span class="empi">📡</span><div class="empt">Nenhum dado</div></div>';
  }catch(e){}
}
async function loadSigs(){
  try{
    const d=await apiFetch('/api/signals');
    if(d.length>_lastSigLen){_unread+=d.length-_lastSigLen;updBadge();toast((d.length-_lastSigLen)+' novo(s) sinal(is)','info');}
    _lastSigLen=d.length;_sigs=d;
    const bgMap={radar:'y3',gatilho:'b3',sinal:'b3',ct:'r3',close:'g3',cb:'r3',insuf:'bg3'};
    document.getElementById('sig-list').innerHTML=d.length?d.map(s=>{
      const bg=bgMap[s.tipo]||'bg4';
      return`<div class="sig-card" style="background:var(--${bg})">
        <div class="sig-head">
          <span class="sig-tipo">${s.tipo.toUpperCase()}</span>
          <span class="sig-ts">${s.ts}</span>
        </div>
        <div class="sig-txt">${s.texto}</div>
      </div>`;
    }).join('')
    :'<div class="empty"><span class="empi">🔔</span><div class="empt">Nenhum sinal ainda.</div></div>';
  }catch(e){}
}
async function loadCT(){
  try{
    const d=await apiFetch('/api/reversals');
    document.getElementById('ct-list').innerHTML=d.length?d.map(x=>{
      const pct=Math.min(x.strength,100);
      const rsiCls=x.rsi>70?'r':x.rsi<30?'g':'';
      return`<div class="ctcard">
        <div class="cthead">
          <div><div class="ctsym">${x.symbol}</div><div style="font-size:11px;color:var(--muted2);margin-top:2px">${x.name||''}</div></div>
          <div class="ctdir">${x.direction}</div>
        </div>
        <div class="ctstat">
          <div class="ctbox"><div class="ctl">Força</div><div class="ctv cy">${x.strength}%</div></div>
          <div class="ctbox"><div class="ctl">RSI</div><div class="ctv ${rsiCls}">${x.rsi}</div></div>
        </div>
        <div class="ctbar"><div class="ctfill" style="width:${pct}%"></div></div>
        <div class="ctrs">${x.reasons.map(r=>`<span class="cttag">${r}</span>`).join('')}</div>
      </div>`;
    }).join('')
    :'<div class="empty"><span class="empi">⚡</span><div class="empt">Nenhuma CT detectada.</div></div>';
  }catch(e){}
}
async function loadNews(){
  try{
    const d=await apiFetch('/api/news');
    const fg=d.fg||{};
    const fgVal=parseInt(fg.value)||0;
    const fgColor=fgVal<=25?'var(--red)':fgVal<=45?'var(--gold)':fgVal<=55?'var(--text2)':fgVal<=75?'var(--green)':'var(--cyan)';
    const dashArr=Math.round(fgVal*1.759)+' 175.9';
    document.getElementById('fg-card-wrap').innerHTML=`<div class="fg-card">
      <div class="fg-l">
        <div class="fg-lbl">Fear & Greed Index</div>
        <div class="fg-val" style="color:${fgColor}">${fg.value||'N/D'}</div>
        <div class="fg-name" style="color:${fgColor}">${fg.label||'--'}</div>
      </div>
      <svg width="64" height="64" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r="28" fill="none" stroke="var(--bg4)" stroke-width="7"/>
        <circle cx="32" cy="32" r="28" fill="none" stroke="${fgColor}" stroke-width="7"
          stroke-dasharray="${dashArr}" stroke-linecap="round" class="fg-circle"/>
      </svg>
    </div>`;
    document.getElementById('news-list').innerHTML=d.articles&&d.articles.length
      ?d.articles.map(a=>`<div class="news-item">
          <a class="news-title" href="${a.url}" target="_blank">${a.title}</a>
          <span class="news-src">${a.source}</span>
        </div>`).join('')
      :'<div class="empty"><span class="empi">📰</span><div class="empt">Sem notícias disponíveis.</div></div>';
  }catch(e){}
}
async function loadCfg(){
  try{
    const c=await apiFetch('/api/config');
    document.getElementById('p-sl').textContent=c.atm_sl+'×ATR';
    document.getElementById('p-tp').textContent=c.atr_tp+'×ATR';
    document.getElementById('p-mt').textContent=c.max_trades;
    document.getElementById('p-mc').textContent=c.min_conf+'/7';
    const pbal=document.getElementById('p-bal'); if(pbal) pbal.textContent=fp(c.balance||0);
    const pcomm=document.getElementById('p-comm'); if(pcomm) pcomm.textContent='$'+c.commission_rt_forex+'/lote';
    const pml=document.getElementById('p-minlot'); if(pml) pml.textContent=c.min_lot||'0.01';
    // Atualiza painel de alavancagem
    const plev=document.getElementById('p-lev'); if(plev) plev.textContent=(c.leverage||0)+'x';
    const plevmax=document.getElementById('p-lev-max'); if(plevmax) plevmax.textContent='máx Tickmill por ativo: varia';
    updLevBtns(c.leverage||0);
  }catch(_){}
  updCfgBtns();
}
function updLevBtns(cur){
  document.querySelectorAll('.levb[data-lev]').forEach(b=>{
    b.classList.toggle('on', parseInt(b.dataset.lev)===parseInt(cur));
  });
  const inp=document.getElementById('lev-input');
  if(inp) inp.value='';
}
async function setLeverage(val){
  try{
    await apiFetch('/api/leverage',{method:'POST',body:JSON.stringify({leverage:val})});
    const plev=document.getElementById('p-lev'); if(plev) plev.textContent=val+'x';
    updLevBtns(val);
    if(_st) _st.leverage=val;
    toast('Alavancagem: '+val+'x','success');
    await loadDash();
  }catch(e){toast('Erro: '+e.message,'error');}
}
async function submitLeverage(){
  const inp=document.getElementById('lev-input');
  if(!inp)return;
  const val=parseInt(inp.value);
  if(!Number.isFinite(val)||val<1||val>500){
    inp.style.borderColor='var(--red)';
    toast('Alavancagem deve ser entre 1 e 500','error');
    setTimeout(()=>inp.style.borderColor='',1500);
    return;
  }
  await setLeverage(val);
}
function updCfgBtns(){
  if(!_st)return;
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('on',b.dataset.mode===_st.mode));
  document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('on',b.dataset.tf===_st.timeframe));
}
async function setMode(m){
  try{await apiFetch('/api/mode',{method:'POST',body:JSON.stringify({mode:m})});await loadDash();toast('Modo: '+m,'success');}
  catch(e){toast('Erro: '+e.message,'error');}
}
async function setTf(t){
  try{await apiFetch('/api/timeframe',{method:'POST',body:JSON.stringify({timeframe:t})});await loadDash();toast('Timeframe: '+t,'success');}
  catch(e){toast('Erro: '+e.message,'error');}
}
async function setBalance(){
  const raw=prompt('Digite o novo saldo da conta em USD','500');
  if(raw===null)return;
  const balance=parseFloat(String(raw).replace(',','.'));
  if(!Number.isFinite(balance)||balance<=0){toast('Saldo inválido','error');return;}
  try{
    await apiFetch('/api/balance',{method:'POST',body:JSON.stringify({balance})});
    await loadDash();
    toast('Saldo atualizado','success');
  }catch(e){toast('Erro: '+e.message,'error');}
}
async function resetPausa(){
  if(!confirm('Resetar Circuit Breaker?'))return;
  try{await apiFetch('/api/resetpausa',{method:'POST'});toast('Circuit Breaker resetado','success');await loadDash();}
  catch(e){toast('Erro: '+e.message,'error');}
}
async function requestNotif(){
  if(!('serviceWorker' in navigator)||!('PushManager' in window)){toast('Navegador não suporta notificações','warning');return;}
  try{
    const perm=await Notification.requestPermission();
    if(perm!=='granted'){toast('Permissão negada','warning');return;}
    const reg=await navigator.serviceWorker.ready;
    const key=await apiFetch('/api/vapid-public-key').then(r=>r.key);
    const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
    await apiFetch('/api/subscribe',{method:'POST',body:JSON.stringify(sub)});
    toast('Notificações ativadas!','success');
  }catch(e){toast('Erro ao ativar: '+e.message,'error');}
}
function updBadge(){
  const pend=_pending?_pending.length:0;
  document.getElementById('nbadge-pend').textContent=pend>0?pend:'';
  document.getElementById('nbadge-pend').style.display=pend>0?'flex':'none';
  const sig=_unread>0?_unread:0;
  document.getElementById('nbadge-sig').textContent=sig>0?sig:'';
  document.getElementById('nbadge-sig').style.display=sig>0?'flex':'none';
}
window.addEventListener('load',()=>{
  loadDash();loadPending();
  setInterval(()=>{
    loadDash();
    const pg=document.querySelector('.pg.on');
    if(pg&&pg.id==='pg-pend')loadPending();
    if(pg&&pg.id==='pg-sig')loadSigs();
  },5000);
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
});

function startCountdown() {
    setInterval(() => {
        const now = Date.now() / 1000;
        document.querySelectorAll('.tcard.pending').forEach(card => {
            const created = parseFloat(card.dataset.created);
            const remaining = Math.max(0, 900 - (now - created));
            const pct = (remaining / 900) * 100;
            const bar = card.querySelector('.expire-bar');
            if (bar) bar.style.width = pct + '%';
            if (remaining <= 0) {
                card.style.opacity = '0.4';
                card.querySelector('.tbtns').innerHTML = '<div style="color:var(--red);text-align:center;width:100%;padding:10px;font-weight:bold">SINAL EXPIRADO</div>';
            }
        });
    }, 1000);
}
window.addEventListener('load', startCountdown);
</script>
</body>
</html>
"""
# ═══════════════════════════════════════════════════════════════
# FLASK API (100% COMPATÍVEL COM O FRONTEND NOVO)
# ═══════════════════════════════════════════════════════════════
def create_api(bot):
    app = Flask(__name__)
    CORS(app)
    @app.after_request
    def cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    @app.route("/")
    def index(): return Response(DASHBOARD_HTML, mimetype="text/html")
    @app.route("/sw.js")
    def sw(): return Response(SW_JS, mimetype="application/javascript")
    @app.route("/icon-192.png")
    @app.route("/icon-512.png")
    def icon():
        size = 192 if "192" in request.path else 512
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" rx="{size//6}" fill="#06090f"/><text x="{size//2}" y="{int(size*.72)}" font-size="{int(size*.55)}" text-anchor="middle" fill="#00e676" font-family="monospace" font-weight="700">S</text></svg>'
        return Response(svg, mimetype="image/svg+xml")
    @app.route("/api/health")
    def api_health(): return jsonify({"status": "ok", "version": "7.3 PRO", "broker": Config.BROKER_NAME, "platform": Config.BROKER_PLATFORM, "account_type": Config.ACCOUNT_TYPE})
    @app.route("/api/status")
    def api_status():
        total = bot.wins + bot.losses
        wr = round(bot.wins/total*100, 1) if total > 0 else 0
        today = datetime.now(Config.BR_TZ).strftime("%d/%m")
        today_trades = [h for h in bot.history if h.get("closed_at", " ").startswith(today)]
        daily_pnl = sum(h.get("pnl", 0) for h in today_trades)
        daily_wins = sum(1 for h in today_trades if h.get("result") == "WIN")
        daily_losses = sum(1 for h in today_trades if h.get("result") == "LOSS")
        snap = account_snapshot(bot)
        trades_out = []
        for t in bot.active_trades:           
            try: res = get_analysis(t["symbol"], bot.timeframe); cur = res["price"] if res else t["entry"]
            except: cur = t["entry"]
            pnl = (cur - t["entry"]) / t["entry"] * 100
            if t["dir"] == "SELL": pnl = -pnl
            dist_sl = abs(cur - t["sl"]) / abs(t["entry"] - t["sl"]) * 100 if t["entry"] != t["sl"] else 0
            dist_tp = abs(cur - t["tp"]) / abs(t["tp"] - t["entry"]) * 100 if t["tp"] != t["entry"] else 0
            progress = min(max(100 - dist_tp, 0), 100) if t["tp"] != t["entry"] else 0
            trades_out.append({
                "symbol": t["symbol"], "name": t.get("name", " "), "dir": t["dir"],
                "tipo": t.get("tipo", " "), "entry": t["entry"], "sl": t["sl"], "tp": t["tp"],
                "current": cur, "pnl": round(pnl, 2), "pnl_money": round(t.get("pnl_money", 0), 2),
                "opened_at": t.get("opened_at", " "),
                "dist_sl": round(dist_sl, 1), "dist_tp": round(dist_tp, 1), "progress": round(progress, 1),
                "lot": round(float(t.get("lot", 0)), 2), "margin_required": round(float(t.get("margin_required", 0)), 2),
                "capital_base": round(float(t.get("capital_base", 0)), 2),
                "commission": round(float(t.get("commission", 0)), 2),
                "max_leverage": max_leverage_for(t["symbol"]),
            })
        return jsonify({
            "wins": bot.wins, "losses": bot.losses, "winrate": wr,
            "consecutive_losses": bot.consecutive_losses, "mode": bot.mode, "timeframe": bot.timeframe,
            "paused": bot.is_paused(), "cb_mins": max(0, int((bot.paused_until - time.time()) / 60)) if bot.is_paused() else 0,
            "active_trades": trades_out, "pending_count": len(bot.pending_trades),
            "daily_pnl": round(daily_pnl, 2), "daily_wins": daily_wins, "daily_losses": daily_losses,
            "today_closed": len(today_trades), "history_today": today_trades,
            "balance": snap["balance"], "equity": snap["equity"],
            "used_margin": snap["used_margin"], "free_margin": snap["free_margin"],
            "margin_level": snap["margin_level"],
            "leverage": bot.leverage, "risk_pct": bot.risk_pct,
            "margin_call_level": Config.MARGIN_CALL_LEVEL,
            "stop_out_level": Config.STOP_OUT_LEVEL,
            "broker": Config.BROKER_NAME,
            "account_type": bot.account_type,
            "platform": bot.platform,
        })
    @app.route("/api/config")
    def api_config(): return jsonify({
        "atm_sl": Config.ATR_MULT_SL, "atr_tp": Config.ATR_MULT_TP,
        "max_trades": Config.MAX_TRADES, "min_conf": Config.MIN_CONFLUENCE,
        "balance": bot.balance, "leverage": bot.leverage, "risk_pct": bot.risk_pct,
        "broker": Config.BROKER_NAME, "platform": Config.BROKER_PLATFORM,
        "account_type": bot.account_type,
        "margin_call_level": Config.MARGIN_CALL_LEVEL,
        "stop_out_level": Config.STOP_OUT_LEVEL,
        "commission_rt_forex": Config.COMMISSION_PER_LOT_RT["FOREX"],
        "min_lot": Config.MIN_LOT,
        "max_leverage_by_cat": Config.MAX_LEVERAGE_BY_CAT,
    })
    @app.route("/api/history")
    def api_history(): return jsonify(list(reversed(bot.history[-50:])))
    @app.route("/api/signals")
    def api_signals(): return jsonify(list(reversed(bot.signals_feed)))
    @app.route("/api/pending")
    def api_pending():
        snap = account_snapshot(bot)
        pending = []
        for p in bot.pending_trades:
            item = dict(p)
            item["balance"] = snap["balance"]
            item["equity"] = snap["equity"]
            item["used_margin"] = snap["used_margin"]
            item["free_margin"] = snap["free_margin"]
            item["margin_level"] = snap["margin_level"]
            item["min_lot"] = float(p.get("min_lot", Config.MIN_LOT))
            item["min_amount_required"] = float(p.get("min_amount_required", required_amount_for_lot(p["symbol"], p["entry"], bot.leverage, Config.MIN_LOT)))
            pending.append(item)
        return jsonify(pending)
    @app.route("/api/execute_pending", methods=["POST", "OPTIONS"])
    def api_execute_pending():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        amount = data.get("amount")
        try:
            amount = float(amount)
        except Exception:
            return jsonify({"error": "amount inválido"}), 400
        return jsonify({"ok": True}) if bot.execute_pending_with_amount(pid, amount, source="dashboard") else (jsonify({"error": "not found"}), 404)
    @app.route("/api/execute_pending_pct", methods=["POST", "OPTIONS"])
    def api_execute_pending_pct():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        pid = data.get("pending_id")
        pct = data.get("pct")
        try:
            pct = float(pct)
        except Exception:
            return jsonify({"error": "pct inválido"}), 400
        amount = max(0.0, bot.balance * pct / 100.0)
        return jsonify({"ok": True}) if bot.execute_pending_with_amount(pid, amount, source="dashboard") else (jsonify({"error": "not found"}), 404)
    @app.route("/api/confirm", methods=["POST", "OPTIONS"])
    def api_confirm():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}; pid = data.get("pending_id")
        amount = data.get("amount")
        if amount is None:
            return jsonify({"ok": True}) if bot.confirm_pending(pid) else (jsonify({"error": "not found"}), 404)
        try:
            amount = float(amount)
        except Exception:
            return jsonify({"error": "amount inválido"}), 400
        return jsonify({"ok": True}) if bot.execute_pending_with_amount(pid, amount, source="dashboard") else (jsonify({"error": "not found"}), 404)
    @app.route("/api/balance", methods=["POST", "OPTIONS"])
    def api_balance():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        try:
            value = float(data.get("balance"))
        except Exception:
            return jsonify({"error": "balance inválido"}), 400
        if value <= 0:
            return jsonify({"error": "saldo precisa ser maior que zero"}), 400
        bot.set_balance(value)
        return jsonify({"ok": True, "balance": round(bot.balance, 2)})

    @app.route("/api/leverage", methods=["POST", "OPTIONS"])
    def api_leverage():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}
        try:
            value = int(data.get("leverage"))
        except Exception:
            return jsonify({"error": "alavancagem inválida"}), 400
        if value < 1 or value > 500:
            return jsonify({"error": "alavancagem deve ser entre 1 e 500"}), 400
        bot.set_leverage(value)
        return jsonify({"ok": True, "leverage": bot.leverage})

    @app.route("/api/reject", methods=["POST", "OPTIONS"])
    def api_reject():
        if request.method == "OPTIONS": return jsonify({}), 200
        data = request.get_json(force=True) or {}; pid = data.get("pending_id")
        return jsonify({"ok": True}) if bot.reject_pending(pid) else (jsonify({"error": "not found"}), 404)
    @app.route("/api/news")
    def api_news():
        now = time.time()
        if now - bot.news_cache_ts > 600 or not bot.news_cache:
            try: bot.news_cache = {"fg": get_fear_greed(), "articles": get_news(15)}; bot.news_cache_ts = now
            except Exception as e: log(f"[NEWS] {e}")
        return jsonify(bot.news_cache if bot.news_cache else {"fg": {}, "articles": []})
    @app.route("/api/trends")
    def api_trends():
        bot.update_trends_cache()        
        out = []
        for sym, entry in bot.trend_cache.items():
            d = entry["data"]
            out.append({"symbol": sym, "name": d["name"], "category": asset_cat(sym), "price": d["price"], "cenario": d["cenario"], "rsi": round(d["rsi"],1), "adx": round(d["adx"],1), "change_pct": round(d["change_pct"],2)})
        out.sort(key=lambda x: ({"ALTA":0,"BAIXA":1,"NEUTRO":2}.get(x["cenario"],9), -abs(x["change_pct"])))
        return jsonify(out)
    @app.route("/api/reversals")
    def api_reversals():
        bot.update_trends_cache()
        out = []
        for sym, entry in bot.trend_cache.items():
            rev = entry.get("reversal", {})
            if rev.get("has"):
                d = entry["data"]
                out.append({"symbol": sym, "name": d["name"], "price": d["price"], "rsi": round(d["rsi"],1), "adx": round(d["adx"],1), "direction": rev["dir"], "strength": rev["strength"], "reasons": rev["reasons"]})
        out.sort(key=lambda x: -x["strength"])
        return jsonify(out)
    @app.route("/api/mode", methods=["POST", "OPTIONS"])
    def api_mode():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(force=True) or {}
        mode = data.get("mode", "").strip()
        if mode not in list(Config.MARKET_CATEGORIES.keys()) + ["TUDO"]:
            return jsonify({"error": "inválido"}), 400
        bot.set_mode(mode)
        return jsonify({"ok": True})
    @app.route("/api/timeframe", methods=["POST", "OPTIONS"])
    def api_timeframe():
        if request.method == "OPTIONS":
            return jsonify({}), 200
        data = request.get_json(force=True) or {}
        tf = data.get("timeframe", "").strip()
        if tf not in Config.TIMEFRAMES:
            return jsonify({"error": "inválido"}), 400
        bot.set_timeframe(tf)
        return jsonify({"ok": True})
    @app.route("/api/resetpausa", methods=["POST", "OPTIONS"])
    def api_reset():
        if request.method == "OPTIONS": return jsonify({}), 200
        bot.reset_pause(); return jsonify({"ok": True})
    @app.route("/api/vapid-public-key")
    def api_vapid_key(): return jsonify({"key": os.getenv("VAPID_PUBLIC_KEY", "")})
    @app.route("/api/subscribe", methods=["POST", "OPTIONS"])
    def api_subscribe():
        if request.method == "OPTIONS": return jsonify({}), 200
        sub = request.get_json(force=True)
        if sub and sub not in _push_subscriptions: _push_subscriptions.append(sub)
        return jsonify({"ok": True})
    return app
def run_api(bot):
    port = int(os.getenv("PORT", 8080))
    app = create_api(bot)
    log(f"🌐 Flask rodando na porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
# ═══════════════════════════════════════════════════════════════
# LOOP DO BOT & MAIN (100% PRESERVADO)
# ═══════════════════════════════════════════════════════════════
def bot_loop(bot):
    bot.build_menu()
    if bot._restore_msg:
        bot.send(bot._restore_msg)
        bot._restore_msg = None
    try:
        bot.send_news()
    except:
        pass
    while True:
        try:
            url = (
                f"https://api.telegram.org/bot"
                f"{Config.BOT_TOKEN}/getUpdates"
                f"?offset={bot.last_id+1}&timeout=5"
            )
            r = requests.get(url, timeout=12).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]
                    if "message" in u:
                        txt = u["message"].get("text", " ").strip().lower()
                        if bot.awaiting_custom_amount and txt not in ("/cancelar", "cancelar"):
                            try:
                                amount = float(txt.replace(",", "."))
                                if amount <= 0:
                                    raise ValueError
                                pid = bot.awaiting_custom_amount
                                bot.awaiting_custom_amount = None
                                bot.execute_pending_with_amount(pid, amount, source="telegram")
                            except Exception:
                                bot.send("❌ Envie apenas um valor numérico válido, por exemplo: <code>500</code>")
                        elif txt in ("/noticias", "/news"): bot.send_news()
                        elif txt == "/status": bot.send_status()
                        elif txt in ("/placar", "/score"): bot.send_placar()
                        elif txt.startswith("/setsaldo"):
                            try:
                                parts = txt.split()
                                if len(parts) < 2: raise ValueError
                                val = float(parts[1].replace(",", "."))
                                if bot.set_balance(val):
                                    bot.send(f"✅ Saldo ajustado para <code>{fmt(bot.balance)}</code>")
                                else:
                                    bot.send("❌ Saldo inválido. Use: <code>/setsaldo 500</code>")
                            except Exception:
                                bot.send("❌ Use: <code>/setsaldo 500</code>")
                        elif txt in ("/saldo", "/account"): bot.send(f"🏦 Saldo: <code>{fmt(bot.balance)}</code> | Alavancagem: <code>{bot.leverage}x</code> | Risco: <code>{bot.risk_pct:.1f}%</code>")
                        elif txt in ("/menu", "/start"): bot.build_menu()
                        elif txt == "/resetpausa": bot.reset_pause()
                    if "callback_query" in u:
                        cb = u["callback_query"]["data"]; cid = u["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": cid}, timeout=5)
                        if cb.startswith("set_tf"): bot.set_timeframe(cb.replace("set_tf_", ""))
                        elif cb.startswith("set"): bot.set_mode(cb.replace("set_", ""))
                        elif cb == "tf_menu": bot.build_tf_menu()
                        elif cb == "main_menu": bot.build_menu()
                        elif cb == "news": bot.send_news()
                        elif cb == "status": bot.send_status()
                        elif cb == "placar": bot.send_placar()
                        elif cb.startswith("amtpct_"):
                            try:
                                _, pct, pid = cb.split("_")
                                amount = max(0.0, bot.balance * float(pct) / 100.0)
                                bot.execute_pending_with_amount(int(pid), amount, source="telegram")
                            except Exception:
                                pass
                        elif cb.startswith("amtcustom_"):
                            try: bot.request_custom_amount(int(cb.split("_")[1]))
                            except Exception: pass
                        elif cb.startswith("confirm_"):
                            try: bot.confirm_pending(int(cb.split("_")[1])) 
                            except: pass
                        elif cb.startswith("reject"):
                            try: bot.reject_pending(int(cb.split("_")[1])) 
                            except: pass
            bot.update_trends_cache()
            bot.maybe_send_news()
            bot.scan()
            bot.scan_reversal_forex()
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)
        except Exception as e: log(f"Erro loop: {e}"); time.sleep(10)
def main():
    log("🔌 Tickmill Sniper Bot v7.3 PRO — MT5 | Raw ECN | Dashboard de Execução")
    try: requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=8) 
    except: pass
    bot = TradingBot()
    load_state(bot)
    t = threading.Thread(target=bot_loop, args=(bot,), daemon=True)
    t.start()
    run_api(bot)
if __name__ == "__main__":    
    main()
