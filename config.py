import os


def _getenv_required(name: str) -> str:
    """Retorna env var; se não existir/vazia, retorna '' (validação acontece em main.py)."""
    return os.getenv(name, "").strip()


class Config:
    # ═══════════════════════════════════════════════════════════════════════════════
    # CREDENCIAIS — devem vir obrigatoriamente de variáveis de ambiente
    # Railway → Variables
    # ═══════════════════════════════════════════════════════════════════════════════
    BOT_TOKEN = _getenv_required("TELEGRAM_TOKEN")
    CHAT_ID = _getenv_required("TELEGRAM_CHAT_ID")

    # Twelve Data — chave grátis em https://twelvedata.com/
    TWELVE_DATA_API_KEY = _getenv_required("TWELVE_DATA_API_KEY")

    # Google Gemini — chave grátis em https://aistudio.google.com/apikey
    GEMINI_API_KEY = _getenv_required("GEMINI_API_KEY")

    # Push opcional (ntfy.sh)
    NTFY_TOPIC = _getenv_required("NTFY_TOPIC")

    # Backup remoto opcional de state/logs (Supabase Storage / S3-compatible)
    # Deixe vazio para desabilitar.
    BACKUP_REMOTE_URL = os.getenv("BACKUP_REMOTE_URL", "").strip()
    BACKUP_REMOTE_TOKEN = os.getenv("BACKUP_REMOTE_TOKEN", "").strip()
    BACKUP_INTERVAL = int(os.getenv("BACKUP_INTERVAL", "3600"))

    # ═══════════════════════════════════════════════════════════════════════════════
    # MODO E TIMEFRAME
    # ═══════════════════════════════════════════════════════════════════════════════
    # ATENÇÃO: este bot é SINALIZADOR apenas. Não executa ordens no broker.
    # O "saldo" e os trades "ativos" são uma simulação para estatística.
    # ═══════════════════════════════════════════════════════════════════════════════
    MODE = "FXGOLD"
    TIMEFRAME = "1h"
    BOT_IS_SIGNAL_ONLY = True  # flag semântica exibida no dashboard

    FXGOLD_ASSETS = {
        "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
        "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
        "GBPJPY": "GBP/JPY", "XAUUSD": "Ouro",
    }

    # ═══════════════════════════════════════════════════════════════════════════════
    # AJUSTE GERAL DE FREQUÊNCIA x QUALIDADE
    # ═══════════════════════════════════════════════════════════════════════════════
    # Perfil balanceado: reduz travas duras sem transformar o bot em overtrader.
    USE_SESSION_FILTER = True
    USE_NEWS_FILTER = True
    USE_AVOID_HOURS = False

    # Notícias: janela mais objetiva para não pausar o bot por tempo demais.
    NEWS_MINUTES_BEFORE = 10
    NEWS_MINUTES_AFTER = 20
    ONLY_BLOCK_HIGH_IMPACT = True

    # Exige apenas um apoio mínimo de contexto (SMC ou H4), em vez de exigir tudo.
    MIN_SUPPORT_CHECKS = 1

    # ═══════════════════════════════════════════════════════════════════════════════
    # ALAVANCAGEM
    # ═══════════════════════════════════════════════════════════════════════════════
    DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    USE_FIXED_LEVERAGE = True
    USE_DYNAMIC_LEVERAGE = True  # prevalece sobre USE_FIXED quando True

    # Tabela de alavancagem dinâmica por faixa de capital
    DYNAMIC_LEVERAGE_TABLE = {
        500: 500,   # $0-$500
        2000: 200,
        5000: 100,
        10000: 50,
        30000: 30,
        float('inf'): 20,   # $30k+
    }

    # ═══════════════════════════════════════════════════════════════════════════════
    # SMC & MULTI-TIMEFRAME
    # ═══════════════════════════════════════════════════════════════════════════════
    MTF_CONFIRM_TIMEFRAME = "4h"
    MTF_MIN_CONFLUENCE = 4
    FVG_LOOKBACK = 20
    OB_LOOKBACK = 15
    LIQUIDITY_SWING_LOOKBACK = 10

    # R:R dinâmico baseado em score SMC
    TP_SL_RATIO_BASE = 2.2
    TP_SL_RATIO_STEP = 0.35
    MAX_TP_SL_RATIO = 4.0
    USE_OB_FOR_SL = True
    USE_LIQUIDITY_FOR_TP = True
    USE_FVG_FOR_TP = True

    # Turtle Position Sizing
    ATR_RISK_PCT = 1.0
    ATR_MULT_FOR_RISK = 2.0

    # Fallback de SL/TP em percentagem
    SL_TP_BASE_MULTIPLIER = 400.0
    SL_MAX_PCT = 4.0
    SL_MIN_PCT = 0.5
    TP_SL_RATIO = 2.2

    ATR_SL_MULT = 1.5
    ATR_TP_MULT = 2.4

    # ═══════════════════════════════════════════════════════════════════════════════
    # SISTEMA DE PESOS PARA CONFLUÊNCIA
    # A ideia aqui é manter a qualidade, mas permitir mais sinais válidos.
    # ═══════════════════════════════════════════════════════════════════════════════
    CONFLUENCE_WEIGHTS = {
        # Tendência (base técnica)
        "ema200": 2,
        "ema9_21": 1,
        "macd": 1,
        "rsi": 1,
        "adx": 2,
        "bands": 1,
        "candle": 1,
        # SMC (setup propriamente)
        "fvg": 2,
        "ob": 2,
        "sweep": 1,
        "structure": 1,
        # Multi-timeframe
        "mtf_aligned": 2,
        "mtf_ema200": 1,
    }
    CONFLUENCE_MAX_SCORE = 17
    MIN_CONFLUENCE_WEIGHTED = 8

    # Legado — mantido para compatibilidade
    MIN_CONFLUENCE = 5

    # ═══════════════════════════════════════════════════════════════════════════════
    # PRÉ-SINAL / RADAR PREMIUM
    # ═══════════════════════════════════════════════════════════════════════════════
    PRE_SIGNAL_COOLDOWN = 1200   # 20 minutos entre alertas do mesmo par/direção
    PRE_SIGNAL_GAP = 2           # quantos pontos abaixo do mínimo ainda viram "quase sinal"
    PRE_SIGNAL_MAX_AGE = 14400   # 4 horas: tempo máximo para confirmar o pré-sinal

    # ═══════════════════════════════════════════════════════════════════════════════
    # CAPITAL E RISCO
    # ═══════════════════════════════════════════════════════════════════════════════
    INITIAL_BALANCE = float(os.getenv("START_BALANCE", "150"))
    RISK_PERCENT_PER_TRADE = 2.0

    # Correlação (regra 3-5-7)
    CORRELATION_GROUPS = {
        "USD_LONG": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "XAUUSD"],
        "USD_SHORT": ["USDJPY", "USDCAD", "USDCHF"],
        "EUROPE": ["EURUSD", "EURGBP", "EURJPY"],
        "STERLING": ["GBPUSD", "EURGBP", "GBPJPY"],
        "YEN": ["USDJPY", "EURJPY", "GBPJPY"],
    }
    MAX_CORRELATED_RISK_PCT = 7.0

    MAX_TRADES = 3
    ASSET_COOLDOWN = 2400
    SCAN_INTERVAL = 60
    PAUSE_DURATION = 1800
    MAX_CONSECUTIVE_LOSSES = 3

    MARGIN_CALL_PCT = 100.0
    STOP_OUT_PCT = 30.0

    TIMEFRAMES = {
        "1h": ("60d", "1h"),
        "4h": ("120d", "1h"),
    }

    COMMISSION_PER_LOT = {"FOREX": 6.0, "COMMODITIES": 6.0}
    CONTRACT_SIZES = {"FOREX": 100000, "COMMODITIES": 100}
    CONTRACT_SIZES_SPECIFIC = {"XAUUSD": 100}
    MAX_LEVERAGE = {"FOREX": 1000, "XAUUSD": 1000}
    MIN_LOT = 0.01

    YAHOO_SYMBOLS = {
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
        "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X",
        "NZDUSD": "NZDUSD=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X",
        "GBPJPY": "GBPJPY=X", "XAUUSD": "XAUUSD=X",
    }

    TRAILING_ACTIVATION = 0.5
    ATR_MULT_TRAIL = 1.5

    # ═══════════════════════════════════════════════════════════════════════════════
    # PROTEÇÕES DE SEGURANÇA (FASE 500x)
    # ═══════════════════════════════════════════════════════════════════════════════

    # Máximo de trades ativos por nível de banca
    DYNAMIC_MAX_TRADES = {
        500: 1,
        1500: 2,
        float('inf'): 3,
    }

    # Tier system de ativos
    ASSET_TIERS = {
        0: {"min_balance": 0, "symbols": ["EURUSD", "GBPUSD"]},
        1: {"min_balance": 500, "symbols": ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]},
        2: {"min_balance": 1000, "symbols": ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF",
                                             "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "USDJPY"]},
        3: {"min_balance": 2000, "symbols": list(FXGOLD_ASSETS.keys())},
    }

    # Risco máximo absoluto (USD) por trade
    MAX_RISK_ABSOLUTE_USD = {
        500: 5.0,
        1500: 15.0,
        3000: 30.0,
        float('inf'): 100.0,
    }

    # Margem livre mínima obrigatória
    MIN_FREE_MARGIN_PCT = {
        500: 0.60,
        1500: 0.40,
        3000: 0.25,
        float('inf'): 0.15,
    }

    # Proteção de gap fim de semana
    FRIDAY_NO_TRADE_AFTER_HOUR = 20  # UTC
    SUNDAY_NO_TRADE_BEFORE_HOUR = 22  # UTC

    # Candle anômalo: se body > N*ATR, ignora sinal
    ATR_ANOMALY_MULT = 2.5

    # Cooldown após loss
    DYNAMIC_COOLDOWN = {
        500: 5400,   # 1h30
        1500: 4200,  # 70min
        float('inf'): 3600,  # 1h
    }

    # ═══════════════════════════════════════════════════════════════════════════════
    # EXPIRAÇÃO DE SINAIS PENDENTES
    # ═══════════════════════════════════════════════════════════════════════════════
    PENDING_EXPIRY_SECONDS = int(os.getenv("PENDING_EXPIRY_SECONDS", "7200"))  # 2h

    # ═══════════════════════════════════════════════════════════════════════════════
    # TELEGRAM — RETRIES
    # ═══════════════════════════════════════════════════════════════════════════════
    TELEGRAM_MAX_RETRIES = 3
    TELEGRAM_RETRY_DELAY = 2.0

    # ═══════════════════════════════════════════════════════════════════════════════
    # VALIDAÇÃO
    # ═══════════════════════════════════════════════════════════════════════════════
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
            errors.append("❌ DEFAULT_LEVERAGE deve ser >= 1")

        if cls.MAX_CONSECUTIVE_LOSSES < 1:
            errors.append("❌ MAX_CONSECUTIVE_LOSSES deve ser >= 1")

        return errors
