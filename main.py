"""
main.py — Entrypoint do Sniper Bot (somente sinais).

Responsabilidades:
  • Carregar estado (state.json → memória do bot)
  • Disparar thread do loop principal
  • Subir API Flask (dashboard e endpoints)
  • Agendar heartbeat, relatório diário, aprendizado semanal e mensal
  • Processar comandos do Telegram (/executar_, /confluencia)

⚠️  Este bot é SINALIZADOR: ele NÃO executa ordens em corretora real.
    Todos os cálculos de saldo / P&L são simulados para fins de estatística.
"""

from __future__ import annotations

import os
import sys
import time
import threading
import traceback
from datetime import datetime, timezone
from typing import Any

import requests

from config import Config
from utils import log
from db import load_state, append_log, save_metrics, calculate_metrics
from bot import TradingBot
from signals import scan
from api import create_api

# Pandas .ewm() em séries longas pode aprofundar a pilha — aumenta o limite
sys.setrecursionlimit(5000)

# ============================================================================
# CONFIGURAÇÕES DE CICLO
# ============================================================================
HEARTBEAT_INTERVAL = 3600          # 1 h
DAILY_REPORT_HOUR = 21             # 21:00 UTC
WEEK_SECS = 7 * 24 * 3600
MONTH_SECS = 30 * 24 * 3600
NEAR_CHECK_INTERVAL = 600          # 10 min
STARTUP_NOTIFICATION = True


# ============================================================================
# HELPERS
# ============================================================================
def _safe_send(bot: TradingBot, message: str) -> None:
    """Envia mensagem sem derrubar o loop caso o canal falhe."""
    try:
        bot.send(message)
    except Exception:
        pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_dt_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d/%m %H:%M UTC")


def _parse_trade_time(trade: dict[str, Any], now_utc: datetime) -> datetime | None:
    """Tenta ler timestamp ISO ou fallback antigo do histórico."""
    iso_ts = trade.get("closed_ts_iso")
    if iso_ts:
        try:
            trade_time = datetime.fromisoformat(iso_ts)
            if trade_time.tzinfo is None:
                trade_time = trade_time.replace(tzinfo=timezone.utc)
            return trade_time.astimezone(timezone.utc)
        except Exception:
            return None

    closed_at = trade.get("closed_at", "")
    if closed_at:
        try:
            trade_time = datetime.strptime(closed_at, "%d/%m %H:%M")
            trade_time = trade_time.replace(year=now_utc.year, tzinfo=timezone.utc)
            return trade_time
        except Exception:
            return None

    return None


# ============================================================================
# NOTIFICAÇÕES
# ============================================================================
def send_startup_notification(bot: TradingBot) -> None:
    """Envia notificação de inicialização com resumo do estado."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0

    status = "⛔ Status: PAUSADO (circuit breaker)" if bot.is_paused() else "✅ Status: OPERANDO"
    lines = [
        "🚀 SNIPER BOT INICIADO",
        "------------------------------",
        f"💰 Saldo simulado: ${round(bot.balance, 2)}",
        f"📊 Win Rate: {wr}% ({bot.wins}W / {bot.losses}L)",
        f"📈 Trades ativos: {len(bot.active_trades)}",
        f"⏳ Pendentes: {len(bot.pending_trades)}",
        f"⚡ Alavancagem: {bot.get_current_leverage()}x",
        status,
        f"🕐 Iniciado: {_format_dt_utc(_utc_now())}",
    ]
    _safe_send(bot, "\n".join(lines))
    append_log("startup", {"balance": bot.balance, "winrate": wr})


def send_heartbeat(bot: TradingBot, regime_info: dict[str, Any] | None = None, ai_params: dict[str, Any] | None = None) -> None:
    """Heartbeat periódico confirmando que o bot está vivo, incluindo regime atual."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0.0

    regime_info = regime_info or {}
    ai_params = ai_params or {}

    live_regime = regime_info.get("live_regime", ai_params.get("live_regime", "neutral"))
    avg_adx = regime_info.get("avg_adx", ai_params.get("avg_adx", 0))
    eff_conf = regime_info.get("effective_conf", ai_params.get("live_confluence", Config.MIN_CONFLUENCE))

    emoji = {
        "ranging": "〰️",
        "trending": "📈",
        "neutral": "➡️",
        "volatile": "⚡",
    }.get(str(live_regime).lower(), "➡️")

    drawdown = bot.current_drawdown_pct() if hasattr(bot, "current_drawdown_pct") else 0.0
    lines = [
        "💓 HEARTBEAT — Bot operando",
        "------------------------------",
        f"💰 Saldo: ${round(bot.balance, 2)}",
        f"📉 Drawdown: {drawdown}%",
        f"📊 WR: {wr}% | {bot.wins}W / {bot.losses}L",
        f"📈 Ativos: {len(bot.active_trades)} | Pendentes: {len(bot.pending_trades)}",
        f"{emoji} Regime: {str(live_regime).upper()} (ADX={avg_adx})",
        f"🎯 Confluência mínima efetiva: {eff_conf} pts",
    ]
    _safe_send(bot, "\n".join(lines))
    append_log(
        "heartbeat",
        {
            "balance": bot.balance,
            "winrate": wr,
            "regime": live_regime,
            "drawdown_pct": drawdown,
        },
    )


def send_daily_report(bot: TradingBot) -> None:
    """Relatório diário de performance."""
    metrics = calculate_metrics(bot)
    now = _utc_now()

    day_pnl = 0.0
    day_trades = 0
    day_wins = 0
    day_losses = 0

    for trade in bot.history:
        try:
            trade_time = _parse_trade_time(trade, now)
            if trade_time and trade_time.date() == now.date():
                day_pnl += float(trade.get("pnl", 0) or 0)
                day_trades += 1
                if trade.get("result") == "WIN":
                    day_wins += 1
                else:
                    day_losses += 1
        except Exception:
            continue

    lines = [
        f"📊 RELATÓRIO DIÁRIO — {now.strftime('%d/%m/%Y')}",
        "------------------------------",
        "📈 Hoje:",
        f"   Trades: {day_trades} ({day_wins}W / {day_losses}L)",
        f"   P&L: ${round(day_pnl, 2)}",
        "",
        "💰 Geral:",
        f"   Saldo: ${round(bot.balance, 2)}",
        f"   Total trades: {metrics.get('total_trades', 0)}",
        f"   WR: {metrics.get('winrate', 0)}%",
        f"   Profit Factor: {metrics.get('profit_factor', 0)}",
        f"   Expectancy: ${metrics.get('expectancy', 0)}/trade",
        f"   Max Drawdown: {metrics.get('max_drawdown_pct', 0)}%",
    ]
    _safe_send(bot, "\n".join(lines))
    save_metrics(metrics)
    append_log("daily_report", metrics)


def send_error_notification(bot: TradingBot, error_msg: str, traceback_str: str = "") -> None:
    """Notificação de erro/crash — tolerante a falhas do próprio send."""
    lines = [
        "🚨 ERRO NO BOT",
        "------------------------------",
        f"❌ {error_msg[:200]}",
    ]
    if traceback_str:
        lines.append("")
        lines.append("📋 Traceback:")
        lines.append(traceback_str[:500])
    lines.append("")
    lines.append(f"🕐 {_format_dt_utc(_utc_now())}")

    try:
        bot.send("\n".join(lines))
    except Exception:
        pass

    append_log("error", {"message": error_msg, "traceback": traceback_str})


def _send_confluence_report(bot: TradingBot) -> None:
    """Resposta ao comando /confluencia no Telegram."""
    from signals import get_confluence_snapshot
    from ai_validator import load_ai_params
    from utils import get_allowed_symbols

    _safe_send(bot, "⏳ Calculando confluência...")

    try:
        snapshot = get_confluence_snapshot()
        ai_params = load_ai_params()
        min_conf = ai_params.get("live_confluence", Config.MIN_CONFLUENCE)
        live_regime = ai_params.get("live_regime", "neutral")
        allowed_symbols = get_allowed_symbols(bot.balance)

        lines: list[str] = [
            f"📊 CONFLUÊNCIA — {_utc_now().strftime('%d/%m %H:%M')} UTC",
            f"Regime: {str(live_regime).upper()} | Mínimo: {min_conf} pts",
            "────────────────────────────────",
        ]

        for item in snapshot:
            score = int(item.get("best_score", 0))
            total = int(item.get("total", 0))
            direc = item.get("best_dir", "?")
            sym = item.get("symbol", "?")
            filled = max(0, min(score, 10))
            empty = max(0, min(total, 10) - filled)
            bar = "🟢" * filled + "⚪" * empty
            h4 = "✅" if item.get("h4_aligned") else "❌"
            locked = sym not in allowed_symbols

            if locked:
                status = "🔒"
            elif score >= min_conf:
                status = "🔥 SINAL"
            elif score >= min_conf - 2:
                status = "⚡ QUASE"
            elif score >= min_conf - 4:
                status = "👀 WATCH"
            else:
                status = "💤"

            lines.extend(
                [
                    f"{status} {sym} {direc} {score}/{total}" + (" (bloqueado)" if locked else ""),
                    f"  {bar}",
                    f"  RSI:{item.get('rsi', '?')} ADX:{item.get('adx', '?')} H4:{h4}",
                ]
            )

        lines.append("────────────────────────────────")
        lines.append("🔒 = par bloqueado pelo tier de capital atual.")
        lines.append("Use /confluencia para atualizar.")
        _safe_send(bot, "\n".join(lines))
    except Exception as exc:
        _safe_send(bot, f"❌ Erro ao calcular confluência: {exc}")


# ============================================================================
# LOOP PRINCIPAL
# ============================================================================
def bot_loop(bot: TradingBot) -> None:
    last_heartbeat = 0.0
    last_daily_report: datetime.date | None = None
    last_weekly_learning = 0.0
    last_monthly_analysis = 0.0
    last_near_check = 0.0

    while True:
        now = _utc_now()

        # HEARTBEAT
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                from ai_validator import check_live_regime, load_ai_params

                regime_info = check_live_regime(bot)
                ai_params = load_ai_params()
                send_heartbeat(bot, regime_info, ai_params)
                last_heartbeat = time.time()
            except Exception as exc:
                log(f"[HEARTBEAT] Erro: {exc}")

        # RELATÓRIO DIÁRIO
        if now.hour == DAILY_REPORT_HOUR and last_daily_report != now.date():
            try:
                send_daily_report(bot)
                last_daily_report = now.date()
            except Exception as exc:
                log(f"[DAILY] Erro: {exc}")

        # APRENDIZADO SEMANAL (Gemini Flash — Layer 2)
        if time.time() - last_weekly_learning >= WEEK_SECS:
            try:
                from ai_validator import weekly_learning

                result = weekly_learning(bot)
                if result:
                    suggestion = result.get("last_suggestion", "")
                    blocked_pairs = result.get("blocked_pairs", []) or []
                    lines = [
                        "🧠 APRENDIZADO SEMANAL",
                        "────────────────────────────────",
                        str(suggestion),
                        "",
                        f"Min confluence: {result.get('min_confluence', '?')} | Min ADX: {result.get('min_adx', '?')} | Min RR: {result.get('min_rr', '?')}",
                        f"Pares bloqueados: {', '.join(blocked_pairs) if blocked_pairs else 'nenhum'}",
                    ]
                    _safe_send(bot, "\n".join(lines))
                last_weekly_learning = time.time()
            except Exception as exc:
                log(f"[LAYER2] Erro no aprendizado semanal: {exc}")

        # ANÁLISE MENSAL (Gemini Flash — Layer 3)
        if time.time() - last_monthly_analysis >= MONTH_SECS:
            try:
                from ai_validator import monthly_deep_analysis

                result = monthly_deep_analysis(bot)
                if result:
                    regime_pairs = result.get("regime_pairs", {}) or {}
                    regime_txt = " | ".join(f"{k}:{v}" for k, v in regime_pairs.items()) or "—"
                    favored_sessions = result.get("favored_sessions", []) or []
                    avoid_hours = result.get("avoid_hours_utc", []) or []
                    lines = [
                        "🔮 ANÁLISE MENSAL (Estratégica)",
                        "────────────────────────────────",
                        str(result.get("opus_summary", "")),
                        "",
                        f"Regime: {str(result.get('market_regime', '?')).upper()} | Viés: {str(result.get('strategy_bias', '?')).upper()}",
                        f"Sessões favoritas: {', '.join(favored_sessions) if favored_sessions else '—'}",
                        f"Horas a evitar (UTC): {avoid_hours if avoid_hours else 'nenhuma'}",
                        "",
                        f"Por par: {regime_txt}",
                    ]
                    _safe_send(bot, "\n".join(lines))
                last_monthly_analysis = time.time()
            except Exception as exc:
                log(f"[LAYER3] Erro na análise mensal: {exc}")

        # SCAN / MONITOR
        if not bot.is_paused():
            try:
                bot.expire_pending_signals(max_age_seconds=Config.PENDING_EXPIRY_SECONDS)
                scan(bot)
                bot.monitor_trades()

                if time.time() - last_near_check >= NEAR_CHECK_INTERVAL:
                    from signals import check_near_signals

                    check_near_signals(bot)
                    last_near_check = time.time()
            except Exception as exc:
                error_msg = str(exc)
                tb = traceback.format_exc()
                log(f"Erro no loop: {error_msg}")
                send_error_notification(bot, error_msg, tb)
                append_log("loop_error", {"error": error_msg})

        # COMANDOS TELEGRAM
        if Config.BOT_TOKEN and Config.CHAT_ID:
            try:
                url = (
                    f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                    f"/getUpdates?offset={bot.last_id + 1}&timeout=5"
                )
                resp = requests.get(url, timeout=10).json()
                results = resp.get("result", []) if isinstance(resp, dict) else []

                for update in results:
                    message = update.get("message", {}) if isinstance(update, dict) else {}
                    text = str(message.get("text", "")).strip()

                    if text.startswith("/executar_"):
                        parts = text.split("_")
                        if len(parts) >= 3:
                            try:
                                pending_id = int(parts[1])
                                amount = float(parts[2])
                                bot.execute_pending(pending_id, amount)
                            except ValueError:
                                _safe_send(bot, "❌ Formato inválido. Use /executar_<id>_<valor>")

                    elif text in ("/confluencia", "/confluência"):
                        _send_confluence_report(bot)

                    elif text == "/status":
                        send_heartbeat(bot)

                    bot.last_id = int(update.get("update_id", bot.last_id))
            except Exception:
                pass

        time.sleep(Config.SCAN_INTERVAL)


# ============================================================================
# ENTRYPOINT
# ============================================================================
def main() -> None:
    log("Iniciando Sniper Bot v2 (Forex + Gold H1 — modo sinalizador)")
    bot = TradingBot()

    # 1. Carrega estado persistido
    state_loaded = load_state(bot)

    # 2. Força refresh inicial dos dados de mercado antes do primeiro scan
    try:
        from analysis import force_initial_refresh

        log("Executando refresh inicial de mercado (Twelve Data)...")
        force_initial_refresh()
    except Exception as exc:
        log(f"[INIT] Falha no refresh inicial: {exc}")

    # 3. Notificação de startup
    if STARTUP_NOTIFICATION:
        try:
            send_startup_notification(bot)
        except Exception as exc:
            log(f"[STARTUP] Erro ao enviar notificação: {exc}")

    append_log(
        "init",
        {
            "balance": bot.balance,
            "state_loaded": state_loaded,
            "leverage": bot.get_current_leverage(),
            "signal_only": Config.BOT_IS_SIGNAL_ONLY,
        },
    )

    # 4. Sobe thread do loop principal
    threading.Thread(target=bot_loop, args=(bot,), daemon=True).start()

    # 5. Sobe API Flask
    app = create_api(bot)
    port = int(os.environ.get("PORT", 8080))
    log(f"API HTTP escutando em 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
