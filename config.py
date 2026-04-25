# config.py
import os
from datetime import timedelta, timezone

class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN",   "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")
    BR_TZ      = timezone(timedelta(hours=-3))

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

    SL_TP_BASE_MULTIPLIER = 250.0
    SL_MAX_PCT = 3.0
    SL_MIN_PCT = 0.2
    TP_SL_RATIO = 2.5
    DYNAMIC_RR_ENABLED = True
    DYNAMIC_RR_TIERS = [
        (3, 3.0, "⚡ Forte"),
        (5, 3.5, "🔥 Muito Forte"),
        (7, 4.5, "💎 Perfeito"),
    ]
    ATR_MULT_SL = 1.5; ATR_MULT_TP = 3.75; ATR_MULT_TRAIL = 1.2
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
    COMMISSION_PER_LOT_SIDE = {
        "FOREX":       3.0,
        "COMMODITIES": 3.0,
        "INDICES":     0.0,
        "CRYPTO":      0.0,
    }
    MAX_LEVERAGE_BY_CAT = {
        "FOREX":       1000,
        "COMMODITIES": 500,
        "INDICES":     100,
        "CRYPTO":      200,
    }
    MAX_LEVERAGE_BY_SYM = {
        "XAUUSD": 1000, "XAGUSD": 125,
        "XTIUSD": 100,  "BRENT":  100,   "NATGAS": 100, "COPPER": 100,
        "US500":  100,  "USTEC":  100,   "US30":   100,
        "DE40":   100,  "UK100":  100,   "JP225":  100, "AUS200": 100, "STOXX50": 100,
    }
    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "500.0"))
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    RISK_PERCENT_PER_TRADE = float(os.getenv("RISK_PERCENT_PER_TRADE", "2.0"))
    MARGIN_CALL_LEVEL = 100.0
    STOP_OUT_LEVEL    = 30.0
    MIN_LOT  = 0.01
    LOT_STEP = 0.01
    CONTRACT_SIZES = {
        "FOREX":       100000,
        "CRYPTO":      1,
        "COMMODITIES": 100,
        "INDICES":     1,
    }
    CONTRACT_SIZES_SPECIFIC = {
        "XAUUSD": 100, "XAGUSD": 5000, "XTIUSD": 1000, "BRENT":  1000,
        "NATGAS": 1000, "COPPER": 1000,
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
    ATR_TRAILING_MULT = 2.0
    NEWS_FILTER_IMPACT = ["HIGH"]
    CORRELATION_LIMIT = 0.7
    # ── Filtro de Sessão (UTC) ─────────────────────────────────
    SESSION_FILTER_ENABLED = True
    # Horários de início/fim das sessões (UTC)
    SESSIONS = {
        "Tokyo":    (0, 9),
        "London":   (8, 17),
        "NewYork":  (13, 22),
    }
    MIN_SESSIONS_OVERLAP = 2   # mínimo de sessões abertas simultâneas

    # ── Filtro de Notícias ─────────────────────────────────────
    NEWS_FILTER_ENABLED = True
    NEWS_BLOCK_MINUTES = 15        # minutos antes/depois do evento
    FOREX_FACTORY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
