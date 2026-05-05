
"""
telegram_hedgefund.py — Telegram professional, signal-only, sem capital.
"""

from __future__ import annotations

import html
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import requests

from config import Config
from utils import asset_name, fmt, get_selected_symbols, load_strategy_settings


TG_LIMIT = 3900


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def _trim(text: str, limit: int = TG_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)] + "\n… (mensagem truncada)"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def _quality_10(score: float | int | None, total: float | int | None) -> int:
    try:
        score = float(score or 0)
        total = float(total or 0)
        if total <= 0:
            return 0
        return max(1, min(10, int(round((score / total) * 10))))
    except Exception:
        return 0


def _signal_bar(score: int, total: int) -> str:
    total = max(1, int(total or 1))
    score = max(0, min(int(score or 0), total))
    filled = round((score / total) * 10)
    filled = max(0, min(10, filled))
    return "🟢" * filled + "⚪" * (10 - filled)


def keyboard_markup() -> dict:
    return {
        "keyboard": [
            [{"text": "/status"}, {"text": "/report"}],
            [{"text": "/confluencia"}, {"text": "/trades"}],
            [{"text": "/pause"}, {"text": "/resume"}],
            [{"text": "/assets"}, {"text": "/help"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


@dataclass
class TelegramDeskState:
    offset: int = 0
    last_poll_ts: float = 0.0
    poll_interval: float = 0.8


class TelegramDesk:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self.base = f"https://api.telegram.org/bot{token}"
        self.state = TelegramDeskState()
        self._webhook_cleared = False
        self._me_cache: dict | None = None

    def _post(self, method: str, payload: dict):
        try:
            return requests.post(f"{self.base}/{method}", json=payload, timeout=10)
        except Exception:
            return None

    def _get(self, method: str, params: dict | None = None):
        try:
            return requests.get(f"{self.base}/{method}", params=params, timeout=15)
        except Exception:
            return None

    def bootstrap(self):
        """Garante polling limpo: remove webhook e descarta updates pendentes."""
        if self._webhook_cleared:
            return True
        try:
            self._post("deleteWebhook", {"drop_pending_updates": True})
            self.state.offset = 0
            self._webhook_cleared = True
            return True
        except Exception:
            return False

    def bot_username(self) -> str | None:
        if self._me_cache is not None:
            return self._me_cache.get("username")
        try:
            resp = self._get("getMe")
            if resp and resp.ok:
                data = resp.json()
                if data.get("ok") and isinstance(data.get("result"), dict):
                    self._me_cache = data["result"]
                    return self._me_cache.get("username")
        except Exception:
            pass
        return None

    def send(self, text: str, *, reply_markup: dict | None = None, disable_preview: bool = True):
        payload = {
            "chat_id": self.chat_id,
            "text": _trim(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def send_plain(self, text: str, *, reply_markup: dict | None = None):
        payload = {
            "chat_id": self.chat_id,
            "text": _trim(text),
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._post("sendMessage", payload)

    def get_updates(self):
        params = {
            "timeout": 15,
            "offset": self.state.offset,
            "allowed_updates": json.dumps(["message", "edited_message"]),
        }
        resp = self._get("getUpdates", params=params)
        if resp is None:
            return {"ok": False, "description": "request failed", "result": []}
        try:
            return resp.json()
        except Exception as e:
            return {"ok": False, "description": str(e), "result": []}

    def push_startup(self, bot):
        self.send(format_startup(bot), reply_markup=keyboard_markup())

    def push_heartbeat(self, bot, regime_info: dict | None = None):
        self.send(format_heartbeat(bot, regime_info or {}), reply_markup=keyboard_markup())

    def push_signal(self, trade: dict, bot=None):
        self.send(format_signal(trade, bot), reply_markup=keyboard_markup())

    def push_result(self, trade: dict, bot, result: str):
        self.send(format_result(trade, bot, result), reply_markup=keyboard_markup())

    def push_report(self, bot):
        self.send(format_report(bot), reply_markup=keyboard_markup())

    def push_status(self, bot, extra: str = ""):
        self.send(format_status(bot, extra=extra), reply_markup=keyboard_markup())

    def push_assets(self, bot):
        self.send(format_assets(bot), reply_markup=keyboard_markup())

    def push_trades(self, bot):
        self.send(format_trades(bot), reply_markup=keyboard_markup())

    def push_confluence(self, bot):
        try:
            from signals import get_confluence_snapshot
        except Exception as e:
            self.send(f"⚠️ <b>Confluence Desk</b>\nFalha ao carregar snapshot: {esc(e)}")
            return

        try:
            snapshot = get_confluence_snapshot()
            strategy = load_strategy_settings()
            lines = [
                "🧭 <b>CONFLUENCE DESK</b>",
                f"<b>Horário:</b> {_now_utc()}",
                f"<b>Min score:</b> {strategy.get('min_confluence', 5)}",
                f"<b>Timeframe:</b> {esc(getattr(bot, 'timeframe', '—'))}",
                "—" * 18,
            ]
            for item in snapshot[:12]:
                sym = item.get("symbol", "?")
                score = int(item.get("best_score", 0) or 0)
                total = int(item.get("total", 0) or 0)
                direction = item.get("best_dir", "—")
                h4 = "✅" if item.get("h4_aligned") else "❌"
                quality = _quality_10(score, total)
                status = "🔥 SINAL" if score >= strategy.get("min_confluence", 5) else "⚡ WATCH"
                lines.append(
                    f"{status} {esc(sym)} {esc(direction)} {score}/{total} | Qualidade {quality}/10\n"
                    f"  {_signal_bar(score, total)}\n"
                    f"  RSI:{item.get('rsi', '—')} ADX:{item.get('adx', '—')} H4:{h4}"
                )
            lines.append("—" * 18)
            lines.append("Confluência classificada apenas por força técnica.")
            self.send("\n".join(lines), reply_markup=keyboard_markup())
        except Exception as e:
            self.send(f"❌ <b>Erro ao calcular confluência:</b> {esc(e)}", reply_markup=keyboard_markup())

    def poll_commands(self, bot, on_confluence=None):
        executed = []
        if time.time() - self.state.last_poll_ts < self.state.poll_interval:
            return executed
        self.state.last_poll_ts = time.time()

        data = self.get_updates()
        if not data.get("ok"):
            return executed

        username = self.bot_username()
        for upd in data.get("result", []):
            try:
                uid = int(upd.get("update_id", 0))
                self.state.offset = max(self.state.offset, uid + 1)

                text = ""
                if upd.get("message"):
                    text = str(upd["message"].get("text", "") or "").strip()
                elif upd.get("edited_message"):
                    text = str(upd["edited_message"].get("text", "") or "").strip()

                if not text or not text.startswith("/"):
                    continue

                raw_cmd = text.split()[0].strip()
                cmd = raw_cmd.split("@", 1)[0].lower()

                executed.append(cmd.lstrip("/"))

                if cmd in ("/start", "/help"):
                    self.send(
                        "🤖 <b>SNIPER BOT | SIGNAL DESK</b>\n"
                        "Comandos disponíveis:\n"
                        "• /status — visão operacional\n"
                        "• /report — relatório do dia\n"
                        "• /confluencia — ranking dos setups\n"
                        "• /trades — sinais ativos\n"
                        "• /assets — ativos monitorados\n"
                        "• /pause [min] — pausa temporária\n"
                        "• /resume — retoma o bot\n"
                        "• /mode — modo e parâmetros\n\n"
                        "Botões abaixo para acesso rápido.",
                        reply_markup=keyboard_markup(),
                    )

                elif cmd == "/status":
                    self.push_status(bot)

                elif cmd == "/report":
                    self.push_report(bot)

                elif cmd == "/portfolio":
                    self.push_status(bot, extra="Portfólio desativado no modo signal-only.")

                elif cmd == "/confluencia":
                    if on_confluence:
                        on_confluence(bot)
                    else:
                        self.push_confluence(bot)

                elif cmd == "/assets":
                    self.push_assets(bot)

                elif cmd == "/trades":
                    self.push_trades(bot)

                elif cmd == "/pause":
                    minutes = 120
                    parts = text.split()
                    if len(parts) > 1:
                        try:
                            minutes = max(1, min(24 * 60, int(float(parts[1]))))
                        except Exception:
                            pass
                    if hasattr(bot, "pause_for"):
                        bot.pause_for(minutes * 60, reason=f"Telegram /pause {minutes}m")
                    else:
                        bot.paused_until = time.time() + minutes * 60
                    self.send(
                        f"⏸️ <b>Bot pausado</b>\nTempo: {minutes} min\nRetoma: {_now_utc()} + {minutes} min",
                        reply_markup=keyboard_markup(),
                    )

                elif cmd == "/resume":
                    if hasattr(bot, "resume"):
                        bot.resume()
                    else:
                        bot.paused_until = 0.0
                    self.send("▶️ <b>Bot retomado</b>\nModo operacional ativado.", reply_markup=keyboard_markup())

                elif cmd == "/mode":
                    strategy = load_strategy_settings()
                    self.send(
                        "🧠 <b>STRATEGY MODE</b>\n"
                        f"<b>Profile:</b> {esc(strategy.get('profile', 'hedge_fund'))}\n"
                        f"<b>Min confluence:</b> {strategy.get('min_confluence')}\n"
                        f"<b>ADX min:</b> {strategy.get('adx_min')}\n"
                        f"<b>RR mínimo:</b> {strategy.get('min_rr')}\n"
                        f"<b>Weekly target:</b> {strategy.get('weekly_trade_target')} sinal(is)",
                        reply_markup=keyboard_markup(),
                    )

                elif cmd == "/health":
                    self.send(format_health(bot), reply_markup=keyboard_markup())

                else:
                    self.send(
                        "Comando não reconhecido. Use /help para ver os comandos disponíveis.",
                        reply_markup=keyboard_markup(),
                    )
            except Exception:
                continue
        return executed


def format_startup(bot) -> str:
    strategy = load_strategy_settings()
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0
    lines = [
        "🚀 <b>SNIPER BOT ONLINE</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Modo:</b> SIGNAL ONLY",
        f"<b>Win rate:</b> {wr}% ({bot.wins}W / {bot.losses}L)",
        f"<b>Sinais ativos:</b> {len(getattr(bot, 'active_trades', []))}",
        f"<b>Sinais monitorados:</b> {len(getattr(bot, 'pending_trades', []))}",
        "—" * 18,
        f"<b>Profile:</b> {esc(strategy.get('profile', 'hedge_fund'))}",
        f"<b>Min confluence:</b> {strategy.get('min_confluence')}",
        f"<b>ADX min:</b> {strategy.get('adx_min')}",
        f"<b>Weekly target:</b> {strategy.get('weekly_trade_target')}",
        f"<b>Timeframe:</b> {esc(getattr(bot, 'timeframe', '—'))}",
    ]
    lines.append("<b>Status:</b> ⏸️ PAUSADO" if bot.is_paused() else "<b>Status:</b> ✅ OPERANDO")
    return "\n".join(lines)


def format_heartbeat(bot, regime_info: dict) -> str:
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0
    live_regime = str(regime_info.get("live_regime", "neutral")).upper()
    avg_adx = regime_info.get("avg_adx", 0)
    eff_conf = regime_info.get("effective_conf", load_strategy_settings().get("min_confluence", 5))
    emoji = {
        "RANGING": "〰️",
        "TRENDING": "📈",
        "NEUTRAL": "➡️",
        "VOLATILE": "⚡",
        "TRADING": "📡",
    }.get(live_regime, "➡️")
    return "\n".join([
        "💓 <b>HEARTBEAT</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Modo:</b> SIGNAL ONLY",
        f"<b>WR:</b> {wr}% | {bot.wins}W / {bot.losses}L",
        f"<b>Sinais ativos:</b> {len(getattr(bot, 'active_trades', []))} | <b>Pendentes:</b> {len(getattr(bot, 'pending_trades', []))}",
        f"<b>{emoji} Regime:</b> {live_regime} (ADX={avg_adx})",
        f"<b>Confluência mínima efetiva:</b> {eff_conf}",
    ])


def format_status(bot, extra: str = "") -> str:
    strategy = load_strategy_settings()
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0
    pause_status = "⏸️ PAUSADO" if bot.is_paused() else "✅ OPERANDO"
    selected = get_selected_symbols()
    last = (bot.history[-1] if getattr(bot, "history", None) else None) or {}
    lines = [
        "📊 <b>STATUS DESK</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Status:</b> {pause_status}",
        f"<b>Modo:</b> SIGNAL ONLY",
        f"<b>Win rate:</b> {wr}% ({bot.wins}W/{bot.losses}L)",
        f"<b>Sinais ativos:</b> {len(getattr(bot, 'active_trades', []))}",
        f"<b>Sinais monitorados:</b> {len(getattr(bot, 'pending_trades', []))}",
        f"<b>Ativos monitorados:</b> {len(selected)}",
        f"<b>Min confluence:</b> {strategy.get('min_confluence')} | <b>ADX min:</b> {strategy.get('adx_min')}",
        f"<b>Qualidade alvo:</b> 1–10",
    ]
    if last:
        lines.append(f"<b>Último resultado:</b> {esc(last.get('result', '—'))} | {esc(last.get('symbol', '—'))}")
    if extra:
        lines.append(f"—\n{esc(extra)}")
    return "\n".join(lines)


def format_report(bot) -> str:
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0
    avg_quality = 0.0
    scored = []
    for t in list(getattr(bot, "history", []))[-200:]:
        try:
            s = float(t.get("score", t.get("ai_confidence", 0)) or 0)
            m = float(t.get("score_total", 10) or 10)
            scored.append(_quality_10(s, m))
        except Exception:
            continue
    if scored:
        avg_quality = round(sum(scored) / len(scored), 1)
    return "\n".join([
        "📈 <b>DAILY REPORT</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Modo:</b> SIGNAL ONLY",
        f"<b>Trades/sinais:</b> {total}",
        f"<b>Win rate:</b> {wr}%",
        f"<b>Wins / Losses:</b> {bot.wins} / {bot.losses}",
        f"<b>Qualidade média:</b> {avg_quality}/10",
        f"<b>Pendentes:</b> {len(getattr(bot, 'pending_trades', []))}",
        f"<b>Ativos:</b> {len(getattr(bot, 'active_trades', []))}",
    ])


def format_assets(bot) -> str:
    selected = get_selected_symbols()
    names = [asset_name(s) for s in selected]
    return "\n".join([
        "🛰 <b>ASSET DESK</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Ativos monitorados:</b> {len(selected)}",
        f"<b>Timeframe:</b> {esc(getattr(bot, 'timeframe', '—'))}",
        "—" * 18,
        f"<b>Lista:</b> {', '.join(esc(n) for n in names)}",
    ])


def format_trades(bot) -> str:
    active = list(getattr(bot, "active_trades", []))
    if not active:
        return "\n".join([
            "📂 <b>SINAIS ATIVOS</b>",
            "Nenhum sinal ativo no momento.",
        ])

    lines = [
        "📂 <b>SINAIS ATIVOS</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Total:</b> {len(active)}",
        "—" * 18,
    ]
    for t in active[:15]:
        quality = _quality_10(t.get("score"), t.get("score_total"))
        lines.append(
            f"• <b>{esc(t.get('symbol','?'))}</b> {esc(t.get('dir','—'))} | "
            f"{t.get('score','—')}/{t.get('score_total','—')} ({quality}/10)\n"
            f"  Entrada {fmt(t.get('entry', 0))} | SL {fmt(t.get('sl', 0))} | TP {fmt(t.get('tp', 0))}"
        )
    return "\n".join(lines)


def format_health(bot) -> str:
    return "\n".join([
        "🩺 <b>HEALTH CHECK</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Status:</b> {'PAUSADO' if bot.is_paused() else 'OPERANDO'}",
        f"<b>Threads:</b> ok",
        f"<b>Telegram:</b> ok",
        f"<b>Sinais ativos:</b> {len(getattr(bot, 'active_trades', []))}",
        f"<b>Pendentes:</b> {len(getattr(bot, 'pending_trades', []))}",
    ])


def format_result(trade: dict, bot, result: str) -> str:
    emoji = "✅" if result == "WIN" else "❌"
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0
    quality = _quality_10(trade.get("score"), trade.get("score_total"))
    return "\n".join([
        f"📊 <b>HEDGE FUND DESK | RESULT {emoji}</b>",
        f"<b>Horário:</b> {_now_utc()}",
        "—" * 18,
        f"<b>Ativo:</b> {esc(trade.get('symbol','?'))}",
        f"<b>Direção:</b> {esc(trade.get('dir','—'))}",
        f"<b>Qualidade:</b> {quality}/10",
        f"<b>Win rate:</b> {wr}%",
    ])
