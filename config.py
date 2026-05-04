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
    CHAT_ID   = _getenv_required("TELEGRAM_CHAT_ID")

    # Twelve Data — chave grátis em https://twelvedata.com/
    TWELVE_DATA_API_KEY = _getenv_required("TWELVE_DATA_API_KEY")

    # Google Gemini — chave grátis em https://aistudio.google.com/apikey
    GEMINI_API_KEY = _getenv_required("GEMINI_API_KEY")

    # Push opcional (ntfy.sh)
    NTFY_TOPIC = _getenv_required("NTFY_TOPIC")

    # Backup remoto opcional de state/logs (Supabase Storage / S3-compatible)
    # Deixe vazio para desabilitar.
    BACKUP_REMOTE_URL   = os.getenv("BACKUP_REMOTE_URL",   "").strip()
    BACKUP_REMOTE_TOKEN = os.getenv("BACKUP_REMOTE_TOKEN", "").strip()
    BACKUP_INTERVAL     = int(os.getenv("BACKUP_INTERVAL", "3600"))

    # ═══════════════════════════════════════════════════════════════════════════════
    # SEGURANÇA — Dashboard API
    # Gere com: python -c "import secrets; print(secrets.token_hex(32))"
    # ═══════════════════════════════════════════════════════════════════════════════
    DASHBOARD_API_TOKEN = os.getenv("DASHBOARD_API_TOKEN", "").strip()

    # ═══════════════════════════════════════════════════════════════════════════════
    # PERSISTÊNCIA — SQLite (WAL mode)
    # ═══════════════════════════════════════════════════════════════════════════════
    DB_PATH = os.getenv("DB_PATH", "bot_state.db")

    # ═══════════════════════════════════════════════════════════════════════════════
    # SIMULAÇÃO DE EXECUÇÃO — Spread e Slippage
    # Valores em pips por par (spread típico de broker ECN/STP)
    # ═══════════════════════════════════════════════════════════════════════════════
    SPREAD_PIPS = {
        "EURUSD": 0.6, "GBPUSD": 0.9, "USDJPY": 0.7,
        "AUDUSD": 0.8, "USDCAD": 1.0, "USDCHF": 1.0,
        "NZDUSD": 1.2, "EURGBP": 1.0, "EURJPY": 1.0,
        "GBPJPY": 1.5, "XAUUSD": 25.0,
    }
    SLIPPAGE_PIPS = {
        "EURUSD": 0.2, "GBPUSD": 0.3, "USDJPY": 0.2,
        "AUDUSD": 0.3, "USDCAD": 0.3, "USDCHF": 0.3,
        "NZDUSD": 0.4, "EURGBP": 0.3, "EURJPY": 0.3,
        "GBPJPY": 0.5, "XAUUSD": 5.0,
    }
    USE_SPREAD_MODEL    = True
    USE_SLIPPAGE_MODEL  = True

    # ═══════════════════════════════════════════════════════════════════════════════
    # FALLBACK DE DADOS — Yahoo Finance
    # ═══════════════════════════════════════════════════════════════════════════════
    USE_YAHOO_FALLBACK  = True
    YAHOO_FALLBACK_TTL  = 30 * 60

    # ═══════════════════════════════════════════════════════════════════════════════
    # RETRY / RESILIÊNCIA
    # ═══════════════════════════════════════════════════════════════════════════════
    API_RETRY_ATTEMPTS  = 3
    API_RETRY_MIN_WAIT  = 2
    API_RETRY_MAX_WAIT  = 30

    # ═══════════════════════════════════════════════════════════════════════════════
    # LOG ROTATION
    # ═══════════════════════════════════════════════════════════════════════════════
    LOG_MAX_BYTES       = 10 * 1024 * 1024
    LOG_BACKUP_COUNT    = 5

    # ═══════════════════════════════════════════════════════════════════════════════
    # MODO E TIMEFRAME
    # ═══════════════════════════════════════════════════════════════════════════════
    # ATENÇÃO: este bot é SINALIZADOR apenas. Não executa ordens no broker.
    # O "saldo" e os trades "ativos" são uma simulação para estatística.
    # ═══════════════════════════════════════════════════════════════════════════════
    MODE              = "FXGOLD"
    TIMEFRAME         = "1h"
    BOT_IS_SIGNAL_ONLY = True  # flag semântica exibida no dashboard

    # Em modo sinalizador, sessão e notícias viram preferência de qualidade,
    # não veto absoluto. Isso evita o bot ficar parado por longos períodos.
    SESSION_HARD_BLOCK = False
    NEWS_HARD_BLOCK = False
    MAX_SYMBOLS_PER_REFRESH = 8

    FXGOLD_ASSETS = {
        "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
        "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "USDCHF": "USD/CHF",
        "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP", "EURJPY": "EUR/JPY",
        "GBPJPY": "GBP/JPY", "XAUUSD": "Ouro"
    }

    # ═══════════════════════════════════════════════════════════════════════════════
    # ALAVANCAGEM
    # ═══════════════════════════════════════════════════════════════════════════════
    DEFAULT_LEVERAGE   = int(os.getenv("DEFAULT_LEVERAGE", "500"))
    USE_FIXED_LEVERAGE = True
    USE_DYNAMIC_LEVERAGE = True  # prevalece sobre USE_FIXED quando True

    # Tabela de alavancagem dinâmica por faixa de capital
    DYNAMIC_LEVERAGE_TABLE = {
        500:           500,   # $0-$500
        2000:          200,
        5000:          100,
        10000:          50,
        30000:          30,
        float('inf'):   20,   # $30k+
    }

    # ═══════════════════════════════════════════════════════════════════════════════
    # SMC & MULTI-TIMEFRAME
    # ═══════════════════════════════════════════════════════════════════════════════
    MTF_CONFIRM_TIMEFRAME    = "4h"
    MTF_MIN_CONFLUENCE       = 5
    FVG_LOOKBACK             = 20
    OB_LOOKBACK              = 15
    LIQUIDITY_SWING_LOOKBACK = 10

    # R:R dinâmico baseado em score SMC
    TP_SL_RATIO_BASE   = 2.5
    TP_SL_RATIO_STEP   = 0.5
    MAX_TP_SL_RATIO    = 4.5
    USE_OB_FOR_SL      = True
    USE_LIQUIDITY_FOR_TP = True
    USE_FVG_FOR_TP     = True

    # Turtle Position Sizing
    ATR_RISK_PCT       = 1.0
    ATR_MULT_FOR_RISK  = 2.0

    # Fallback de SL/TP em percentagem
    SL_TP_BASE_MULTIPLIER = 400.0
    SL_MAX_PCT            = 4.0
    SL_MIN_PCT            = 0.5
    TP_SL_RATIO           = 2.5

    ATR_SL_MULT = 2.0
    ATR_TP_MULT = 3.0

    # ═══════════════════════════════════════════════════════════════════════════════
    # SISTEMA DE PESOS PARA CONFLUÊNCIA
    # Total máximo: 20 pontos (vs 13 checks com peso 1 antigo)
    # Um setup "clássico" (EMAs + MACD + RSI) bate ~7 pontos.
    # Um setup SMC completo (FVG + OB + sweep + H4) bate ~11 pontos.
    # ═══════════════════════════════════════════════════════════════════════════════
    CONFLUENCE_WEIGHTS = {
        # Tendência (base técnica)
        "ema200":          2,  # preço > EMA200 (ou <)
        "ema9_21":         1,  # EMA9 > EMA21
        "macd":            1,  # MACD na direção
        "rsi":             1,  # RSI em zona favorável
        "adx":             2,  # ADX > 25 (força de tendência)
        "bands":           1,  # preço perto da banda oposta
        "candle":          1,  # candle de força (body >= 50% range)
        # SMC (setup propriamente)
        "fvg":             3,  # FVG ativo na direção
        "ob":              3,  # OB ativo na direção
        "sweep":           2,  # liquidity sweep confirmado
        "structure":       1,  # estrutura intacta
        # Multi-timeframe
        "mtf_aligned":     2,  # H4 na mesma direção
        "mtf_ema200":      1,  # H4 > EMA200 (ou <)
    }
    CONFLUENCE_MAX_SCORE = 21  # soma dos pesos acima
    MIN_CONFLUENCE_WEIGHTED = 10  # score mínimo para gerar sinal (default, pode ser ajustado pela IA)

    # Legado — mantido para compatibilidade
    MIN_CONFLUENCE = 7

    # ═══════════════════════════════════════════════════════════════════════════════
    # PERFIL PROFISSIONAL DE EXECUÇÃO
    # ═══════════════════════════════════════════════════════════════════════════════
    REGIME_MIN_CONFLUENCE = {
        "trend": 9,
        "range": 7,
        "transition": 8,
        "neutral": 8,
    }
    REGIME_MIN_RR = {
        "trend": 1.7,
        "range": 1.4,
        "transition": 1.6,
        "neutral": 1.6,
    }
    REGIME_ADX_TRENDING = 22
    REGIME_ADX_RANGING  = 16
    REGIME_ADX_STRONG   = 28
    PREMIUM_SETUP_BONUS = 1

    # ═══════════════════════════════════════════════════════════════════════════════
    # PRÉ-SINAL / RADAR PREMIUM
    # ═══════════════════════════════════════════════════════════════════════════════

    # ═══════════════════════════════════════════════════════════════════════════════
    # PRÉ-SINAL / RADAR PREMIUM
    # ═══════════════════════════════════════════════════════════════════════════════
    PRE_SIGNAL_COOLDOWN = 1800   # 30 minutos entre alertas do mesmo par/direção
    PRE_SIGNAL_GAP = 2           # quantos pontos abaixo do mínimo ainda viram "quase sinal"
    PRE_SIGNAL_MAX_AGE = 14400   # 4 horas: tempo máximo para confirmar o pré-sinal

    # ═══════════════════════════════════════════════════════════════════════════════
    # CAPITAL E RISCO
    # ═══════════════════════════════════════════════════════════════════════════════
    INITIAL_BALANCE        = float(os.getenv("START_BALANCE", "150"))
    RISK_PERCENT_PER_TRADE = 1.0

    # Correlação (regra 3-5-7)
    CORRELATION_GROUPS = {
        "USD_LONG":  ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "XAUUSD"],
        "USD_SHORT": ["USDJPY", "USDCAD", "USDCHF"],
        "EUROPE":    ["EURUSD", "EURGBP", "EURJPY"],
        "STERLING":  ["GBPUSD", "EURGBP", "GBPJPY"],
        "YEN":       ["USDJPY", "EURJPY", "GBPJPY"],
    }
    MAX_CORRELATED_RISK_PCT = 7.0

    MAX_TRADES             = 4
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

    # ═══════════════════════════════════════════════════════════════════════════════
    # PROTEÇÕES DE SEGURANÇA (FASE 500x)
    # ═══════════════════════════════════════════════════════════════════════════════

    # Máximo de trades ativos por nível de banca
    DYNAMIC_MAX_TRADES = {
        500:          2,
        1500:         3,
        float('inf'): 4,
    }

    # Tier system de ativos
    ASSET_TIERS = {
        # No modo sinalizador o bot monitora todo o universo desde o início.
        0: {"min_balance": 0,    "symbols": list(FXGOLD_ASSETS.keys())},
        1: {"min_balance": 500,  "symbols": list(FXGOLD_ASSETS.keys())},
        2: {"min_balance": 1000, "symbols": list(FXGOLD_ASSETS.keys())},
        3: {"min_balance": 2000, "symbols": list(FXGOLD_ASSETS.keys())},
    }

    # Risco máximo absoluto (USD) por trade
    MAX_RISK_ABSOLUTE_USD = {
        500:          5.0,
        1500:        15.0,
        3000:        30.0,
        float('inf'): 100.0,
    }

    # Margem livre mínima obrigatória
    MIN_FREE_MARGIN_PCT = {
        500:          0.60,
        1500:         0.40,
        3000:         0.25,
        float('inf'): 0.15,
    }

    # Proteção de gap fim de semana
    FRIDAY_NO_TRADE_AFTER_HOUR  = 20  # UTC
    SUNDAY_NO_TRADE_BEFORE_HOUR = 22  # UTC

    # Candle anômalo: se body > N*ATR, ignora sinal
    ATR_ANOMALY_MULT = 2.5

    # Cooldown após loss
    DYNAMIC_COOLDOWN = {
        500:          3600,  # 1h
        1500:         2700,  # 45min
        float('inf'): 1800,  # 30min
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

    # ═══════════════════════════════���═══════════════════════════════════════════════
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
            errors.append(f"❌ DEFAULT_LEVERAGE deve ser >= 1")
        
        if cls.MAX_CONSECUTIVE_LOSSES < 1:
            errors.append(f"❌ MAX_CONSECUTIVE_LOSSES deve ser >= 1")
        
        return errors
