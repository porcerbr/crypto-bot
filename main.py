import asyncio

from core_engine import MarketEngine
from data_provider import DemoLiveProvider
from risk_risk_manager import RiskManager
from strategies_confluence_strategy import ConfluenceStrategy
from telegram_bot import TelegramNotifier
from utils_config import settings
from utils_logger import setup_logger


async def main() -> None:
    logger = setup_logger("main")
    logger.info("Iniciando Forex Signal Bot")
    provider = DemoLiveProvider()
    strategy = ConfluenceStrategy()
    risk_manager = RiskManager()
    notifier = TelegramNotifier()

    engine = MarketEngine(
        provider=provider,
        strategy=strategy,
        risk_manager=risk_manager,
        notifier=notifier,
    )
    await engine.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
