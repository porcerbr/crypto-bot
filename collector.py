"""
data/collector.py — Coleta de dados de mercado
Suporta múltiplos provedores com retry automático e fallback inteligente.
Nunca lança exceção para o engine — retorna None em falha total.
"""

import asyncio
import time
from typing import Optional
import pandas as pd
from loguru import logger

from core.config import settings


class DataCollector:
    """
    Coleta OHLCV de mercado com:
    - Retry com backoff exponencial
    - Cache local para fallback
    - Timeout configurável
    - Suporte a múltiplos provedores
    """

    def __init__(self):
        self._cache: Optional[pd.DataFrame] = None
        self._cache_timestamp: float = 0
        self._cache_max_age = settings.CYCLE_INTERVAL_SECONDS * 2
        self._consecutive_failures = 0

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
    ) -> Optional[pd.DataFrame]:
        """
        Ponto de entrada principal. Tenta provedores em ordem e usa cache como
        último recurso. Retorna DataFrame com colunas [open, high, low, close, volume].
        """
        provider = settings.DATA_PROVIDER

        for attempt in range(1, settings.API_RETRY_ATTEMPTS + 1):
            try:
                logger.debug(f"Coleta via '{provider}' — tentativa {attempt}")
                df = await asyncio.wait_for(
                    self._fetch_from(provider, symbol, timeframe, bars),
                    timeout=settings.API_TIMEOUT_SECONDS,
                )
                if df is not None and not df.empty:
                    df = self._clean(df)
                    self._update_cache(df)
                    self._consecutive_failures = 0
                    logger.debug(f"Dados recebidos: {len(df)} barras")
                    return df

            except asyncio.TimeoutError:
                logger.warning(f"Timeout na tentativa {attempt}/{settings.API_RETRY_ATTEMPTS}")
            except Exception as exc:
                logger.warning(f"Erro na tentativa {attempt}: {exc}")

            if attempt < settings.API_RETRY_ATTEMPTS:
                delay = settings.API_RETRY_DELAY * (2 ** (attempt - 1))
                logger.debug(f"Aguardando {delay:.1f}s antes de nova tentativa")
                await asyncio.sleep(delay)

        # Todas tentativas falharam — usar cache
        self._consecutive_failures += 1
        if self._cache is not None:
            cache_age = time.time() - self._cache_timestamp
            logger.warning(
                f"Usando cache ({cache_age:.0f}s de idade) — "
                f"{self._consecutive_failures} falhas consecutivas"
            )
            return self._cache.copy()

        logger.error("Sem dados disponíveis — cache vazio e API inacessível")
        return None

    async def _fetch_from(
        self, provider: str, symbol: str, timeframe: str, bars: int
    ) -> Optional[pd.DataFrame]:
        """Despacha para o provedor correto."""
        if provider == "yfinance":
            return await self._fetch_yfinance(symbol, timeframe, bars)
        elif provider == "binance":
            return await self._fetch_binance(symbol, timeframe, bars)
        else:
            logger.error(f"Provedor desconhecido: {provider}")
            return None

    # ── Provedores ────────────────────────────────────────────────

    async def _fetch_yfinance(
        self, symbol: str, timeframe: str, bars: int
    ) -> Optional[pd.DataFrame]:
        """Yahoo Finance — free, sem autenticação, ideal para desenvolvimento."""
        import yfinance as yf

        tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m",
            "1h": "1h", "4h": "4h", "1d": "1d",
        }
        period_map = {
            "1m": "7d", "5m": "60d", "15m": "60d",
            "1h": "730d", "4h": "730d", "1d": "5y",
        }
        yf_interval = tf_map.get(timeframe, "1h")
        period = period_map.get(timeframe, "730d")

        loop = asyncio.get_event_loop()
        ticker = yf.Ticker(symbol)
        df = await loop.run_in_executor(
            None,
            lambda: ticker.history(period=period, interval=yf_interval),
        )
        if df is None or df.empty:
            return None

        df = df.rename(columns=str.lower)
        df = df[["open", "high", "low", "close", "volume"]].tail(bars)
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    async def _fetch_binance(
        self, symbol: str, timeframe: str, bars: int
    ) -> Optional[pd.DataFrame]:
        """Binance REST API — requer API Key em produção."""
        import httpx

        base_url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol.replace("-", ""),
            "interval": timeframe,
            "limit": min(bars, 1000),
        }
        async with httpx.AsyncClient(timeout=settings.API_TIMEOUT_SECONDS) as client:
            resp = await client.get(base_url, params=params)
            resp.raise_for_status()

        klines = resp.json()
        df = pd.DataFrame(klines, columns=[
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])
        df = df[["time", "open", "high", "low", "close", "volume"]]
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        df = df.set_index("time")
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
        return df

    # ── Limpeza ───────────────────────────────────────────────────

    def _clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove NaN, zeros e ordena por tempo."""
        df = df.dropna()
        df = df[df["close"] > 0]
        df = df[df["volume"] > 0]
        df = df.sort_index()
        return df

    def _update_cache(self, df: pd.DataFrame):
        self._cache = df.copy()
        self._cache_timestamp = time.time()
