#!/usr/bin/env python3
"""Ponto de entrada do Trading Bot Pro.

Inicializa logging, cria engine e inicia dashboard.
Suporta execução direta ou via Gunicorn (produção).
"""
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
from pathlib import Path

from config import get_settings
from core.engine import TradingEngine
from dashboard.app import run_dashboard


def setup_logging():
    """Configura logging com rotação de arquivos.

    Dois handlers:
    - Console: INFO+ (visível no Railway)
    - Arquivo: DEBUG+ com rotação (persistência)
    """
    settings = get_settings()
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, settings.log_level))
    console.setFormatter(formatter)

    # Arquivo rotativo
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)

    # Reduzir verbosity de bibliotecas externas
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


def main():
    """Fluxo principal da aplicação."""
    setup_logging()
    logger = logging.getLogger("Main")

    logger.info("=" * 50)
    logger.info("Trading Bot Pro v1.0 iniciando")
    logger.info("=" * 50)

    settings = get_settings()
    logger.info(f"Modo: {settings.operation_mode}")
    logger.info(f"Ativo: {settings.trading_symbol}")
    logger.info(f"Intervalo: {settings.collect_interval}s")

    # Criar engine
    engine = TradingEngine()

    # Handler de shutdown graceful
    def shutdown(signum, frame):
        logger.info("Sinal de shutdown recebido. Parando engine...")
        engine.stop()
        time.sleep(1)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Iniciar engine automaticamente
    engine.start()

    # Iniciar dashboard (bloqueante)
    try:
        run_dashboard(engine)
    except Exception as e:
        logger.critical(f"Dashboard falhou: {e}")
        engine.stop()
        raise


if __name__ == "__main__":
    main()
