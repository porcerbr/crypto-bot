from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from core_indicators import add_indicators
from core_models import Signal
from data_provider import MarketDataProvider
from risk_risk_manager import RiskManager
from strategies_confluence_strategy import ConfluenceStrategy
from telegram_bot import TelegramNotifier
from utils_config import settings
from utils_logger import setup_logger
from utils_storage import SignalStorage


class MarketEngine:
    def __init__(
        self,
        provider: MarketDataProvider,
        strategy: ConfluenceStrategy,
        risk_manager: RiskManager,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self.provider = provider
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.notifier = notifier or TelegramNotifier()
        self.storage = SignalStorage()
        self.logger = setup_logger("engine")
        self.latest_signals: list[Signal] = []

    async def _prepare(self, symbol: str, timeframe: str) -> pd.DataFrame:
        candles = await self.provider.get_candles(symbol, timeframe, limit=settings.historical_lookback)
        return add_indicators(candles)

    async def analyze_symbol(self, symbol: str) -> Signal | None:
        m5 = await self._prepare(symbol, "M5")
        m15 = await self._prepare(symbol, "M15")
        h1 = await self._prepare(symbol, "H1")

        spread = await self.provider.get_spread(symbol)
        if not self.strategy.filters.spread_ok(spread, symbol):
            self.logger.info("%s: spread alto (%.2f)", symbol, spread)
            return None
        if not self.strategy.filters.volatility_ok(m5):
            self.logger.info("%s: baixa volatilidade", symbol)
            return None
        if not self.strategy.filters.session_ok():
            self.logger.info("%s: fora da sessão", symbol)
            return None
        if not self.strategy.filters.news_ok(symbol):
            self.logger.info("%s: bloqueado por notícia", symbol)
            return None

        signal = self.strategy.generate_signal(symbol, m5, m15, h1)
        if signal is None:
            return None

        signal = self.risk_manager.apply(signal)
        if signal is None:
            return None

        self.storage.append(signal)
        self.latest_signals.append(signal)
        self.latest_signals = self.latest_signals[-100:]

        await self.notifier.send_signal(signal)
        self.logger.info(
            "%s %s score=%.1f rr=%.2f conf=%.0f%%",
            signal.side.value,
            signal.symbol,
            signal.score,
            signal.rr,
            signal.confidence * 100,
        )
        return signal

    async def run_once(self) -> list[Signal]:
        results: list[Signal] = []
        for symbol in settings.symbols_list:
            try:
                signal = await self.analyze_symbol(symbol)
                if signal:
                    results.append(signal)
            except Exception as exc:
                self.logger.exception("Erro analisando %s: %s", symbol, exc)
        return results

    async def run_forever(self) -> None:
        self.logger.info("MarketEngine iniciado.")
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                self.logger.exception("Erro no loop principal: %s", exc)
            await asyncio.sleep(settings.poll_interval_seconds)
