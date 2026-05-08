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
    ANTHROPIC_API_KEY = _getenv_required("ANTHROPIC_API_KEY")  # Claude (Sonnet)
    GEMINI_API_KEY    = _getenv_required("GEMINI_API_KEY")      # Legado — não mais usado

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
    USE_YAHOO_FALLBACK  = False     # Railway bloqueia Yahoo Finance — usar stale cache
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
    TIMEFRAME         = os.getenv("TIMEFRAME", "M15")  # M15 = mais sinais; H1 = conservador
    BOT_IS_SIGNAL_ONLY = True  # flag semântica exibida no dashboard

    # Em modo sinalizador, sessão e notícias viram preferência de qualidade,
    # não veto absoluto. Isso evita o bot ficar parado por longos períodos.
    SESSION_HARD_BLOCK = True
    NEWS_HARD_BLOCK = True
    MAX_SYMBOLS_PER_REFRESH = 6
    MAX_CORRELATED_SIGNALS_PER_GROUP = 2
    PAIR_PERFORMANCE_LOOKBACK = 12
    MIN_RECENT_PAIR_WR = 0.40
    ALLOW_RANGE_REVERSALS = False  # foco em trend-following robusto
    MIN_AI_CONFIDENCE  = 5       # sinais com nota IA abaixo disso são descartados (0 = filtro desativado)
    USE_COT_FILTER     = False    # filtra sinais contra o posicionamento institucional (CFTC/COT)
    SIGNAL_COOLDOWN_SECONDS = 1800

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
    # SISTEMA LEVE DE CONFLUÊNCIA — FX CORE
    # Mantido apenas o que costuma aparecer com mais consistência em FX:
    # tendência (EMA200), momentum (MACD/RSI) e volatilidade (ATR para gestão).
    # ═══════════════════════════════════════════════════════════════════════════════
    CONFLUENCE_WEIGHTS = {
        "ema200":          4,  # tendência principal
        "macd":            3,  # momentum direcional
        "rsi":             2,  # timing / força relativa
        "adx":             0,
        "fvg":             0,
        "ob":              0,
        "sweep":           0,
        "mtf_aligned":     0,
    }
    CONFLUENCE_MAX_SCORE = 9
    MIN_CONFLUENCE_WEIGHTED = 6

    # Legado — mantido para compatibilidade
    MIN_CONFLUENCE = 5

    # ═══════════════════════════════════════════════════════════════════════════════
    # PERFIL PROFISSIONAL DE EXECUÇÃO
    # ═══════════════════════════════════════════════════════════════════════════════
    # Ajustado proporcionalmente ao novo CONFLUENCE_MAX_SCORE = 16
    REGIME_MIN_CONFLUENCE = {
        "trend": 6,
        "range": 0,
        "transition": 5,
        "neutral": 5
    }
    REGIME_MIN_RR = {
        "trend": 1.6,
        "range": 1.3,
        "transition": 1.5,
        "neutral": 1.5,
    }
    REGIME_ADX_TRENDING = 25
    REGIME_ADX_RANGING  = 18
    REGIME_ADX_STRONG   = 30
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
    RISK_PERCENT_PER_TRADE = 2.0

    # ═══════════════════════════════════════════════════════════════════════════════
    # MULTI-CONTA / ESCALA DE CAPITAL / PROTEÇÃO INTELIGENTE
    # ═══════════════════════════════════════════════════════════════════════════════
    MULTI_ACCOUNT_ENABLED = True
    ACCOUNT_ALLOCATIONS = {
        "core": 0.55,
        "growth": 0.30,
        "reserve": 0.15,
    }
    ACCOUNT_RISK_MULTIPLIERS = {
        "core": 0.90,
        "growth": 1.10,
        "reserve": 0.55,
    }
    RISK_SCALING_TIERS = {
        200: 0.85,
        500: 1.00,
        1000: 1.15,
        2500: 1.30,
        float('inf'): 1.45,
    }
    RISK_SCALING_BASE_PCT = 1.0
    MIN_RISK_PCT = 0.5
    MAX_RISK_PCT = 2.2
    ACCOUNT_DAILY_LOSS_LIMIT_PCT = {
        "core": 3.5,
        "growth": 4.5,
        "reserve": 2.0,
    }
    ACCOUNT_WEEKLY_LOSS_LIMIT_PCT = {
        "core": 7.5,
        "growth": 9.0,
        "reserve": 4.0,
    }
    ACCOUNT_MAX_DRAWDOWN_PCT = {
        "core": 8.0,
        "growth": 10.0,
        "reserve": 5.0,
    }
    ACCOUNT_CONSECUTIVE_LOSSES_PAUSE = 3
    ACCOUNT_LOCK_SECONDS = 3600
    EQUITY_PROTECTION_DD_PCT = 12.0
    PROFIT_LOCK_LEVELS = {
        200: 0.0,
        500: 1.0,
        1000: 2.0,
        2500: 3.0,
    }

    # Correlação (regra 3-5-7)
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

    # ─── Limites de perda (Fase 4) ────────────────────────────────────────────
    # Perda máxima diária: ao atingir, bot pausa até meia-noite UTC
    MAX_DAILY_LOSS_PCT  = float(os.getenv("MAX_DAILY_LOSS_PCT",  "5.0"))
    # Perda máxima semanal: ao atingir, bot pausa até segunda-feira UTC
    MAX_WEEKLY_LOSS_PCT = float(os.getenv("MAX_WEEKLY_LOSS_PCT", "10.0"))

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
        500:          1,
        1500:         2,
        float('inf'): 3,
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
        500:          7200,  # 2h
        1500:         5400,  # 1.5h
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

        # Multi-account / escala de capital
        alloc_sum = round(sum(cls.ACCOUNT_ALLOCATIONS.values()), 4)
        if abs(alloc_sum - 1.0) > 0.01:
            errors.append(f"❌ ACCOUNT_ALLOCATIONS deve somar 1.0 (atual: {alloc_sum})")
        if cls.MIN_RISK_PCT <= 0 or cls.MAX_RISK_PCT <= 0:
            errors.append("❌ MIN_RISK_PCT / MAX_RISK_PCT inválidos")
        if cls.MIN_RISK_PCT > cls.MAX_RISK_PCT:
            errors.append("❌ MIN_RISK_PCT > MAX_RISK_PCT")
        if cls.EQUITY_PROTECTION_DD_PCT <= 0:
            errors.append("❌ EQUITY_PROTECTION_DD_PCT inválido")

        return errors
