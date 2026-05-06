
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

    def download_file(self, file_id: str) -> bytes | None:
        """Baixa um arquivo do Telegram pelo file_id e retorna os bytes."""
        resp = self._get("getFile", params={"file_id": file_id})
        if resp is None:
            return None
        data = resp.json()
        if not data.get("ok"):
            return None
        file_path = data["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception:
            return None


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

                # ── Detecção de arquivo CSV enviado pelo usuário ───────────────
                msg = upd.get("message", {})
                doc = msg.get("document")
                if doc:
                    fname = doc.get("file_name", "")
                    if fname.lower().endswith(".csv"):
                        file_id = doc.get("file_id")
                        # Lê o símbolo da caption (ex: "EURUSD") ou usa padrão
                        caption = str(msg.get("caption", "") or "").strip().upper()
                        # Caption: "optimize EURUSD" → otimizador | qualquer outra → backtest
                        caption_parts = caption.split()
                        is_optimize   = caption_parts and caption_parts[0] == "OPTIMIZE"
                        if is_optimize:
                            symbol = caption_parts[1] if len(caption_parts) > 1 else "EURUSD"
                        else:
                            symbol = caption if caption else "EURUSD"

                        self.send(
                            f"📂 <b>CSV recebido:</b> {fname}\n"
                            + (f"🔬 Iniciando otimização para <b>{symbol}</b> (2 304 combinações)...\n⏳ Aguarde ~30 segundos."
                               if is_optimize else
                               f"⏳ Rodando backtest para <b>{symbol}</b>..."),
                            reply_markup=keyboard_markup(),
                        )
                        try:
                            content = self.download_file(file_id)
                            if not content:
                                self.send("❌ Não foi possível baixar o arquivo.", reply_markup=keyboard_markup())
                            else:
                                import tempfile, os
                                with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                                    tmp.write(content)
                                    tmp_path = tmp.name
                                try:
                                    from backtester import load_bars_from_csv
                                    from config import Config
                                    bars = load_bars_from_csv(tmp_path)
                                    if len(bars) < 60:
                                        self.send(
                                            f"⚠️ CSV com apenas {len(bars)} candles. Mínimo recomendado: 60.",
                                            reply_markup=keyboard_markup(),
                                        )
                                    elif is_optimize:
                                        from optimizer import run_grid
                                        top = run_grid(bars, symbol=symbol, initial_balance=Config.INITIAL_BALANCE)
                                        self.send(_format_optimize_result(symbol, top, len(bars)), reply_markup=keyboard_markup())
                                    else:
                                        from backtester import run_backtest
                                        r = run_backtest(bars, symbol=symbol, initial_balance=Config.INITIAL_BALANCE)
                                        self.send(_format_backtest_result(symbol, r, len(bars)), reply_markup=keyboard_markup())
                                finally:
                                    try:
                                        os.unlink(tmp_path)
                                    except Exception:
                                        pass
                        except Exception as exc:
                            self.send(f"❌ Erro ao processar CSV: {exc}", reply_markup=keyboard_markup())
                    else:
                        self.send(
                            "⚠️ <b>Formato não suportado.</b>\nEnvie um arquivo <b>.csv</b> com candles OHLC.\n"
                            "Fontes: Investing.com, Histdata.com ou MetaTrader.",
                            reply_markup=keyboard_markup(),
                        )
                    continue

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
                        "• /mode — modo e parâmetros\n"
                        "• /backtest [PAR] — backtest do par (ex: /backtest EURUSD)\n"
                        "• /optimize — otimiza parâmetros via CSV (envie o CSV com caption \"optimize EURUSD\")\n\n"
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

                elif cmd == "/backtest":
                    parts = text.split()
                    symbol = parts[1].upper() if len(parts) > 1 else "EURUSD"
                    self.send(f"⏳ <b>Rodando backtest para {symbol}...</b>\nAguarde alguns segundos.", reply_markup=keyboard_markup())
                    try:
                        result_msg = _run_backtest_telegram(symbol)
                    except Exception as exc:
                        result_msg = f"❌ Erro no backtest: {exc}"
                    self.send(result_msg, reply_markup=keyboard_markup())

                elif cmd == "/optimize":
                    self.send(
                        "🔬 <b>OTIMIZADOR DE PARÂMETROS</b>\n"
                        "Envia o CSV com a caption <b>optimize EURUSD</b> (ou outro par).\n\n"
                        "<b>Exemplo de uso:</b>\n"
                        "1. Selecione seu arquivo CSV\n"
                        "2. Na caption/legenda escreva: <code>optimize EURUSD</code>\n"
                        "3. Envie — o bot testa 2 304 combinações e retorna o ranking\n\n"
                        "⏳ Tempo estimado: 30–60 segundos.",
                        reply_markup=keyboard_markup(),
                    )

                else:
                    self.send(
                        "Comando não reconhecido. Use /help para ver os comandos disponíveis.",
                        reply_markup=keyboard_markup(),
                    )
            except Exception:
                continue
        return executed


def _format_backtest_result(symbol: str, r, total_bars: int) -> str:
    """Formata o resultado do backtest para mensagem Telegram."""
    m = r.metrics
    tf = r.params.get("timeframe", "H1")

    total  = int(m.get("total_trades", 0))
    wins   = int(m.get("wins", 0))
    losses = int(m.get("losses", 0))
    wr     = float(m.get("winrate", 0))
    pf     = float(m.get("profit_factor", 0))
    dd     = float(m.get("max_drawdown_pct", 0))
    sharpe = float(m.get("sharpe_ratio", 0))
    pnl    = float(m.get("total_pnl", 0))
    freq   = float(m.get("trade_frequency_per_week", 0))

    def _icon(val, good, great):
        if val >= great: return "🏆"
        if val >= good:  return "✅"
        return "⚠️"

    period = f"~{total_bars//24}d" if tf == "H1" else f"{total_bars} barras"

    from config import Config
    lines = [
        f"📊 <b>BACKTEST — {symbol} · {tf}</b>",
        f"<b>Período:</b> {period} ({total_bars} candles)",
        f"<b>Saldo inicial:</b> ${Config.INITIAL_BALANCE:,.2f}",
        "—" * 20,
        f"{'✅' if pnl > 0 else '❌'} <b>P&amp;L:</b> ${pnl:+,.2f}",
        f"{_icon(wr, 45, 55)} <b>Win Rate:</b> {wr:.1f}%  ({wins}W / {losses}L / {total} trades)",
        f"{_icon(pf, 1.5, 2.0)} <b>Profit Factor:</b> {pf:.2f}",
        f"{'🏆' if dd < 10 else ('✅' if dd < 20 else '⚠️')} <b>Max Drawdown:</b> {dd:.1f}%",
        f"{_icon(sharpe, 1.0, 2.0)} <b>Sharpe Ratio:</b> {sharpe:.2f}",
        f"📅 <b>Trades/semana:</b> {freq:.1f}",
        "—" * 20,
    ]
    if pf >= 1.5 and wr >= 45 and dd < 20:
        lines.append("🏆 <b>Veredicto:</b> Estratégia SÓLIDA para este período.")
    elif pf >= 1.2 and wr >= 40:
        lines.append("✅ <b>Veredicto:</b> Estratégia ACEITÁVEL. Monitore o drawdown.")
    else:
        lines.append("⚠️ <b>Veredicto:</b> Resultado FRACO. Ajuste os parâmetros.")
    return "\n".join(lines)


def _format_optimize_result(symbol: str, top: list[dict], total_bars: int) -> str:
    """Formata o ranking de otimização para o Telegram."""
    if not top:
        return f"❌ <b>Otimização falhou</b> — nenhuma configuração gerou trades suficientes."

    best = top[0]
    lines = [
        f"🔬 <b>OTIMIZAÇÃO — {esc(symbol)}</b>",
        f"<b>Dados:</b> {total_bars:,} candles  |  2 304 combinações testadas",
        "—" * 20,
        "🥇 <b>MELHOR CONFIGURAÇÃO:</b>",
        f"  • Confluence mín.: <b>{best['min_confluence']}</b>",
        f"  • ADX mín.: <b>{best['adx_min']:.0f}</b>",
        f"  • SL multiplicador: <b>{best['atr_sl_mult']}×</b>",
        f"  • TP multiplicador: <b>{best['atr_tp_mult']}×</b>",
        f"  • Risco por trade: <b>{best['risk_pct']:.0f}%</b>",
        f"  • Trades/semana alvo: <b>{best['weekly_trade_target']:.0f}</b>",
        "—" * 20,
        f"📊 <b>Resultado da config #1:</b>",
        f"  Trades: {best['n_trades']}  |  WR: {best['win_rate']:.1f}%",
        f"  PF: {best['profit_factor']:.2f}  |  DD: {best['max_drawdown']:.1f}%",
        f"  Sharpe: {best['sharpe']:.2f}  |  P&amp;L: ${best['pnl']:+.2f}",
        "—" * 20,
    ]

    if len(top) > 1:
        lines.append("📋 <b>TOP 5 CONFIGS:</b>")
        for i, r in enumerate(top[:5], 1):
            wr_tag  = "✅" if r["win_rate"]      >= 50  else "⚠️"
            pf_tag  = "✅" if r["profit_factor"]  >= 1.5 else "⚠️"
            lines.append(
                f"  <b>#{i}</b>  Conf={r['min_confluence']} ADX={r['adx_min']:.0f} "
                f"SL={r['atr_sl_mult']}× TP={r['atr_tp_mult']}× Risk={r['risk_pct']:.0f}% "
                f"| {wr_tag}{r['win_rate']:.0f}% {pf_tag}PF {r['profit_factor']:.2f} "
                f"DD {r['max_drawdown']:.0f}% P&amp;L ${r['pnl']:+.0f}"
            )

    lines += [
        "—" * 20,
        "💡 <b>Para aplicar:</b> edite <code>strategy_settings.json</code> com os valores acima.",
    ]
    return "\n".join(lines)


def _run_backtest_telegram(symbol: str) -> str:
    """Executa backtest usando os dados em cache e retorna mensagem formatada."""
    from analysis import _cache, _cache_lock
    from backtester import bars_from_dicts, run_backtest
    from config import Config

    with _cache_lock:
        entry = _cache.get(symbol)

    if entry is None:
        return (
            f"❌ <b>Sem dados em cache para {symbol}</b>\n"
            "Aguarde o bot iniciar o feed ou verifique se o par está na lista monitorada.\n"
            "Use /assets para ver os pares disponíveis.\n\n"
            "💡 <b>Dica:</b> Para backtest com dados históricos longos, envie um arquivo <b>.csv</b> "
            "diretamente neste chat (com a legenda sendo o par, ex: EURUSD)."
        )

    _, df = entry
    if df is None or df.empty:
        return f"❌ <b>DataFrame vazio para {symbol}.</b> Tente novamente em alguns minutos."

    records = [
        {"timestamp": ts, "open": float(row["Open"]), "high": float(row["High"]),
         "low": float(row["Low"]), "close": float(row["Close"])}
        for ts, row in df.iterrows()
    ]
    bars = bars_from_dicts(records)
    if len(bars) < 60:
        return (
            f"⚠️ <b>Dados insuficientes para {symbol}</b>\n"
            f"Apenas {len(bars)} candles em cache. Mínimo recomendado: 60.\n\n"
            "💡 <b>Dica:</b> Envie um <b>.csv</b> com histórico longo diretamente neste chat."
        )

    r = run_backtest(bars, symbol=symbol, initial_balance=Config.INITIAL_BALANCE)
    return _format_backtest_result(symbol, r, len(bars)) + "\n\n<i>⚡ Dados: cache do feed (~800 candles H1 ≈ 33 dias)</i>"



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
