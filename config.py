"""
core/config.py — Configuração centralizada via .env
Toda configuração do sistema passa por aqui. Nunca use valores hardcoded.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env da raiz do projeto
load_dotenv(Path(__file__).parent.parent / ".env")


class Settings:
    # ── Ambiente ────────────────────────────────────────────────
    ENV: str = os.getenv("ENV", "development")          # development | production
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── Mercado ─────────────────────────────────────────────────
    SYMBOL: str = os.getenv("SYMBOL", "BTC-USD")
    TIMEFRAME: str = os.getenv("TIMEFRAME", "1h")
    QUOTE_CURRENCY: str = os.getenv("QUOTE_CURRENCY", "USD")

    # ── Dados ───────────────────────────────────────────────────
    DATA_PROVIDER: str = os.getenv("DATA_PROVIDER", "yfinance")
    DATA_LOOKBACK_BARS: int = int(os.getenv("DATA_LOOKBACK_BARS", "200"))
    API_TIMEOUT_SECONDS: int = int(os.getenv("API_TIMEOUT_SECONDS", "15"))
    API_RETRY_ATTEMPTS: int = int(os.getenv("API_RETRY_ATTEMPTS", "3"))
    API_RETRY_DELAY: float = float(os.getenv("API_RETRY_DELAY", "2.0"))

    # ── Estratégia ───────────────────────────────────────────────
    RSI_PERIOD: int = int(os.getenv("RSI_PERIOD", "14"))
    RSI_OVERSOLD: float = float(os.getenv("RSI_OVERSOLD", "30"))
    RSI_OVERBOUGHT: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
    EMA_FAST: int = int(os.getenv("EMA_FAST", "9"))
    EMA_SLOW: int = int(os.getenv("EMA_SLOW", "21"))
    MACD_FAST: int = int(os.getenv("MACD_FAST", "12"))
    MACD_SLOW: int = int(os.getenv("MACD_SLOW", "26"))
    MACD_SIGNAL: int = int(os.getenv("MACD_SIGNAL", "9"))
    BB_PERIOD: int = int(os.getenv("BB_PERIOD", "20"))
    BB_STD: float = float(os.getenv("BB_STD", "2.0"))
    MIN_SIGNAL_SCORE: float = float(os.getenv("MIN_SIGNAL_SCORE", "65.0"))

    # ── Risco ────────────────────────────────────────────────────
    MAX_OPEN_TRADES: int = int(os.getenv("MAX_OPEN_TRADES", "3"))
    MAX_DAILY_TRADES: int = int(os.getenv("MAX_DAILY_TRADES", "10"))
    MAX_DRAWDOWN_PCT: float = float(os.getenv("MAX_DRAWDOWN_PCT", "5.0"))
    RISK_PER_TRADE_PCT: float = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
    STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "2.0"))
    TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "4.0"))
    MIN_VOLUME_FACTOR: float = float(os.getenv("MIN_VOLUME_FACTOR", "0.8"))

    # ── Scheduler ────────────────────────────────────────────────
    CYCLE_INTERVAL_SECONDS: int = int(os.getenv("CYCLE_INTERVAL_SECONDS", "300"))
    HEALTH_CHECK_INTERVAL: int = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))

    # ── Dashboard ────────────────────────────────────────────────
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8080"))
    DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")

    # ── Storage ──────────────────────────────────────────────────
    DB_PATH: str = os.getenv("DB_PATH", "data/bot.db")
    STATE_FILE: str = os.getenv("STATE_FILE", "data/state.json")

    # ── Alertas ──────────────────────────────────────────────────
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    ALERT_ON_SIGNAL: bool = os.getenv("ALERT_ON_SIGNAL", "false").lower() == "true"

    # ── Capital Simulado ─────────────────────────────────────────
    INITIAL_CAPITAL: float = float(os.getenv("INITIAL_CAPITAL", "10000.0"))

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def timeframe_seconds(self) -> int:
        mapping = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600,
                   "4h": 14400, "1d": 86400}
        return mapping.get(self.TIMEFRAME, 3600)


settings = Settings()
