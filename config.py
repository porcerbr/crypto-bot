import os

class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN", "7952260034:AAFz3nzC0BJ7Fp7YKwDBIv_HiBX5Sg04TLg")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")

    MODE = "FXGOLD"
    TIMEFRAME = "1h"

    FXGOLD_ASSETS = {
        "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
        "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
        "GBPJPY": "GBP/JPY", "XAUUSD": "Ouro"
    }

    # ── ALAVANCAGEM FIXA ─────────────────────────────────
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    USE_FIXED_LEVERAGE = True      # True = sempre usa DEFAULT_LEVERAGE
                                   # False = usa dinâmica da Tickmill

    # ── SMC & Multi-Timeframe ────────────────────────────
    MTF_CONFIRM_TIMEFRAME = "4h"
    MTF_MIN_CONFLUENCE = 5
    FVG_LOOKBACK = 20
    OB_LOOKBACK = 15
    LIQUIDITY_SWING_LOOKBACK = 10

    # ── R:R Dinâmico baseado em Score SMC ────────────────
    TP_SL_RATIO_BASE = 2.5
    TP_SL_RATIO_STEP = 0.5
    MAX_TP_SL_RATIO = 4.5
    USE_OB_FOR_SL = True
    USE_LIQUIDITY_FOR_TP = True
    USE_FVG_FOR_TP = True

    # ── Turtle Position Sizing ───────────────────────────
    ATR_RISK_PCT = 1.0
    ATR_MULT_FOR_RISK = 2.0

    # Fallback porcentagem
    SL_TP_BASE_MULTIPLIER = 400.0
    SL_MAX_PCT = 4.0
    SL_MIN_PCT = 0.5
    TP_SL_RATIO = 2.5

    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 2.5

    MIN_CONFLUENCE = 6

    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "150"))
    RISK_PERCENT_PER_TRADE = 2.0

    # ── Correlação (regra 3-5-7) ─────────────────────────
    CORRELATION_GROUPS = {
        "USD_LONG":  ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "XAUUSD"],
        "USD_SHORT": ["USDJPY", "USDCAD", "USDCHF"],
        "EUROPE":    ["EURUSD", "EURGBP", "EURJPY"],
        "STERLING":  ["GBPUSD", "EURGBP", "GBPJPY"],
        "YEN":       ["USDJPY", "EURJPY", "GBPJPY"],
    }
    MAX_CORRELATED_RISK_PCT = 7.0

    MAX_TRADES = 3
    ASSET_COOLDOWN = 3600
    SCAN_INTERVAL = 60
    PAUSE_DURATION = 3600
    MAX_CONSECUTIVE_LOSSES = 3

    MARGIN_CALL_PCT = 100.0
    STOP_OUT_PCT = 30.0

    TIMEFRAMES = {
        "1h": ("60d", "1h"),
        "4h": ("120d", "1h"),
    }

    COMMISSION_PER_LOT = {
        "FOREX": 6.0,
        "COMMODITIES": 6.0,
    }
    CONTRACT_SIZES = {
        "FOREX": 100000,
        "COMMODITIES": 100,
    }
    CONTRACT_SIZES_SPECIFIC = {
        "XAUUSD": 100,
    }
    MAX_LEVERAGE = {
        "FOREX": 1000,
        "XAUUSD": 1000,
    }
    MIN_LOT = 0.01

    YAHOO_SYMBOLS = {
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X",
        "AUDUSD": "AUDUSD=X",
        "USDCAD": "USDCAD=X",
        "USDCHF": "USDCHF=X",
        "NZDUSD": "NZDUSD=X",
        "EURGBP": "EURGBP=X",
        "EURJPY": "EURJPY=X",
        "GBPJPY": "GBPJPY=X",
        "XAUUSD": "XAUUSD=X",
    }

    TRAILING_ACTIVATION = 0.5
    ATR_MULT_TRAIL = 1.5

    NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
