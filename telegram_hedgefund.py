
"""
telegram_hedgefund.py — camada Telegram institucional para o Sniper Bot.
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from config import Config
from utils import (
    asset_name,
    fmt,
    get_allowed_symbols,
    get_dynamic_max_trades,
    get_selected_symbols,
    load_strategy_settings,
    load_trade_settings,
)

TG_LIMIT = 3900


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def _trim(text: str, limit: int = TG_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 20)] + "\n… (mensagem truncada)"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def _format_money(v) -> str:
    try:
        v = float(v)
    except Exception:
        return str(v)
    sign = "+" if v >= 0 else ""
    return f"{sign}${v:,.2f}"


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

    def _post(self, method: str, payload: dict):
        try:
            return requests.post(f"{self.base}/{method}", json=payload, timeout=10)
        except Exception:
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
        params = {"timeout": 1, "offset": self.state.offset}
        try:
            resp = requests.get(f"{self.base}/getUpdates", params=params, timeout=3)
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

    def push_confluence(self, bot):
        try:
            from signals import get_confluence_snapshot
        except Exception as e:
            self.send(f"⚠️ <b>Confluence Desk</b>\nFalha ao carregar snapshot: {esc(e)}")
            return

        try:
            snapshot = get_confluence_snapshot()
            strategy = load_strategy_settings()
            allowed = set(get_allowed_symbols(bot.balance))
            lines = [
                "🧭 <b>CONFLUENCE DESK</b>",
                f"<b>Horário:</b> {_now_utc()}",
                f"<b>Min score atual:</b> {strategy.get('min_confluence', 5)}",
                f"<b>Ativos liberados:</b> {len(allowed)}",
                "—" * 18,
            ]
            for item in snapshot[:12]:
                sym = item.get("symbol", "?")
                score = int(item.get("best_score", 0) or 0)
                total = int(item.get("total", 0) or 0)
                direction = item.get("best_dir", "—")
                h4 = "✅" if item.get("h4_aligned") else "❌"
                locked = sym not in allowed
                bar = "🟩" * min(score, 10) + "⬜" * max(0, min(total, 10) - score)
                status = "🔒" if locked else ("🔥" if score >= strategy.get("min_confluence", 5) else "👀")
                lines.append(
                    f"{status} <b>{esc(sym)}</b> {esc(direction)} <b>{score}/{total}</b> H4:{h4}\n"
                    f"<code>{bar or '—'}</code>"
                )
            self.send("\n".join(lines), reply_markup=keyboard_markup())
        except Exception as e:
            self.send(f"⚠️ <b>Confluence Desk</b>\nErro: {esc(e)}")

    def push_assets(self, bot):
        allowed = get_allowed_symbols(bot.balance)
        selected = get_selected_symbols()
        strategy = load_strategy_settings()
        lines = [
            "🛰 <b>ASSET DESK</b>",
            f"<b>Portfólio liberado:</b> {len(allowed)} ativo(s)",
            f"<b>Selecionados no bot:</b> {len(selected)}",
            f"<b>Teto de trades:</b> {get_dynamic_max_trades(bot.balance)}",
            "—" * 18,
            "<b>Lista:</b> " + ", ".join(esc(asset_name(s)) for s in allowed[:20]),
            f"<b>Perfil:</b> {esc(strategy.get('profile', 'hedge_fund'))}",
        ]
        self.send("\n".join(lines), reply_markup=keyboard_markup())

    def push_trades(self, bot):
        active = list(getattr(bot, "active_trades", []))
        if not active:
            self.send("📂 <b>OPEN TRADES</b>\nNenhuma operação ativa no momento.", reply_markup=keyboard_markup())
            return

        lines = [
            "📂 <b>OPEN TRADES</b>",
            f"<b>Saldo:</b> {_format_money(bot.balance)}",
            f"<b>Ativas:</b> {len(active)}",
            "—" * 18,
        ]
        for t in active[:10]:
            lines.append(
                f"• <b>{esc(t.get('symbol','?'))}</b> {esc(t.get('dir','—'))} | "
                f"lot {t.get('lot','—')} | entry {fmt(t.get('entry', 0))} | "
                f"SL {fmt(t.get('sl', 0))} | TP {fmt(t.get('tp', 0))}"
            )
        self.send("\n".join(lines), reply_markup=keyboard_markup())

    def poll_commands(self, bot, on_confluence=None):
        executed = []
        if time.time() - self.state.last_poll_ts < self.state.poll_interval:
            return executed
        self.state.last_poll_ts = time.time()

        data = self.get_updates()
        if not data.get("ok"):
            return executed

        for upd in data.get("result", []):
            try:
                uid = int(upd.get("update_id", 0))
                self.state.offset = max(self.state.offset, uid + 1)

                text = ""
                if "message" in upd and upd["message"]:
                    text = str(upd["message"].get("text", "") or "").strip()
                elif "edited_message" in upd and upd["edited_message"]:
                    text = str(upd["edited_message"].get("text", "") or "").strip()

                if not text:
                    continue

                txt = text.lower()
                executed.append(txt.split()[0])

                if txt.startswith("/start") or txt.startswith("/help"):
                    self.send(
                        "🤖 <b>SNIPER BOT | HEDGE FUND DESK</b>\n"
                        "Comandos disponíveis:\n"
                        "• /status — visão geral\n"
                        "• /report — relatório consolidado\n"
                        "• /confluencia — força dos setups\n"
                        "• /trades — operações ativas\n"
                        "• /assets — ativos liberados\n"
                        "• /pause [min] — pausa temporária\n"
                        "• /resume — retoma o bot\n\n"
                        "Use os botões abaixo para acesso rápido.",
                        reply_markup=keyboard_markup(),
                    )

                elif txt.startswith("/status"):
                    self.push_status(bot)

                elif txt.startswith("/report"):
                    self.push_report(bot)

                elif txt.startswith("/confluencia") or txt.startswith("/confluência"):
                    if on_confluence:
                        on_confluence(bot)
                    else:
                        self.push_confluence(bot)

                elif txt.startswith("/assets"):
                    self.push_assets(bot)

                elif txt.startswith("/trades"):
                    self.push_trades(bot)

                elif txt.startswith("/pause"):
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

                elif txt.startswith("/resume"):
                    if hasattr(bot, "resume"):
                        bot.resume()
                    else:
                        bot.paused_until = 0.0
                    self.send("▶️ <b>Bot retomado</b>\nModo operacional ativado.", reply_markup=keyboard_markup())

                elif txt.startswith("/mode"):
                    strategy = load_strategy_settings()
                    self.send(
                        "🧠 <b>STRATEGY MODE</b>\n"
                        f"<b>Profile:</b> {esc(strategy.get('profile', 'hedge_fund'))}\n"
                        f"<b>Min confluence:</b> {strategy.get('min_confluence')}\n"
                        f"<b>ADX min:</b> {strategy.get('adx_min')}\n"
                        f"<b>RR mínimo:</b> {strategy.get('min_rr')}\n"
                        f"<b>Weekly target:</b> {strategy.get('weekly_trade_target')} trade(s)",
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
        f"<b>Saldo simulado:</b> {_format_money(bot.balance)}",
        f"<b>Win rate:</b> {wr}% ({bot.wins}W / {bot.losses}L)",
        f"<b>Trades ativos:</b> {len(bot.active_trades)}",
        f"<b>Leverage:</b> {bot.get_current_leverage()}x",
        "—" * 18,
        f"<b>Profile:</b> {esc(strategy.get('profile', 'hedge_fund'))}",
        f"<b>Min confluence:</b> {strategy.get('min_confluence')}",
        f"<b>ADX min:</b> {strategy.get('adx_min')}",
        f"<b>Risk %:</b> {strategy.get('risk_pct')}",
        f"<b>Weekly target:</b> {strategy.get('weekly_trade_target')}",
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
        f"<b>Saldo:</b> {_format_money(bot.balance)}",
        f"<b>WR:</b> {wr}% | {bot.wins}W / {bot.losses}L",
        f"<b>Ativos:</b> {len(bot.active_trades)} | <b>Pendentes:</b> {len(bot.pending_trades)}",
        f"<b>{emoji} Regime:</b> {live_regime} (ADX={avg_adx})",
        f"<b>Confluência mínima efetiva:</b> {eff_conf}",
    ])


def format_status(bot, extra: str = "") -> str:
    strategy = load_strategy_settings()
    trade_settings = load_trade_settings()
    allowed = get_allowed_symbols(bot.balance)
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0
    pause_status = "⏸️ PAUSADO" if bot.is_paused() else "✅ OPERANDO"
    lines = [
        "📊 <b>STATUS DESK</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Status:</b> {pause_status}",
        f"<b>Saldo:</b> {_format_money(bot.balance)}",
        f"<b>Win rate:</b> {wr}% ({bot.wins}W/{bot.losses}L)",
        f"<b>Trades ativos:</b> {len(bot.active_trades)}",
        f"<b>Max ativos:</b> {get_dynamic_max_trades(bot.balance)}",
        f"<b>Ativos liberados:</b> {len(allowed)}",
        f"<b>Min confluence:</b> {strategy.get('min_confluence')} | <b>ADX min:</b> {strategy.get('adx_min')}",
        f"<b>Risk %:</b> {strategy.get('risk_pct')} | <b>Weekly target:</b> {strategy.get('weekly_trade_target')}",
    ]
    if trade_settings.get("max_active_trades") is not None:
        lines.append(f"<b>Override max trades:</b> {trade_settings['max_active_trades']}")
    if extra:
        lines.append(f"—\n{esc(extra)}")
    return "\n".join(lines)


def format_report(bot) -> str:
    from performance import calculate_metrics_from_history

    metrics = calculate_metrics_from_history(
        bot.history,
        initial_balance=Config.INITIAL_BALANCE,
        current_balance=bot.balance,
        active_trades_count=len(bot.active_trades),
        pending_trades_count=len(bot.pending_trades),
    )
    total = metrics.get("total_trades", 0) or 0
    wr = metrics.get("winrate", 0)
    pf = metrics.get("profit_factor", 0)
    dd = metrics.get("max_drawdown_pct", 0)
    return "\n".join([
        "📈 <b>DAILY / CONSOLIDATED REPORT</b>",
        f"<b>Horário:</b> {_now_utc()}",
        f"<b>Saldo:</b> {_format_money(bot.balance)}",
        f"<b>Trades:</b> {total}",
        f"<b>Win rate:</b> {wr}%",
        f"<b>Profit factor:</b> {pf}",
        f"<b>Expectancy:</b> {_format_money(metrics.get('expectancy', 0))}",
        f"<b>Max DD:</b> {dd}%",
        f"<b>P&L total:</b> {_format_money(metrics.get('total_pnl', 0))}",
    ])


def format_signal(trade: dict, bot=None) -> str:
    strategy = load_strategy_settings()
    direction = str(trade.get("dir", "—"))
    icon = "🟢" if direction == "BUY" else "🔴"
    rr = trade.get("rr")
    if not rr:
        try:
            rr = round(float(trade.get("tp_pips", 0)) / max(0.000001, float(trade.get("sl_pips", 1))), 2)
        except Exception:
            rr = "—"

    lines = [
        "📡 <b>HEDGE FUND DESK | SIGNAL</b>",
        f"<b>Horário:</b> {_now_utc()}",
        "—" * 18,
        f"<b>Ativo:</b> {esc(trade.get('symbol','?'))} ({esc(trade.get('name', trade.get('symbol','?')))})",
        f"<b>Direção:</b> {icon} {esc(direction)}",
        f"<b>Timeframe:</b> {esc(trade.get('timeframe', getattr(bot, 'timeframe', '—')))}",
        f"<b>Entrada:</b> {fmt(trade.get('entry', 0))}",
        f"<b>Stop:</b> {fmt(trade.get('sl', 0))}",
        f"<b>Take:</b> {fmt(trade.get('tp', 0))}",
        f"<b>RR:</b> 1:{rr} | <b>Score:</b> {trade.get('score', '—')}/{trade.get('max_score', '—')}",
        f"<b>Regime:</b> {esc(str(trade.get('market_regime', 'neutral')).upper())} | <b>Setup:</b> {esc(str(trade.get('setup_type', '—')).upper())}",
        f"<b>Kill zone:</b> {esc(trade.get('kill_zone', '—') or '—')}",
        f"<b>Daily bias:</b> {esc(trade.get('daily_bias', 'NEUTRO'))}",
        f"<b>OTE:</b> {'✅' if trade.get('ote_active') else '⬜'}",
        f"<b>Risk:</b> {_format_money(trade.get('suggested_risk_usd', 0))} ({trade.get('suggested_risk_pct', 0)}%)",
        f"<b>Lote:</b> {esc(trade.get('lot','—'))}",
        f"<b>IA:</b> {trade.get('ai_confidence', 0)}/10",
    ]
    checks = trade.get("checks") or []
    if checks:
        lines.append("—" * 18)
        lines.append("<b>Checklist:</b>")
        for c in checks[:12]:
            ok = "✅" if c.get("ok") else "❌"
            lines.append(f"{ok} {esc(c.get('name',''))}")
    lines.append("—" * 18)
    lines.append("<b>Monitorando SL/TP automaticamente</b>")
    return "\n".join(lines)


def format_result(trade: dict, bot, result: str) -> str:
    emoji = "✅" if result == "WIN" else "❌"
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0
    return "\n".join([
        f"📊 <b>HEDGE FUND DESK | RESULT {emoji}</b>",
        f"<b>Horário:</b> {_now_utc()}",
        "—" * 18,
        f"<b>Ativo:</b> {esc(trade.get('symbol','?'))}",
        f"<b>Direção:</b> {esc(trade.get('dir','—'))}",
        f"<b>P&L:</b> {_format_money(trade.get('pnl', 0))}",
        f"<b>Saldo:</b> {_format_money(bot.balance)}",
        f"<b>Win rate:</b> {wr}% ({bot.wins}W/{bot.losses}L)",
        f"<b>Margem liberada:</b> {_format_money(trade.get('margin_required', 0))}",
        f"<b>IA:</b> {trade.get('ai_confidence', 0)}/10",
    ])
