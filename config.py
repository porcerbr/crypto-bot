import os

class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN", "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")

    # Modo e timeframe FIXOS
    MODE = "FXGOLD"
    TIMEFRAME = "1h"

    # Ativos Forex + Ouro
    FXGOLD_ASSETS = {
        "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
        "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
        "GBPJPY": "GBP/JPY", "XAUUSD": "Ouro"
    }

    # Fallback porcentagem (quando ATR indisponível)
    SL_TP_BASE_MULTIPLIER = 400.0
    SL_MAX_PCT = 4.0
    SL_MIN_PCT = 0.5
    TP_SL_RATIO = 2.5

    # ATR-based SL/TP (preferencial na Tickmill)
    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 2.5

    # Confluência
    MIN_CONFLUENCE = 6

    # Banca e risco
    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "150"))
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    RISK_PERCENT_PER_TRADE = 2.0

    # Operacional
    MAX_TRADES = 3
    ASSET_COOLDOWN = 3600
    SCAN_INTERVAL = 60
    PAUSE_DURATION = 3600
    MAX_CONSECUTIVE_LOSSES = 3

    # Tickmill Margin / Stop Out
    MARGIN_CALL_PCT = 100.0
    STOP_OUT_PCT = 30.0

    # Yahoo Finance – período H1
    TIMEFRAMES = {
        "1h": ("60d", "1h"),
    }

    # Comissões e contratos
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

    # Mapeamento Yahoo Finance — XAUUSD agora é spot proxy
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

    # Trailing Stop
    TRAILING_ACTIVATION = 0.5
    ATR_MULT_TRAIL = 1.5

    # Notificação push
    NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
    
