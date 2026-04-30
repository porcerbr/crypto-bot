
import os


def _getenv_required(name: str) -> str:
    """Retorna env var; se n\u00e3o existir/vazia, retorna '' (valida\u00e7\u00e3o acontece em main.py)."""
    return os.getenv(name, "").strip()


class Config:
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # CREDENCIAIS \u2014 devem vir obrigatoriamente de vari\u00e1veis de ambiente
    # Railway \u2192 Variables
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    BOT_TOKEN = _getenv_required("TELEGRAM_TOKEN")
    CHAT_ID   = _getenv_required("TELEGRAM_CHAT_ID")

    # Twelve Data \u2014 chave gr\u00e1tis em https://twelvedata.com/
    TWELVE_DATA_API_KEY = _getenv_required("TWELVE_DATA_API_KEY")

    # Google Gemini \u2014 chave gr\u00e1tis em https://aistudio.google.com/apikey
    GEMINI_API_KEY = _getenv_required("GEMINI_API_KEY")

    # Push opcional (ntfy.sh)
    NTFY_TOPIC = _getenv_required("NTFY_TOPIC")

    # Backup remoto opcional de state/logs (Supabase Storage / S3-compatible)
    # Deixe vazio para desabilitar.
    BACKUP_REMOTE_URL   = os.getenv("BACKUP_REMOTE_URL",   "").strip()  # ex: https://xxx.supabase.co/storage/v1/object/bucket/path
    BACKUP_REMOTE_TOKEN = os.getenv("BACKUP_REMOTE_TOKEN", "").strip()  # service role key ou bearer
    BACKUP_INTERVAL     = int(os.getenv("BACKUP_INTERVAL", "3600"))      # segundos

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # MODO E TIMEFRAME
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # ATEN\u00c7\u00c3O: este bot \u00e9 SINALIZADOR apenas. N\u00e3o executa ordens no broker.
    # O "saldo" e os trades "ativos" s\u00e3o uma simula\u00e7\u00e3o para estat\u00edstica.
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    MODE              = "FXGOLD"
    TIMEFRAME         = "1h"
    BOT_IS_SIGNAL_ONLY = True  # flag sem\u00e2ntica exibida no dashboard

    FXGOLD_ASSETS = {
        "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
        "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
        "GBPJPY": "GBP/JPY", "XAUUSD": "Ouro"
    }

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # ALAVANCAGEM
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    DEFAULT_LEVERAGE   = int(os.getenv("DEFAULT_LEVERAGE", "500"))
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

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # SMC & MULTI-TIMEFRAME
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
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

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # SISTEMA DE PESOS PARA CONFLU\u00caNCIA
    # Total m\u00e1ximo: 20 pontos (vs 13 checks com peso 1 antigo)
    # Um setup "cl\u00e1ssico" (EMAs + MACD + RSI) bate ~7 pontos.
    # Um setup SMC completo (FVG + OB + sweep + H4) bate ~11 pontos.
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    CONFLUENCE_WEIGHTS = {
        # Tend\u00eancia (base t\u00e9cnica)
        "ema200":          2,  # pre\u00e7o > EMA200 (ou <)
        "ema9_21":         1,  # EMA9 > EMA21
        "macd":            1,  # MACD na dire\u00e7\u00e3o
        "rsi":             1,  # RSI em zona favor\u00e1vel
        "adx":             2,  # ADX > 25 (for\u00e7a de tend\u00eancia)
        "bands":           1,  # pre\u00e7o perto da banda oposta
        "candle":          1,  # candle de for\u00e7a (body >= 50% range)
        # SMC (setup propriamente)
        "fvg":             3,  # FVG ativo na dire\u00e7\u00e3o
        "ob":              3,  # OB ativo na dire\u00e7\u00e3o
        "sweep":           2,  # liquidity sweep confirmado
        "structure":       1,  # estrutura intacta
        # Multi-timeframe
        "mtf_aligned":     2,  # H4 na mesma dire\u00e7\u00e3o
        "mtf_ema200":      1,  # H4 > EMA200 (ou <)
    }
    CONFLUENCE_MAX_SCORE = 21  # soma dos pesos acima, calculado estaticamente
    MIN_CONFLUENCE_WEIGHTED = 10  # score m\u00ednimo para gerar sinal (default, pode ser ajustado pela IA)

    # Legado \u2014 mantido para compatibilidade
    MIN_CONFLUENCE = 6

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # CAPITAL E RISCO
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
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

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # PROTE\u00c7\u00d5ES DE SEGURAN\u00c7A (FASE 500x)
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

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

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # EXPIRA\u00c7\u00c3O DE SINAIS PENDENTES
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    PENDING_EXPIRY_SECONDS = int(os.getenv("PENDING_EXPIRY_SECONDS", "7200"))  # 2h

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # TELEGRAM \u2014 RETRIES
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    TELEGRAM_MAX_RETRIES = 3
    TELEGRAM_RETRY_DELAY = 2.0

    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # VALIDA\u00c7\u00c3O
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    
    # Em config.py, localize o método validate() e substitua por:

@classmethod
def validate(cls) -> list:
    """
    Retorna lista de erros de configuração.
    Lista vazia = tudo OK.
    ❌ = erro crítico (exit)
    ⚠️  = aviso (continua)
    """
    errors = []
    
    if not cls.BOT_TOKEN:
        errors.append("❌ TELEGRAM_TOKEN não configurado")
    if not cls.CHAT_ID:
        errors.append("❌ TELEGRAM_CHAT_ID não configurado")
    if not cls.TWELVE_DATA_API_KEY:
        errors.append("❌ TWELVE_DATA_API_KEY não configurado (obrigatório)")
    
    # ⚠️ Aviso, não erro
    if not cls.GEMINI_API_KEY:
        errors.append("⚠️  GEMINI_API_KEY não configurado — IA desativada (usando fallback técnico)")
    
    if cls.INITIAL_BALANCE <= 0:
        errors.append(f"❌ START_BALANCE inválido: {cls.INITIAL_BALANCE}")
    
    # Validação de limites
    if cls.MARGIN_CALL_PCT <= cls.STOP_OUT_PCT:
        errors.append(f"❌ MARGIN_CALL_PCT ({cls.MARGIN_CALL_PCT}) <= STOP_OUT_PCT ({cls.STOP_OUT_PCT})")
    
    if cls.DEFAULT_LEVERAGE < 1:
        errors.append(f"❌ DEFAULT_LEVERAGE deve ser >= 1")
    
    if cls.MAX_CONSECUTIVE_LOSSES < 1:
        errors.append(f"❌ MAX_CONSECUTIVE_LOSSES deve ser >= 1")
    
    return errors
