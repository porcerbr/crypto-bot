import os

class Config:
    BOT_TOKEN  = os.getenv("TELEGRAM_TOKEN", "7952260034:AAFz3nzC0BJ7Fp7YKwDBIv_HiBX5Sg04TLg")
    CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "1056795017")

    # ── Twelve Data ───────────────────────────────────────────
    # Chave grátis em: https://twelvedata.com/
    # Railway → Variables → TWELVE_DATA_API_KEY
    TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

    # ── Google Gemini (IA de validação e aprendizado — GRÁTIS) ───
    # Chave grátis em: https://aistudio.google.com/apikey
    # Railway → Variables → GEMINI_API_KEY
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

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

    # ═══════════════════════════════════════════════════════════
    # NOVO: ALAVANCAGEM DINÂMICA POR BANCA
    # ═══════════════════════════════════════════════════════════
    # Reduz alavancagem conforme capital cresce — protege lucros
    # acumulados e reduz drasticamente o risco de gap catastrófico
    DYNAMIC_LEVERAGE_TABLE = {
        500:    500,   # $0-$500:   sobrevivência (única opção viável)
        2000:   200,   # $500-$2k:  já operável, reduz risco
        5000:   100,   # $2k-$5k:   confortável
        10000:  50,    # $5k-$10k:  crescimento seguro
        30000:  30,    # $10k-$30k: sustentabilidade
        float('inf'): 20,  # $30k+: patrimônio, alav institucional
    }

    # Se True, usa a tabela acima. Se False, usa DEFAULT_LEVERAGE fixo.
    USE_DYNAMIC_LEVERAGE = True

    # ═══════════════════════════════════════════════════════════
    # NOVO: PROTEÇÕES DE SEGURANÇA PARA FASE 500x
    # ═══════════════════════════════════════════════════════════

    # 1. Máximo de trades ativos por nível de banca
    # Com $150 e 500x, 3 trades abertos = suicídio se mercado abrir com gap
    DYNAMIC_MAX_TRADES = {
        500:    1,   # até $500:   APENAS 1 trade por vez
        1500:   2,   # até $1500:  máximo 2 trades
        float('inf'): 3,  # acima: 3 trades (seu padrão original)
    }

    # 2. Ativos permitidos por nível de banca (tier system)
    # Bloqueia pares voláteis enquanto banca é pequena demais
    ASSET_TIERS = {
        0: {
            "min_balance": 0,
            "symbols": ["EURUSD", "GBPUSD"],  # majors mais estáveis
        },
        1: {
            "min_balance": 500,
            "symbols": ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"],
        },
        2: {
            "min_balance": 1000,
            "symbols": ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF",
                       "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "USDJPY"],
        },
        3: {
            "min_balance": 2000,
            "symbols": list(FXGOLD_ASSETS.keys()),  # tudo incluindo XAUUSD
        },
    }

    # 3. Risco máximo ABSOLUTO por trade (em USD)
    # Impede que banca pequena arrisque demais em um único trade
    MAX_RISK_ABSOLUTE_USD = {
        500:    5.0,    # até $500:   máx $5 de risco por trade
        1500:   15.0,   # até $1500:  máx $15
        3000:   30.0,   # até $3000:  máx $30
        float('inf'): 100.0,  # acima: máx $100
    }

    # 4. Margem mínima livre obrigatória antes de abrir trade
    # Garante buffer contra gaps e movimentos bruscos
    MIN_FREE_MARGIN_PCT = {
        500:    0.60,   # 60% livre obrigatório (só pode usar 40%)
        1500:   0.40,   # 40% livre
        3000:   0.25,   # 25% livre
        float('inf'): 0.15,  # 15% livre
    }

    # 5. Proteção de fim de semana / gap
    # Não abre novos trades próximo do fechamento de sexta ou na abertura de domingo
    FRIDAY_NO_TRADE_AFTER_HOUR = 20   # UTC — não abre após 20h de sexta
    SUNDAY_NO_TRADE_BEFORE_HOUR = 22  # UTC — não abre antes de 22h de domingo

    # 6. ATR anômalo mais agressivo
    # Se candle > 2.5x ATR, ignora sinal (era 3x no seu código original)
    ATR_ANOMALY_MULT = 2.5

    # 7. Cooldown extendido após loss em fase 500x
    # Com banca pequena, 1h pode não ser suficiente para resetar
    DYNAMIC_COOLDOWN = {
        500:    7200,   # 2 horas
        1500:   5400,   # 1.5 horas
        float('inf'): 3600,  # 1h padrão
    }
