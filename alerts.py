"""
monitoring/alerts.py — Sistema de alertas
Suporte a Telegram. Extensível para Slack, Discord, e-mail, etc.
"""

import asyncio
from loguru import logger
from core.config import settings


class AlertSystem:
    async def send(self, message: str, level: str = "info"):
        logger.info(f"[ALERTA/{level.upper()}] {message}")
        if settings.TELEGRAM_TOKEN and settings.TELEGRAM_CHAT_ID:
            await self._send_telegram(message)

    async def _send_telegram(self, message: str):
        try:
            import httpx
            url = f"https://api.telegram.org/bot{settings.TELEGRAM_TOKEN}/sendMessage"
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                })
        except Exception as exc:
            logger.warning(f"Falha ao enviar alerta Telegram: {exc}")
