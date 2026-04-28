import time
import threading
import requests
import os
import traceback
from datetime import datetime
from config import Config
from utils import log
from db import load_state, save_state, append_log, save_metrics, calculate_metrics
from bot import TradingBot
from signals import scan
from api import create_api

# ═══════════════════════════════════════════════════════════
# CONFIGURAÇÕES DE HEARTBEAT
# ═══════════════════════════════════════════════════════════
HEARTBEAT_INTERVAL = 3600       # 1 hora — notificação "estou vivo"
DAILY_REPORT_HOUR = 21          # 21:00 UTC — relatório diário
STARTUP_NOTIFICATION = True     # Notifica quando inicia


def send_startup_notification(bot):
    """Envia notificação de inicialização com resumo do estado."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0

    msg = (
        "🚀 SNIPER BOT INICIADO\n"
        "------------------------------\n"
        "💰 Saldo: $" + str(round(bot.balance, 2)) + "\n"
        "📊 Win Rate: " + str(wr) + "% (" + str(bot.wins) + "W / " + str(bot.losses) + "L)\n"
        "📈 Trades ativos: " + str(len(bot.active_trades)) + "\n"
        "⏳ Pendentes: " + str(len(bot.pending_trades)) + "\n"
        "⚡ Alavancagem atual: " + str(bot.get_current_leverage()) + "x\n"
    )

    if bot.is_paused():
        msg += "⛔ Status: PAUSADO (circuit breaker)\n"
    else:
        msg += "✅ Status: OPERANDO\n"

    msg += "🕐 Iniciado: " + datetime.now().strftime("%d/%m %H:%M UTC")

    bot.send(msg)
    append_log("startup", {"balance": bot.balance, "winrate": wr})


def send_heartbeat(bot, regime_info: dict = None, ai_params: dict = None):
    """Envia heartbeat periódico confirmando que o bot está vivo."""
    total = bot.wins + bot.losses
    wr = round(bot.wins / total * 100, 1) if total > 0 else 0

    regime_info = regime_info or {}
    live_regime = regime_info.get("live_regime", "neutral")
    avg_adx     = regime_info.get("avg_adx", 0)
    eff_conf    = regime_info.get("effective_conf", 7)

    regime_emoji = {"ranging": "〰️", "trending": "📈", "neutral": "➡️", "volatile": "⚡"}.get(live_regime, "➡️")

    msg = (
        "💓 HEARTBEAT — Bot operando normalmente\n"
        "——————————————————\n"
        "💰 Saldo: $" + str(round(bot.balance, 2)) + "\n"
        "📊 WR: " + str(wr) + "% | " + str(bot.wins) + "W / " + str(bot.losses) + "L\n"
        "📈 Ativos: " + str(len(bot.active_trades)) + " | Pendentes: " + str(len(bot.pending_trades)) + "\n"
        "⚡ Alav: " + str(bot.get_current_leverage()) + "x\n"
        "——————————————————\n"
        f"{regime_emoji} Regime: {live_regime.upper()} (ADX médio={avg_adx})\n"
        f"🎯 Confluência mínima atual: {eff_conf}/11"
    )

    bot.send(msg)
    append_log("heartbeat", {"balance": bot.balance, "winrate": wr})


def send_daily_report(bot):
    """Envia relatório diário de performance."""
    from db import load_metrics

    metrics = calculate_metrics(bot)
    prev_metrics = load_metrics()

    # Calcula mudanças do dia
    day_pnl = 0
    day_trades = 0
    day_wins = 0
    day_losses = 0

    now = datetime.utcnow()
    for h in bot.history:
        # Parse do formato "dd/mm HH:MM"
        try:
            trade_time = datetime.strptime(h["closed_at"], "%d/%m %H:%M")
            trade_time = trade_time.replace(year=now.year)
            if trade_time.date() == now.date():
                day_pnl += h["pnl"]
                day_trades += 1
                if h["result"] == "WIN":
                    day_wins += 1
                else:
                    day_losses += 1
        except:
            continue

    msg = (
        "📊 RELATÓRIO DIÁRIO — " + now.strftime("%d/%m/%Y") + "\n"
        "------------------------------\n"
        "📈 Hoje:\n"
        "   Trades: " + str(day_trades) + " (" + str(day_wins) + "W / " + str(day_losses) + "L)\n"
        "   P&L: $" + str(round(day_pnl, 2)) + "\n"
        "\n"
        "💰 Geral:\n"
        "   Saldo: $" + str(round(bot.balance, 2)) + "\n"
        "   Total trades: " + str(metrics["total_trades"]) + "\n"
        "   WR: " + str(metrics["winrate"]) + "%\n"
        "   Profit Factor: " + str(metrics["profit_factor"]) + "\n"
        "   Expectancy: $" + str(metrics["expectancy"]) + "/trade\n"
        "   Max Drawdown: " + str(metrics["max_drawdown_pct"]) + "%"
    )

    bot.send(msg)
    save_metrics(metrics)
    append_log("daily_report", metrics)


def send_error_notification(bot, error_msg, traceback_str=""):
    """Envia notificação de erro/crash."""
    msg = (
        "🚨 ERRO NO BOT\n"
        "------------------------------\n"
        "❌ " + error_msg[:200] + "\n"
    )
    if traceback_str:
        msg += "\n📋 Traceback:\n" + traceback_str[:500] + "\n"
    msg += "\n🕐 " + datetime.now().strftime("%d/%m %H:%M:%S UTC")

    try:
        bot.send(msg)
    except:
        pass  # Se o próprio send falhar, não crasha

    append_log("error", {"message": error_msg, "traceback": traceback_str})


def bot_loop(bot):
    last_heartbeat = 0
    last_daily_report = None
    last_weekly_learning  = 0   # controla aprendizado semanal (Sonnet)
    last_monthly_analysis = 0   # controla análise estratégica mensal (Opus)

    while True:
        now = datetime.utcnow()

        # ── HEARTBEAT ──────────────────────────────────────────────
        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
            try:
                # Detecta regime de mercado em tempo real (sem API)
                from ai_validator import check_live_regime, load_ai_params
                regime_info = check_live_regime(bot)
                ai_p        = load_ai_params()

                send_heartbeat(bot, regime_info, ai_p)
                last_heartbeat = time.time()
            except Exception as e:
                log(f"[HEARTBEAT] Erro: {e}")

        # ── RELATÓRIO DIÁRIO ───────────────────────────────────────
        if now.hour == DAILY_REPORT_HOUR and last_daily_report != now.date():
            try:
                send_daily_report(bot)
                last_daily_report = now.date()
            except Exception as e:
                log(f"[DAILY] Erro: {e}")

        # ── APRENDIZADO SEMANAL (Sonnet) ───────────────────────────
        WEEK_SECS = 7 * 24 * 3600
        if time.time() - last_weekly_learning >= WEEK_SECS:
            try:
                from ai_validator import weekly_learning
                result = weekly_learning(bot)
                if result:
                    bot.send(
                        f"🧠 APRENDIZADO SEMANAL (Sonnet)\n"
                        f"——————————————————\n"
                        f"{result.get('last_suggestion', '')}\n\n"
                        f"Min confluence: {result['min_confluence']} | "
                        f"Min ADX: {result['min_adx']} | "
                        f"Min RR: {result['min_rr']}\n"
                        f"Pares bloqueados: {', '.join(result['blocked_pairs']) or 'nenhum'}"
                    )
                last_weekly_learning = time.time()
            except Exception as e:
                log(f"[SONNET] Erro no aprendizado semanal: {e}")

        # ── ANÁLISE ESTRATÉGICA MENSAL (Opus) ─────────────────────
        MONTH_SECS = 30 * 24 * 3600
        if time.time() - last_monthly_analysis >= MONTH_SECS:
            try:
                from ai_validator import monthly_deep_analysis
                result = monthly_deep_analysis(bot)
                if result:
                    regime_pairs = result.get("regime_pairs", {})
                    regime_txt   = " | ".join(f"{k}:{v}" for k, v in regime_pairs.items())
                    avoid_hours  = result.get("avoid_hours_utc", [])
                    bot.send(
                        f"🔮 ANÁLISE ESTRATÉGICA MENSAL (Opus)\n"
                        f"——————————————————\n"
                        f"{result.get('opus_summary', '')}\n\n"
                        f"Regime geral: {result.get('market_regime','?').upper()}\n"
                        f"Viés: {result.get('strategy_bias','?').upper()}\n"
                        f"Sessões favoritas: {', '.join(result.get('favored_sessions', [])) or '—'}\n"
                        f"Horas a evitar (UTC): {avoid_hours or 'nenhuma'}\n\n"
                        f"Regime por par:\n{regime_txt}"
                    )
                last_monthly_analysis = time.time()
            except Exception as e:
                log(f"[OPUS] Erro na análise mensal: {e}")

        # ── LOOP PRINCIPAL ─────────────────────────────────────────
        if not bot.is_paused():
            try:
                bot.expire_pending_signals(max_age_seconds=7200)  # expira sinais com +2h
                scan(bot)
                bot.monitor_trades()
            except Exception as e:
                error_msg = str(e)
                tb = traceback.format_exc()
                log(f"Erro no loop: {error_msg}")
                send_error_notification(bot, error_msg, tb)
                append_log("loop_error", {"error": error_msg})

        # ── COMANDOS DO TELEGRAM ───────────────────────────────────
        try:
            url = "https://api.telegram.org/bot" + Config.BOT_TOKEN + "/getUpdates?offset=" + str(bot.last_id+1) + "&timeout=5"
            resp = requests.get(url, timeout=10).json()
            if "result" in resp:
                for u in resp["result"]:
                    if "message" in u and "text" in u["message"]:
                        txt = u["message"]["text"].strip()
                        if txt.startswith("/executar_"):
                            parts = txt.split("_")
                            if len(parts) >= 3:
                                pid = int(parts[1])
                                amount = float(parts[2])
                                bot.execute_pending(pid, amount)
                    bot.last_id = u["update_id"]
        except Exception:
            pass

        time.sleep(Config.SCAN_INTERVAL)


def main():
    log("Iniciando Sniper Bot v2 (Twelve Data, Forex+Ouro H1)")
    bot = TradingBot()

    # Carrega estado salvo
    state_loaded = load_state(bot)

    # Notificação de inicialização
    if STARTUP_NOTIFICATION:
        try:
            send_startup_notification(bot)
        except Exception as e:
            log(f"[STARTUP] Erro ao enviar notificação: {e}")

    # Log de inicialização
    append_log("init", {
        "balance": bot.balance,
        "state_loaded": state_loaded,
        "leverage": bot.get_current_leverage(),
    })

    # Inicia threads
    threading.Thread(target=bot_loop, args=(bot,), daemon=True).start()

    # Inicia API
    app = create_api(bot)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
