from __future__ import annotations

import aiohttp

from core_models import Signal
from utils_config import settings


class TelegramNotifier:
    def __init__(self) -> None:
        self.enabled = settings.telegram_enabled
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    async def send_message(self, text: str) -> None:
        if not self.enabled or not self.token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=15) as resp:
                await resp.text()

    async def send_signal(self, signal: Signal) -> None:
        text = (
            f"<b>{signal.side.value} {signal.symbol}</b>\n"
            f"Entrada: {signal.entry:.5f}\n"
            f"SL: {signal.stop_loss:.5f}\n"
            f"TP: {signal.take_profit:.5f}\n"
            f"RR: 1:{signal.rr:.2f}\n"
            f"Score: {signal.score:.1f}\n"
            f"Confiança: {signal.confidence:.0%}\n"
            f"Probabilidade: {signal.probability:.0%}\n"
            f"{signal.reason}"
        )
        await self.send_message(text)
