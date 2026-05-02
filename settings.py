"""Configurações centralizadas do bot usando Pydantic Settings.

Todas as variáveis são carregadas do .env com validação de tipos.
Isso evita erros silenciosos de configuração em produção.
"""
import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Operação
    operation_mode: Literal["SIMULATION", "LIVE"] = Field(default="SIMULATION")
    trading_symbol: str = Field(default="BTC-USD")
    collect_interval: int = Field(default=60, ge=10)
    timeframe: str = Field(default="5m")
    lookback_period: int = Field(default=100, ge=20)

    # Risco
    max_risk_per_trade: float = Field(default=2.0, gt=0, le=100)
    max_exposure: float = Field(default=10.0, gt=0, le=100)
    max_open_trades: int = Field(default=3, ge=1)

    # Horário
    trade_start_hour: int = Field(default=9, ge=0, le=23)
    trade_end_hour: int = Field(default=21, ge=0, le=23)

    # Filtros
    max_volatility_pct: float = Field(default=5.0, gt=0)
    min_volume_ratio: float = Field(default=1.2, gt=0)
    min_signal_score: int = Field(default=65, ge=0, le=100)

    # APIs externas
    alpha_vantage_key: str = Field(default="")
    news_api_key: str = Field(default="")

    # Dashboard
    dashboard_host: str = Field(default="0.0.0.0")
    dashboard_port: int = Field(default=5000, ge=1, le=65535)
    dashboard_debug: bool = Field(default=False)
    secret_key: str = Field(default="change-me")

    # Storage
    db_path: str = Field(default="data_storage/bot_state.db")

    # Logging
    log_level: str = Field(default="INFO")
    log_max_bytes: int = Field(default=10_485_760)
    log_backup_count: int = Field(default=5)

    @field_validator("trade_end_hour")
    @classmethod
    def end_after_start(cls, v: int, info) -> int:
        start = info.data.get("trade_start_hour", 0)
        if v <= start:
            raise ValueError("trade_end_hour deve ser maior que trade_start_hour")
        return v

    @property
    def is_simulation(self) -> bool:
        return self.operation_mode == "SIMULATION"


@lru_cache()
def get_settings() -> Settings:
    """Retorna instância cacheada das configurações.

    O cache garante que o .env seja lido apenas uma vez,
    melhorando performance e evitando inconsistências.
    """
    return Settings()
