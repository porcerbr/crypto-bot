# config.py
import os

class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN", "7952260034:AAG6sFwQ6nhuZrYXaqR6v5G2wmfQtZhuXE4")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")

    # Modo de operação e Timeframe padrão
    MODE = os.getenv("MODE", "CRYPTO")
    TIMEFRAME = os.getenv("TIMEFRAME", "15m")

    MARKET_CATEGORIES = {
        "FOREX": {"label": "FOREX", "assets": {
            "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD",
            "USDCAD": "USD/CAD", "USDCHF": "USD/CHF", "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
            "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY"}},
        "CRYPTO": {"label": "CRIPTO", "assets": {
            "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
            "BNB-USD": "BNB", "XRP-USD": "XRP", "ADA-USD": "Cardano",
            "DOGE-USD": "Dogecoin", "LTC-USD": "Litecoin"}},
        "COMMODITIES": {"label": "COMMODITIES", "assets": {
            "GC=F": "Ouro", "SI=F": "Prata", "CL=F": "Petróleo WTI", "BZ=F": "Brent",
            "NG=F": "Gás Natural", "HG=F": "Cobre"}},
        "INDICES": {"label": "ÍNDICES", "assets": {
            "ES=F": "S&P 500", "NQ=F": "Nasdaq 100", "YM=F": "Dow Jones",
            "^GDAXI": "DAX 40", "^FTSE": "FTSE 100", "^N225": "Nikkei 225"}}
    }

    # SL/TP com base na alavancagem
    SL_TP_BASE_MULTIPLIER = 250.0
    SL_MAX_PCT = 3.0
    SL_MIN_PCT = 0.2
    TP_SL_RATIO = 2.5

    # Confluência mínima (score de 0 a 7)
    MIN_CONFLUENCE = 5

    # Parâmetros de risco
    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "1000"))
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "200"))
    RISK_PERCENT_PER_TRADE = 2.0  # usado apenas como sugestão

    # Operacional
    MAX_TRADES = 3
    ASSET_COOLDOWN = 3600    # segundos após loss do mesmo ativo
    SCAN_INTERVAL = 60       # segundos
    PAUSE_DURATION = 3600    # 1h se 3 losses consecutivos
    MAX_CONSECUTIVE_LOSSES = 3

    # Yahoo Finance – períodos para cada timeframe
    TIMEFRAMES = {
        "1m":  ("7d", "1m"),
        "5m":  ("5d", "5m"),
        "15m": ("5d", "15m"),
        "30m": ("5d", "30m"),
        "1h":  ("60d", "1h"),
        "4h":  ("60d", "1h"),
    }

    # Dados de contrato (para cálculo de lote)
    COMMISSION_PER_LOT = {
        "FOREX": 6.0,
        "COMMODITIES": 6.0,
        "INDICES": 0.0,
        "CRYPTO": 0.0,
    }
    CONTRACT_SIZES = {
        "FOREX": 100000,
        "CRYPTO": 1,
        "COMMODITIES": 100,
        "INDICES": 1,
    }
    CONTRACT_SIZES_SPECIFIC = {
        "GC=F": 100, "SI=F": 5000, "CL=F": 1000, "BZ=F": 1000,
        "NG=F": 10000, "HG=F": 25000,
    }
    MAX_LEVERAGE = {
        "FOREX": 100, "CRYPTO": 50, "COMMODITIES": 50, "INDICES": 50,
    }
