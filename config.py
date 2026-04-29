
import os


def _getenv_required(name: str) -> str:
    """Retorna env var; se n\u00e3o existir/vazia, retorna '' (valida\u00e7\u00e3o acontece em main.py)."""
    return os.getenv(name, "").strip()


class Config:
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # CREDENCIAIS \u2014 devem vir obrigatoriamente de vari\u00e1veis de ambiente
    # Railway \u2192 Variables
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    BOT_TOKEN = _getenv_required("7952260034:AAHTy0sTn5jIA0a7O9yJOQ9qPwZLxQDbxf4")
    CHAT_ID   = _getenv_required("1056795017")

    # Twelve Data \u2014 chave gr\u00e1tis em https://twelvedata.com/
    TWELVE_DATA_API_KEY = _getenv_required("b0c5b7aa2b1e430b83d14c4fe0db3cfd")

    # Google Gemini \u2014 chave gr\u00e1tis em https://aistudio.google.com/apikey
    GEMINI_API_KEY = _getenv_required("AIzaSyDx9WQaAaALWcTTRudihFLfTb8HFAZPphQ")

    # Push opcional (ntfy.sh)
    NTFY_TOPIC = _getenv_required("NTFY_TOPIC")

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # MODO E TIMEFRAME
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    MODE = "FXGOLD"
    TIMEFRAME = "1h"

    FXGOLD_ASSETS = {
        "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
        "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
        "GBPJPY": "GBP/JPY", "XAUUSD": "Ouro"
    }

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # ALAVANCAGEM
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    DEFAULT_LEVERAGE  = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    USE_FIXED_LEVERAGE = True
    USE_DYNAMIC_LEVERAGE = True  # prevalece sobre USE_FIXED quando True

    # Tabela de alavancagem din\u00e2mica por faixa de capital
    DYNAMIC_LEVERAGE_TABLE = {
        500:           500,   # $0-$500
        2000:          200,
        5000:          100,
        10000:          50,
        30000:          30,
        float('inf'):   20,   # $30k+
    }

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # SMC & MULTI-TIMEFRAME
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    MTF_CONFIRM_TIMEFRAME    = "4h"
    MTF_MIN_CONFLUENCE       = 5
    FVG_LOOKBACK             = 20
    OB_LOOKBACK              = 15
    LIQUIDITY_SWING_LOOKBACK = 10

    # R:R din\u00e2mico baseado em score SMC
    TP_SL_RATIO_BASE   = 2.5
    TP_SL_RATIO_STEP   = 0.5
    MAX_TP_SL_RATIO    = 4.5
    USE_OB_FOR_SL      = True
    USE_LIQUIDITY_FOR_TP = True
    USE_FVG_FOR_TP     = True

    # Turtle Position Sizing
    ATR_RISK_PCT       = 1.0
    ATR_MULT_FOR_RISK  = 2.0

    # Fallback de SL/TP em porcentagem
    SL_TP_BASE_MULTIPLIER = 400.0
    SL_MAX_PCT            = 4.0
    SL_MIN_PCT            = 0.5
    TP_SL_RATIO           = 2.5

    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 2.5

    MIN_CONFLUENCE = 6

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # CAPITAL E RISCO
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    INITIAL_BALANCE        = float(os.getenv("START_BALANCE", "150"))
    RISK_PERCENT_PER_TRADE = 2.0

    # Correla\u00e7\u00e3o (regra 3-5-7)
    CORRELATION_GROUPS = {
        "USD_LONG":  ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "XAUUSD"],
        "USD_SHORT": ["USDJPY", "USDCAD", "USDCHF"],
        "EUROPE":    ["EURUSD", "EURGBP", "EURJPY"],
        "STERLING":  ["GBPUSD", "EURGBP", "GBPJPY"],
        "YEN":       ["USDJPY", "EURJPY", "GBPJPY"],
    }
    MAX_CORRELATED_RISK_PCT = 7.0

    MAX_TRADES             = 3
    ASSET_COOLDOWN         = 3600
    SCAN_INTERVAL          = 60
    PAUSE_DURATION         = 3600
    MAX_CONSECUTIVE_LOSSES = 3

    MARGIN_CALL_PCT = 100.0
    STOP_OUT_PCT    = 30.0

    TIMEFRAMES = {
        "1h": ("60d",  "1h"),
        "4h": ("120d", "1h"),
    }

    COMMISSION_PER_LOT = {"FOREX": 6.0, "COMMODITIES": 6.0}
    CONTRACT_SIZES     = {"FOREX": 100000, "COMMODITIES": 100}
    CONTRACT_SIZES_SPECIFIC = {"XAUUSD": 100}
    MAX_LEVERAGE       = {"FOREX": 1000, "XAUUSD": 1000}
    MIN_LOT            = 0.01

    YAHOO_SYMBOLS = {
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
        "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X",
        "NZDUSD": "NZDUSD=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X",
        "GBPJPY": "GBPJPY=X", "XAUUSD": "XAUUSD=X",
    }

    TRAILING_ACTIVATION = 0.5
    ATR_MULT_TRAIL      = 1.5

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # PROTE\u00c7\u00d5ES DE SEGURAN\u00c7A (FASE 500x)
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

    # M\u00e1ximo de trades ativos por n\u00edvel de banca
    DYNAMIC_MAX_TRADES = {
        500:          1,
        1500:         2,
        float('inf'): 3,
    }

    # Tier system de ativos
    ASSET_TIERS = {
        0: {"min_balance": 0,    "symbols": ["EURUSD", "GBPUSD"]},
        1: {"min_balance": 500,  "symbols": ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]},
        2: {"min_balance": 1000, "symbols": ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF",
                                             "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "USDJPY"]},
        3: {"min_balance": 2000, "symbols": list(FXGOLD_ASSETS.keys())},
    }

    # Risco m\u00e1ximo absoluto (USD) por trade
    MAX_RISK_ABSOLUTE_USD = {
        500:          5.0,
        1500:        15.0,
        3000:        30.0,
        float('inf'): 100.0,
    }

    # Margem livre m\u00ednima obrigat\u00f3ria
    MIN_FREE_MARGIN_PCT = {
        500:          0.60,
        1500:         0.40,
        3000:         0.25,
        float('inf'): 0.15,
    }

    # Prote\u00e7\u00e3o de gap fim de semana
    FRIDAY_NO_TRADE_AFTER_HOUR  = 20  # UTC
    SUNDAY_NO_TRADE_BEFORE_HOUR = 22  # UTC

    # Candle an\u00f4malo: se body > N*ATR, ignora sinal
    ATR_ANOMALY_MULT = 2.5

    # Cooldown ap\u00f3s loss
    DYNAMIC_COOLDOWN = {
        500:          7200,  # 2h
        1500:         5400,  # 1.5h
        float('inf'): 3600,  # 1h
    }

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # VALIDA\u00c7\u00c3O
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    @classmethod
    def validate(cls) -> list[str]:
        """Retorna lista de erros de configura\u00e7\u00e3o. Vazia = tudo OK."""
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("TELEGRAM_TOKEN n\u00e3o configurado")
        if not cls.CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID n\u00e3o configurado")
        if not cls.TWELVE_DATA_API_KEY:
            errors.append("TWELVE_DATA_API_KEY n\u00e3o configurado (obrigat\u00f3rio para obter candles)")
        if not cls.GEMINI_API_KEY:
            # Warning apenas \u2014 bot funciona sem IA mas aprova tudo
            errors.append("AVISO: GEMINI_API_KEY n\u00e3o configurado \u2014 IA desativada")
        if cls.INITIAL_BALANCE <= 0:
            errors.append(f"START_BALANCE inv\u00e1lido: {cls.INITIAL_BALANCE}")
        return errors
