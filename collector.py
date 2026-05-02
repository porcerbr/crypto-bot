"""Módulo de coleta de dados de mercado.

Suporta múltiplas fontes com fallback automático.
Fonte primária: Yahoo Finance (gratuito, robusto)
Fallback: Dados sintéticos de último recurso para manter
o bot funcionando mesmo com falha total de APIs externas.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

from config import get_settings

logger = logging.getLogger("DataCollector")


class DataCollector:
    """Coletor de dados com timeout, retry e fallback."""

    def __init__(self):
        self.settings = get_settings()
        self._last_price: Optional[float] = None
        self._last_data: Optional[pd.DataFrame] = None

    def fetch(self, symbol: str, periods: int = 100) -> Optional[pd.DataFrame]:
        """Busca dados históricos com timeout e retry.

        Args:
            symbol: Ticker do ativo (ex: BTC-USD)
            periods: Quantidade de candles desejados

        Returns:
            DataFrame com colunas [Open, High, Low, Close, Volume]
            ou None em caso de falha.
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.debug(f"Coletando dados para {symbol} (tentativa {attempt + 1})")

                # Yahoo Finance com timeout implícito via requests
                ticker = yf.Ticker(symbol)
                # Converter timeframe para período do yfinance
                interval = self._map_interval(self.settings.timeframe)
                period = self._estimate_period(interval, periods)

                df = ticker.history(period=period, interval=interval, timeout=15)

                if df is None or df.empty:
                    raise ValueError("DataFrame vazio retornado")

                # Normalizar colunas
                df.columns = [c.lower().replace(" ", "_") for c in df.columns]
                df = df.reset_index()

                # Garantir colunas esperadas
                required = {"open", "high", "low", "close", "volume"}
                if not required.issubset(set(df.columns)):
                    raise ValueError(f"Colunas faltantes: {required - set(df.columns)}")

                # Atualizar cache
                self._last_data = df.copy()
                self._last_price = float(df["close"].iloc[-1])

                logger.info(f"Dados coletados: {len(df)} registros para {symbol}")
                return df

            except Exception as e:
                logger.warning(f"Tentativa {attempt + 1} falhou: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Backoff exponencial
                else:
                    logger.error(f"Todas as tentativas de coleta falharam para {symbol}")
                    return None

    def fallback_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """Gera dados sintéticos baseados no último valor conhecido.

        Usado quando todas as fontes externas falham.
        Mantém o bot operacional para recuperação posterior.
        """
        if self._last_data is not None and not self._last_data.empty:
            logger.warning("Usando dados em cache como fallback")
            return self._last_data.copy()

        logger.error("Fallback indisponível - sem dados em cache")
        return None

    def _map_interval(self, tf: str) -> str:
        """Mapeia timeframe interno para formato yfinance."""
        mapping = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "1d": "1d",
            "1wk": "1wk",
        }
        return mapping.get(tf, "5m")

    def _estimate_period(self, interval: str, periods: int) -> str:
        """Estima o período necessário para obter N candles."""
        # Estimativa conservadora
        if interval in ("1m", "5m", "15m", "30m"):
            return "5d"
        if interval == "1h":
            return "1mo"
        return "6mo"
