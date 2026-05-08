"""
telegram_testkit.py — kit para testar Telegram sem internet.

Ele simula os endpoints usados pelo TelegramDesk:
- sendMessage
- getUpdates
- getMe
- getFile
- download de arquivo

Uso em testes:
    api = FakeTelegramAPI()
    api.add_text('/pause 5')
    api.install(monkeypatch, telegram_hedgefund)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class FakeResponse:
    payload: dict | None = None
    status_code: int = 200
    content: bytes = b""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        if self.payload is None:
            return {}
        return self.payload

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeTelegramAPI:
    def __init__(self):
        self.sent_messages: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.files: dict[str, bytes] = {}
        self.fail_next_posts: int = 0
        self.fail_next_gets: int = 0
        self._update_id = 1000

    def add_text(self, text: str, chat_id: str = "123") -> dict:
        self._update_id += 1
        upd = {"update_id": self._update_id, "message": {"chat": {"id": chat_id}, "text": text}}
        self.updates.append(upd)
        return upd

    def add_document(self, filename: str, content: bytes, caption: str = "", chat_id: str = "123") -> dict:
        file_id = f"file_{len(self.files) + 1}"
        self.files[file_id] = content
        self._update_id += 1
        upd = {
            "update_id": self._update_id,
            "message": {
                "chat": {"id": chat_id},
                "caption": caption,
                "document": {"file_id": file_id, "file_name": filename},
            },
        }
        self.updates.append(upd)
        return upd

    def post(self, url: str, json: dict | None = None, timeout: int | float | None = None):
        if self.fail_next_posts > 0:
            self.fail_next_posts -= 1
            raise RuntimeError("simulated Telegram POST failure")
        method = url.rstrip("/").split("/")[-1]
        if method == "sendMessage":
            self.sent_messages.append(json or {})
            return FakeResponse({"ok": True, "result": {"message_id": len(self.sent_messages)}})
        if method == "deleteWebhook":
            return FakeResponse({"ok": True, "result": True})
        return FakeResponse({"ok": True, "result": {}})

    def get(self, url: str, params: dict | None = None, timeout: int | float | None = None):
        if self.fail_next_gets > 0:
            self.fail_next_gets -= 1
            raise RuntimeError("simulated Telegram GET failure")
        if "/file/bot" in url:
            file_path = url.rstrip("/").split("/")[-1]
            # file_path é simulado como downloads/<file_id>
            file_id = file_path.split("_")[-1]
            key = f"file_{file_id}" if not file_path.startswith("file_") else file_path
            return FakeResponse(status_code=200, content=self.files.get(key, b""))

        method = url.rstrip("/").split("/")[-1]
        if method == "getMe":
            return FakeResponse({"ok": True, "result": {"username": "fake_bot"}})
        if method == "getUpdates":
            offset = int((params or {}).get("offset", 0) or 0)
            result = [u for u in self.updates if int(u.get("update_id", 0)) >= offset]
            return FakeResponse({"ok": True, "result": result})
        if method == "getFile":
            file_id = (params or {}).get("file_id")
            if file_id not in self.files:
                return FakeResponse({"ok": False, "description": "file not found"}, status_code=404)
            return FakeResponse({"ok": True, "result": {"file_path": f"downloads/{file_id}"}})
        return FakeResponse({"ok": True, "result": {}})

    def install(self, monkeypatch, telegram_module):
        monkeypatch.setattr(telegram_module.requests, "post", self.post)
        monkeypatch.setattr(telegram_module.requests, "get", self.get)
        return self

    def last_text(self) -> str:
        if not self.sent_messages:
            return ""
        return str(self.sent_messages[-1].get("text", ""))
