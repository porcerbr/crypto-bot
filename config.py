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

    # SL/TP para H1
    SL_TP_BASE_MULTIPLIER = 400.0   # SL = 400 / alavancagem
    SL_MAX_PCT = 4.0
    SL_MIN_PCT = 0.5
    TP_SL_RATIO = 2.5

    # Confluência elevada para win rate ≥55%
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
        "FOREX": 500,
        "XAUUSD": 500,
    }
    MIN_LOT = 0.01
