"""
TradingBot Professional — Entry Point
Inicializa todos os módulos e sobe o sistema completo.
"""

import sys
import signal
import asyncio
from loguru import logger

from core.config import settings
from core.engine import BotEngine
from dashboard.server import start_dashboard


def configure_logging():
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> — <white>{message}</white>",
        colorize=True,
    )
    logger.add(
        "logs/bot_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        compression="gz",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}",
        encoding="utf-8",
    )
    logger.add(
        "logs/errors_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        compression="gz",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} — {message}\n{exception}",
        encoding="utf-8",
    )


async def main():
    configure_logging()
    logger.info("=" * 60)
    logger.info("  TradingBot Professional — Iniciando Sistema")
    logger.info(f"  Ambiente : {settings.ENV}")
    logger.info(f"  Símbolo  : {settings.SYMBOL}")
    logger.info(f"  Timeframe: {settings.TIMEFRAME}")
    logger.info("=" * 60)

    engine = BotEngine()

    loop = asyncio.get_event_loop()

    def shutdown(sig, frame):
        logger.warning(f"Sinal {sig} recebido — encerrando graciosamente...")
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Sobe o dashboard em background
    import threading
    dash_thread = threading.Thread(
        target=start_dashboard,
        kwargs={"engine": engine},
        daemon=True,
    )
    dash_thread.start()
    logger.info(f"Dashboard disponível em http://localhost:{settings.DASHBOARD_PORT}")

    # Inicia o engine principal (bloqueante)
    await engine.run()


if __name__ == "__main__":
    asyncio.run(main())
