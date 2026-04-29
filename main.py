
"""
main.py \u2014 Entrypoint do Sniper Bot (somente sinais).

Responsabilidades:
  \u2022 Carregar estado (state.json \u2192 mem\u00f3ria do bot)
  \u2022 Disparar thread do loop principal
  \u2022 Subir API Flask (dashboard e endpoints)
  \u2022 Agendar heartbeat, relat\u00f3rio di\u00e1rio, aprendizado semanal e mensal
  \u2022 Processar comandos do Telegram (/executar_, /confluencia)

\u26a0\ufe0f  Este bot \u00e9 SINALIZADOR: ele N\u00c3O executa ordens em corretora real.
    Todos os c\u00e1lculos de saldo / P&L s\u00e3o simulados para fins de estat\u00edstica.
"""

import sys
import time
import threading
import traceback
import os
from datetime import datetime, timezone

import requests

from config import Config
from utils import log
from db import load_state, append_log, save_metrics, calculate_metrics
from bot import TradingBot
from signals import scan
from api import create_api

# Pandas .ewm() em s\u00e9ries longas pode aprofundar a pilha \u2014 aumenta o limite
sys.setrecursionlimit(5000)

# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# CONFIGURA\u00c7\u00d5ES DE CICLO
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
HEARTBEAT_INTERVAL  = 3600          # 1 h
DAILY_REPORT_HOUR   = 21            # 21:00 UTC
WEEK_SECS           = 7  * 24 * 3600
MONTH_SECS          = 30 * 24 * 3600
NEAR_CHECK_INTERVAL = 600           # 10 min
STARTUP_NOTIFICATION = True


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# NOTIFICA\u00c7\u00d5ES
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def send_startup_notification(bot):
    """Envia notifica\u00e7\u00e3o de inicializa\u00e7\u00e3o com resumo do estado."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0

    msg = (
        "\ud83d\ude80 SNIPER BOT INICIADO\
"
        "------------------------------\
"
        f"\ud83d\udcb0 Saldo simulado: ${round(bot.balance, 2)}\
"
        f"\ud83d\udcca Win Rate: {wr}% ({bot.wins}W / {bot.losses}L)\
"
        f"\ud83d\udcc8 Trades ativos: {len(bot.active_trades)}\
"
        f"\u23f3 Pendentes: {len(bot.pending_trades)}\
"
        f"\u26a1 Alavancagem: {bot.get_current_leverage()}x\
"
    )
    msg += "\u26d4 Status: PAUSADO (circuit breaker)\
" if bot.is_paused() else "\u2705 Status: OPERANDO\
"
    msg += f"\ud83d\udd50 Iniciado: {datetime.now().strftime('%d/%m %H:%M UTC')}"

    bot.send(msg)
    append_log("startup", {"balance": bot.balance, "winrate": wr})


def send_heartbeat(bot, regime_info: dict | None = None, ai_params: dict | None = None):
    """Heartbeat periódico confirmando que o bot está vivo, incluindo regime atual."""
    total = bot.wins + bot.losses
    wr    = round(bot.wins / total * 100, 1) if total > 0 else 0

    regime_info = regime_info or {}
    live_regime = regime_info.get("live_regime", "neutral")
    avg_adx     = regime_info.get("avg_adx", 0)
    eff_conf    = regime_info.get("effective_conf", Config.MIN_CONFLUENCE)

    emoji = {
        "ranging":  "〰️",
        "trending": "📈",
        "neutral":  "➡️",
        "volatile": "⚡",
    }.get(live_regime, "➡️")

    drawdown = bot.current_drawdown_pct() if hasattr(bot, "current_drawdown_pct") else 0.0
    bot.send(
        "💓 HEARTBEAT — Bot operando"
        "------------------------------"
        f"💰 Saldo: ${round(bot.balance, 2)}"
        f"📉 Drawdown: {drawdown}%"
        f"📊 WR: {wr}% | {bot.wins}W / {bot.losses}L"
        f"📈 Ativos: {len(bot.active_trades)} | Pendentes: {len(bot.pending_trades)}"
        f"{emoji} Regime: {live_regime.upper()} (ADX={avg_adx})"
        f"🎯 Confluência mínima efetiva: {eff_conf} pts"
    )
    append_log("heartbeat", {"balance": bot.balance, "winrate": wr, "regime": live_regime, "drawdown_pct": drawdown})


def send_daily_report(bot):
    """Relat\u00f3rio di\u00e1rio de performance."""
    metrics = calculate_metrics(bot)

    now = datetime.now(timezone.utc)
    day_pnl = 0.0
    day_trades = 0
    day_wins = 0
    day_losses = 0

    for h in bot.history:
        try:
            trade_time = None
            iso_ts = h.get("closed_ts_iso")
            if iso_ts:
                trade_time = datetime.fromisoformat(iso_ts)
                if trade_time.tzinfo is None:
                    trade_time = trade_time.replace(tzinfo=timezone.utc)
                trade_time = trade_time.astimezone(timezone.utc)
            else:
                trade_time = datetime.strptime(h.get("closed_at", ""), "%d/%m %H:%M").replace(year=now.year, tzinfo=timezone.utc)

            if trade_time.date() == now.date():
                day_pnl += h.get("pnl", 0)
                day_trades += 1
                if h.get("result") == "WIN":
                    day_wins += 1
                else:
                    day_losses += 1
        except Exception:
            continue

    msg = (
        f"\ud83d\udcca RELAT\u00d3RIO DI\u00c1RIO \u2014 {now.strftime('%d/%m/%Y')}\
"
        "------------------------------\
"
        "\ud83d\udcc8 Hoje:\
"
        f"   Trades: {day_trades} ({day_wins}W / {day_losses}L)\
"
        f"   P&L: ${round(day_pnl, 2)}\
"
        "\
"
        "\ud83d\udcb0 Geral:\
"
        f"   Saldo: ${round(bot.balance, 2)}\
"
        f"   Total trades: {metrics['total_trades']}\
"
        f"   WR: {metrics['winrate']}%\
"
        f"   Profit Factor: {metrics['profit_factor']}\
"
        f"   Expectancy: ${metrics['expectancy']}/trade\
"
        f"   Max Drawdown: {metrics['max_drawdown_pct']}%"
    )
    bot.send(msg)
    save_metrics(metrics)
    append_log("daily_report", metrics)


def send_error_notification(bot, error_msg: str, traceback_str: str = ""):
    """Notifica\u00e7\u00e3o de erro/crash \u2014 tolerante a falhas do pr\u00f3prio send."""
    msg = (
        "\ud83d\udea8 ERRO NO BOT\
"
        "------------------------------\
"
        f"\u274c {error_msg[:200]}\
"
    )
    if traceback_str:
        msg += f"\
\ud83d\udccb Traceback:\
{traceback_str[:500]}\
"
    msg += f"\
\ud83d\udd50 {datetime.now().strftime('%d/%m %H:%M:%S UTC')}"
    try:
        bot.send(msg)
    except Exception:
        pass
    append_log("error", {"message": error_msg, "traceback": traceback_str})


def _send_confluence_report(bot):
    """Resposta ao comando /confluencia no Telegram."""
    from signals import get_confluence_snapshot
    from ai_validator import load_ai_params
    from utils import get_allowed_symbols

    bot.send("\u23f3 Calculando conflu\u00eancia...")
    try:
        snapshot        = get_confluence_snapshot()
        ai_params       = load_ai_params()
        min_conf        = ai_params.get("live_confluence", Config.MIN_CONFLUENCE)
        live_regime     = ai_params.get("live_regime", "neutral")
        allowed_symbols = get_allowed_symbols(bot.balance)

        lines = [
            f"\ud83d\udcca CONFLU\u00caNCIA \u2014 {datetime.now(timezone.utc).strftime('%d/%m %H:%M')} UTC",
            f"Regime: {live_regime.upper()} | M\u00ednimo: {min_conf} pts",
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        ]

        for item in snapshot:
            score  = item["best_score"]
            total  = item["total"]
            direc  = item["best_dir"]
            sym    = item["symbol"]
            bar    = "\ud83d\udfe2" * min(score, 10) + "\u26aa" * max(0, min(total, 10) - score)
            h4     = "\u2705" if item["h4_aligned"] else "\u274c"
            locked = sym not in allowed_symbols

            if locked:
                status = "\ud83d\udd12"
            elif score >= min_conf:
                status = "\ud83d\udd25 SINAL"
            elif score >= min_conf - 2:
                status = "\u26a1 QUASE"
            elif score >= min_conf - 4:
                status = "\ud83d\udc40 WATCH"
            else:
                status = "\ud83d\udca4"

            lines.append(
                f"{status} {sym} {direc} {score}/{total}"
                + (" (bloqueado)" if locked else "") + "\
"
                f"  {bar}\
"
                f"  RSI:{item['rsi']} ADX:{item['adx']} H4:{h4}"
            )

        lines.append("\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        lines.append("\ud83d\udd12 = par bloqueado pelo tier de capital atual.")
        lines.append("Use /confluencia para atualizar.")
        bot.send("\
".join(lines))
    except Exception as e:
        bot.send(f"\u274c Erro ao calcular conflu\u00eancia: {e}")


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# LOOP PRINCIPAL
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def bot_loop(bot):
    last_heartbeat        = 0.0
    last_daily_report     = None
    last_weekly_learning  = 0.0
    last_monthly_analysis = 0.0
    last_near_check       = 0.0

    while True:
        now = datetime.now(timezone.utc)

        # \u2500\u2500 HEARTBEAT \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                from ai_validator import check_live_regime, load_ai_params
                regime_info = check_live_regime(bot)
                ai_p        = load_ai_params()
                send_heartbeat(bot, regime_info, ai_p)
                last_heartbeat = time.time()
            except Exception as e:
                log(f"[HEARTBEAT] Erro: {e}")

        # \u2500\u2500 RELAT\u00d3RIO DI\u00c1RIO \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if now.hour == DAILY_REPORT_HOUR and last_daily_report != now.date():
            try:
                send_daily_report(bot)
                last_daily_report = now.date()
            except Exception as e:
                log(f"[DAILY] Erro: {e}")

        # \u2500\u2500 APRENDIZADO SEMANAL (Gemini Flash \u2014 Layer 2) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if time.time() - last_weekly_learning >= WEEK_SECS:
            try:
                from ai_validator import weekly_learning
                result = weekly_learning(bot)
                if result:
                    bot.send(
                        "\ud83e\udde0 APRENDIZADO SEMANAL\
"
                        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\
"
                        f"{result.get('last_suggestion','')}\
\
"
                        f"Min confluence: {result['min_confluence']} | "
                        f"Min ADX: {result['min_adx']} | "
                        f"Min RR: {result['min_rr']}\
"
                        f"Pares bloqueados: {', '.join(result['blocked_pairs']) or 'nenhum'}"
                    )
                last_weekly_learning = time.time()
            except Exception as e:
                log(f"[LAYER2] Erro no aprendizado semanal: {e}")

        # \u2500\u2500 AN\u00c1LISE MENSAL (Gemini Flash \u2014 Layer 3) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if time.time() - last_monthly_analysis >= MONTH_SECS:
            try:
                from ai_validator import monthly_deep_analysis
                result = monthly_deep_analysis(bot)
                if result:
                    regime_pairs = result.get("regime_pairs", {})
                    regime_txt   = " | ".join(f"{k}:{v}" for k, v in regime_pairs.items())
                    bot.send(
                        "\ud83d\udd2e AN\u00c1LISE MENSAL (Estrat\u00e9gica)\
"
                        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\
"
                        f"{result.get('opus_summary','')}\
\
"
                        f"Regime: {result.get('market_regime','?').upper()} | "
                        f"Vi\u00e9s: {result.get('strategy_bias','?').upper()}\
"
                        f"Sess\u00f5es favoritas: {', '.join(result.get('favored_sessions',[])) or '\u2014'}\
"
                        f"Horas a evitar (UTC): {result.get('avoid_hours_utc',[]) or 'nenhuma'}\
\
"
                        f"Por par:\
{regime_txt}"
                    )
                last_monthly_analysis = time.time()
            except Exception as e:
                log(f"[LAYER3] Erro na an\u00e1lise mensal: {e}")

        # \u2500\u2500 SCAN / MONITOR \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if not bot.is_paused():
            try:
                bot.expire_pending_signals(max_age_seconds=Config.PENDING_EXPIRY_SECONDS)
                scan(bot)
                bot.monitor_trades()

                if time.time() - last_near_check >= NEAR_CHECK_INTERVAL:
                    from signals import check_near_signals
                    check_near_signals(bot)
                    last_near_check = time.time()

            except Exception as e:
                error_msg = str(e)
                tb = traceback.format_exc()
                log(f"Erro no loop: {error_msg}")
                send_error_notification(bot, error_msg, tb)
                append_log("loop_error", {"error": error_msg})

        # \u2500\u2500 COMANDOS TELEGRAM \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        if Config.BOT_TOKEN and Config.CHAT_ID:
            try:
                url  = (
                    f"https://api.telegram.org/bot{Config.BOT_TOKEN}"
                    f"/getUpdates?offset={bot.last_id + 1}&timeout=5"
                )
                resp = requests.get(url, timeout=10).json()
                if "result" in resp:
                    for u in resp["result"]:
                        if "message" in u and "text" in u["message"]:
                            txt = u["message"]["text"].strip()

                            if txt.startswith("/executar_"):
                                parts = txt.split("_")
                                if len(parts) >= 3:
                                    try:
                                        pid    = int(parts[1])
                                        amount = float(parts[2])
                                        bot.execute_pending(pid, amount)
                                    except ValueError:
                                        bot.send("❌ Formato inválido. Use /executar_<id>_<valor>")

                            elif txt in ("/confluencia", "/confluência"):
                                _send_confluence_report(bot)

                            elif txt == "/status":
                                send_heartbeat(bot)

                        bot.last_id = u["update_id"]
            except Exception:
                pass

        time.sleep(Config.SCAN_INTERVAL)


# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
# ENTRYPOINT
# \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

def main():
    log("Iniciando Sniper Bot v2 (Forex + Gold H1 \u2014 modo sinalizador)")
    bot = TradingBot()

    # 1. Carrega estado persistido
    state_loaded = load_state(bot)

    # 2. \ud83d\udd34 FIX: for\u00e7a refresh inicial dos dados de mercado antes do primeiro scan,
    #    para evitar que o bot fique "cego" nos primeiros ciclos caso o cache esteja vazio.
    try:
        from analysis import force_initial_refresh
        log("Executando refresh inicial de mercado (Twelve Data)...")
        force_initial_refresh()
    except Exception as e:
        log(f"[INIT] Falha no refresh inicial: {e}")

    # 3. Notifica\u00e7\u00e3o de startup
    if STARTUP_NOTIFICATION:
        try:
            send_startup_notification(bot)
        except Exception as e:
            log(f"[STARTUP] Erro ao enviar notifica\u00e7\u00e3o: {e}")

    append_log("init", {
        "balance":      bot.balance,
        "state_loaded": state_loaded,
        "leverage":     bot.get_current_leverage(),
        "signal_only":  Config.BOT_IS_SIGNAL_ONLY,
    })

    # 4. Sobe thread do loop principal
    threading.Thread(target=bot_loop, args=(bot,), daemon=True).start()

    # 5. Sobe API Flask
    app  = create_api(bot)
    port = int(os.environ.get("PORT", 8080))
    log(f"API HTTP escutando em 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
