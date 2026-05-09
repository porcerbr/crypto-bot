from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "production"

    account_balance: float = 10_000.0
    risk_per_trade: float = 0.005
    max_daily_loss: float = 0.03
    max_daily_trades: int = 5
    max_loss_streak: int = 3

    symbols: str = "EURUSD,GBPUSD,USDJPY,XAUUSD"
    timeframes: str = "M5,M15,H1"

    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    poll_interval_seconds: int = 5
    min_signal_score: float = 75.0
    min_rr: float = 1.8
    port: int = 8000

    dashboard_enabled: bool = True
    historical_lookback: int = 500

    @property
    def symbols_list(self) -> List[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]

    @property
    def timeframes_list(self) -> List[str]:
        return [s.strip().upper() for s in self.timeframes.split(",") if s.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
